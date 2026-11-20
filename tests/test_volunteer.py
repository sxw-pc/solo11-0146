import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import volunteer
from volunteer import call,credential,attendance,beneficiary,report
from volunteer.store import connect
print('imported module:',volunteer.__file__)
assert Path(volunteer.__file__).resolve().is_relative_to(ROOT)

def fixture(name):return json.loads((ROOT/'fixtures'/'volunteer'/name).read_text(encoding='utf-8'))

class VolunteerCases(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'test.sqlite')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def good(self):
        call.ingest(self.db,fixture('call_good.json'))
        credential.ingest(self.db,fixture('skill_good.json'))
        attendance.ingest(self.db,fixture('attend_good.json'))

    def test_three_ledgers_credit_distinct_hours(self):
        self.good();r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual([(h['volunteer_id'],h['minutes'],h['decision']) for h in r['hours']],[('v1',120,'credited'),('v2',60,'credited')])

    def test_shrink_keeps_waitlist_and_organizer_responsibility(self):
        self.good();call.ingest(self.db,fixture('call_changed.json'))
        r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual(r['rosters']['s1']['people'][1]['decision'],'waitlist')
        self.assertEqual((r['hours'][1]['decision'],r['hours'][1]['absence']),('frozen','organizer_reduced'))

    def test_credential_revocation_freezes_existing_attendance(self):
        self.good();credential.ingest(self.db,fixture('skill_expired.json'))
        r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual((r['assignments']['s1'][0]['decision'],r['hours'][0]['decision'],r['hours'][0]['absence']),('unassigned','frozen','qualification_withdrawn'))
        self.assertEqual(r['hours'][1]['minutes'],60)

    def test_untrusted_issuer_cannot_staff_special_role(self):
        call.ingest(self.db,fixture('call_good.json'))
        bad=dict(fixture('skill_good.json')[0],issuer='unknown')
        credential.ingest(self.db,[bad])
        r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual(r['assignments']['s1'][0]['reason'],'issuer_untrusted')

    def test_late_signup_is_waitlist_even_when_capacity_open(self):
        call.ingest(self.db,fixture('call_good.json')[:1])
        late=dict(fixture('call_good.json')[1],event_id='late-signup',promised_at='2026-11-17T09:40:00Z',event_time='2026-11-17T09:40:00Z')
        call.ingest(self.db,[late])
        self.assertEqual(call.roster(self.db,'s1','2026-11-17T10:00:00Z')['people'][0]['reason'],'after_deadline')

    def test_attendance_outside_shift_counts_intersection_only(self):
        self.good();attendance.ingest(self.db,fixture('attend_overlap.json'))
        r=report.decide(self.db,'2026-11-17T13:00:00Z')
        self.assertEqual(r['hours'][0]['minutes'],120)

    def test_wrong_site_rejects_hours_without_changing_assignment(self):
        self.good();bad=dict(fixture('attend_good.json')[0],event_id='att-wrong',site='south',event_time='2026-11-17T12:20:00Z')
        attendance.ingest(self.db,[bad]);r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual((r['assignments']['s1'][0]['decision'],r['hours'][0]['reason']),('assigned','wrong_site'))

    def test_self_approved_hours_rejected(self):
        self.good();bad=dict(fixture('attend_good.json')[2],event_id='approve-self',supervisor='v1',event_time='2026-11-17T12:20:00Z')
        attendance.ingest(self.db,[bad]);r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual(r['hours'][0]['reason'],'self_review')

    def test_cross_shift_overlap_not_double_counted(self):
        self.good()
        second=dict(fixture('call_good.json')[0],event_id='call-s2',shift_id='s2',starts_at='2026-11-17T11:00:00Z',ends_at='2026-11-17T13:00:00Z',skill='general',site='south')
        signup=dict(fixture('call_good.json')[1],event_id='signup-s2',shift_id='s2')
        call.ingest(self.db,[second,signup])
        att={'event_id':'att-s2','op':'attendance','shift_id':'s2','volunteer_id':'v1','site':'south','arrived_at':'2026-11-17T11:00:00Z','left_at':'2026-11-17T13:00:00Z','event_time':'2026-11-17T13:05:00Z'}
        approve={'event_id':'approve-s2','op':'approval','shift_id':'s2','volunteer_id':'v1','supervisor':'supervisor-y','decision':'approve','event_time':'2026-11-17T13:10:00Z'}
        attendance.ingest(self.db,[att,approve])
        r=report.decide(self.db,'2026-11-17T13:20:00Z')
        self.assertEqual(sum(h['minutes'] for h in r['hours'] if h['volunteer_id']=='v1'),180)

    def test_no_show_is_different_from_organizer_cancel(self):
        call.ingest(self.db,fixture('call_good.json'))
        credential.ingest(self.db,fixture('skill_good.json'))
        r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual(r['hours'][0]['absence'],'volunteer_no_show')
        cancelled=dict(fixture('call_good.json')[0],event_id='call-cancel',version=2,status='cancelled',event_time='2026-11-17T09:20:00Z')
        call.ingest(self.db,[cancelled]);r=report.decide(self.db,'2026-11-17T12:30:00Z')
        self.assertEqual(r['hours'][0]['absence'],'organizer_reduced')

    def test_duplicate_event_id_new_content_rolls_back(self):
        self.good();bad=dict(fixture('attend_good.json')[0],site='south')
        with self.assertRaises(ValueError):attendance.ingest(self.db,[dict(bad,event_id='new-att'),bad])
        self.assertIsNone(self.db.execute("SELECT event_id FROM evidence WHERE event_id='new-att'").fetchone())

class BeneficiaryEvaluationCases(unittest.TestCase):
    AS_OF='2026-11-17T18:00:00Z'
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'test.sqlite')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def base(self,surveys=None,contracts=None):
        call.ingest(self.db,fixture('call_good.json'))
        credential.ingest(self.db,fixture('skill_good.json'))
        attendance.ingest(self.db,fixture('attend_good.json'))
        beneficiary.ingest(self.db,fixture('invite_frozen.json'))
        beneficiary.ingest(self.db,fixture('delivery_dual.json'))
        beneficiary.ingest(self.db,fixture('survey_complete.json') if surveys is None else surveys)
        beneficiary.ingest(self.db,fixture('contracts_two.json') if contracts is None else contracts)
    def contracts(self,r):
        return {c['contract_id']:c for c in r['evaluation']['rounds']['r1']['contracts']}

    def test_two_contracts_distinct_estimates_on_same_originals(self):
        self.base();r=report.decide(self.db,self.AS_OF)
        rd=r['evaluation']['rounds']['r1']
        self.assertEqual(rd['group_counts'],{'invited':2,'control':2})
        self.assertEqual(rd['delivered_counts'],{'invited':1,'control':0})
        self.assertEqual(rd['observed_counts'],{'invited':2,'control':2})
        c=self.contracts(r);a,b=c['contract-a'],c['contract-b']
        self.assertEqual((a['status'],a['estimate']),('estimated',0.5))
        self.assertEqual((a['numerator'],a['denominator']),({'outcome_sum_invited':1,'outcome_sum_control':0},{'n_invited':2,'n_control':2}))
        self.assertEqual((b['status'],b['estimate']),('estimated',1.0))
        self.assertEqual((b['numerator']['value'],b['denominator']['value']),(0.5,0.5))
        frozen={x['check']:x['status'] for x in b['assumption_checks']}
        for key in ('assumption:random_assignment','assumption:monotonic_compliance_exclusion','assumption:no_interference'):
            self.assertEqual(frozen[key],'frozen_unverifiable')
        self.assertEqual(frozen['first_stage_nonzero'],'pass')
        kinds={o['kind'] for o in rd['originals']['invites']}|{o['kind'] for o in rd['originals']['deliveries']}|{o['kind'] for o in rd['originals']['surveys']}
        self.assertEqual(kinds,{'invite','delivery','questionnaire'})
        sample=rd['originals']['invites'][0]
        self.assertTrue({'sha256','recorded_at','business_time','version'}<=set(sample))

    def test_itt_keeps_households_of_no_show_volunteers(self):
        call.ingest(self.db,fixture('call_good.json'))
        credential.ingest(self.db,fixture('skill_good.json'))
        attendance.ingest(self.db,[e for e in fixture('attend_good.json') if e['volunteer_id']=='v1'])
        for name in ('invite_frozen.json','delivery_dual.json','survey_complete.json','contracts_two.json'):
            beneficiary.ingest(self.db,fixture(name))
        r=report.decide(self.db,self.AS_OF)
        self.assertEqual(r['hours'][1]['absence'],'volunteer_no_show')
        rd=r['evaluation']['rounds']['r1']
        self.assertEqual(rd['grouping']['invited'],['hh-a','hh-b'])
        self.assertEqual(rd['group_counts'],{'invited':2,'control':2})
        self.assertEqual(self.contracts(r)['contract-a']['estimate'],0.5)

    def test_missing_questionnaire_sends_estimates_to_pending(self):
        surveys=[e for e in fixture('survey_complete.json') if e['household_id']!='hh-b']
        self.base(surveys=surveys);r=report.decide(self.db,self.AS_OF)
        rd=r['evaluation']['rounds']['r1']
        self.assertEqual(rd['observed_counts'],{'invited':1,'control':2})
        self.assertIn('questionnaire_missing',rd['markers']['hh-b'])
        for c in self.contracts(r).values():
            self.assertEqual((c['status'],c['estimate']),('pending_review',None))
            self.assertIn('follow_up_incomplete',c['reasons'])

    def test_refusal_is_not_zero_result(self):
        surveys=[dict(e,status='refused') if e['household_id']=='hh-b' else e for e in fixture('survey_complete.json')]
        for e in surveys:
            if e['status']=='refused':e.pop('outcome')
        self.base(surveys=surveys);r=report.decide(self.db,self.AS_OF)
        rd=r['evaluation']['rounds']['r1']
        self.assertIn('questionnaire_refused',rd['markers']['hh-b'])
        self.assertEqual(rd['observed_counts'],{'invited':1,'control':2})
        self.assertIn('hh-d',rd['observed']['control'])
        for c in self.contracts(r).values():self.assertEqual(c['status'],'pending_review')

    def test_late_control_delivery_zero_first_stage_keeps_history(self):
        self.base();r1=report.decide(self.db,self.AS_OF)
        self.assertEqual(self.contracts(r1)['contract-b']['estimate'],1.0)
        beneficiary.ingest(self.db,fixture('delivery_late_control.json'))
        r2=report.decide(self.db,'2026-11-17T19:00:00Z')
        rd=r2['evaluation']['rounds']['r1']
        self.assertEqual(rd['delivered_counts'],{'invited':1,'control':1})
        self.assertIn('cross_group_delivery',rd['markers']['hh-c'])
        c=self.contracts(r2)
        self.assertEqual((c['contract-a']['status'],c['contract-a']['estimate']),('estimated',0.5))
        b=c['contract-b']
        self.assertEqual((b['status'],b['estimate']),('pending_review',None))
        self.assertIn('first_stage_zero',b['reasons'])
        self.assertNotEqual(b['estimate'],0.5)
        self.assertEqual(b['previous'],{'report_id':r1['report_id'],'status':'estimated','estimate':1.0})
        self.assertEqual(r2['evaluation']['previous_report_id'],r1['report_id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) c FROM report_history').fetchone()['c'],2)

    def test_credential_revocation_keeps_dual_signed_delivery(self):
        self.base();credential.ingest(self.db,fixture('skill_expired.json'))
        r=report.decide(self.db,self.AS_OF)
        self.assertEqual((r['hours'][0]['decision'],r['hours'][0]['absence']),('frozen','qualification_withdrawn'))
        rd=r['evaluation']['rounds']['r1']
        self.assertEqual(rd['delivered_counts'],{'invited':1,'control':0})
        self.assertEqual(rd['qualification_disputes'][0]['volunteer_id'],'v1')
        c=self.contracts(r)
        self.assertEqual((c['contract-a']['status'],c['contract-a']['estimate']),('estimated',0.5))
        self.assertEqual(c['contract-b']['status'],'pending_review')
        self.assertIn('qualification_dispute',c['contract-b']['reasons'])

    def test_invite_same_version_conflict_not_resolved_by_order(self):
        clashing=[{'event_id':'inv-x1','op':'invite','round_id':'r1','household_id':'hh-a','arm':'invited','version':1,'frozen_at':'2026-11-17T07:00:00Z','event_time':'2026-11-17T07:05:00Z'},
                  {'event_id':'inv-x2','op':'invite','round_id':'r1','household_id':'hh-a','arm':'control','version':1,'frozen_at':'2026-11-17T07:00:00Z','event_time':'2026-11-17T07:05:00Z'}]
        rest=[e for e in fixture('invite_frozen.json') if e['household_id']!='hh-a']
        for first in (0,1):
            with self.subTest(first=first):
                tmp=tempfile.TemporaryDirectory();db=connect(Path(tmp.name)/'t.sqlite')
                ordered=clashing if first==0 else clashing[::-1]
                beneficiary.ingest(db,ordered+rest)
                beneficiary.ingest(db,fixture('delivery_dual.json'))
                beneficiary.ingest(db,fixture('survey_complete.json'))
                beneficiary.ingest(db,fixture('contracts_two.json'))
                r=report.decide(db,self.AS_OF);rd=r['evaluation']['rounds']['r1']
                self.assertIn('invite_conflict',rd['markers']['hh-a'])
                self.assertEqual(rd['conflicts'][0]['reason'],'invite_same_version_conflict')
                self.assertNotIn('hh-a',rd['grouping']['invited']+rd['grouping']['control'])
                for c in {x['contract_id']:x for x in rd['contracts']}.values():
                    self.assertEqual(c['status'],'pending_review')
                    self.assertIn('grouping_disputed',c['reasons'])
                db.close();tmp.cleanup()

    def test_multiple_deliveries_count_once_under_exposure_definition(self):
        self.base()
        extra=dict(fixture('delivery_dual.json')[0],event_id='dlv-hh-a-2',version=2,delivered_at='2026-11-17T11:45:00Z',event_time='2026-11-17T11:50:00Z')
        beneficiary.ingest(self.db,[extra])
        r=report.decide(self.db,self.AS_OF)
        rd=r['evaluation']['rounds']['r1']
        self.assertEqual(rd['delivered_counts'],{'invited':1,'control':0})
        self.assertEqual(self.contracts(r)['contract-b']['estimate'],1.0)

    def test_invite_frozen_after_signup_rejected(self):
        call.ingest(self.db,fixture('call_good.json'))
        late=dict(fixture('invite_frozen.json')[0],event_id='inv-late',frozen_at='2026-11-17T10:00:00Z')
        with self.assertRaises(ValueError):beneficiary.ingest(self.db,[late])
        self.assertEqual(self.db.execute('SELECT COUNT(*) c FROM invite_roster').fetchone()['c'],0)

    def test_unknown_household_marked_without_blocking_clean_estimates(self):
        self.base()
        alien=dict(fixture('delivery_dual.json')[0],event_id='dlv-hh-z',household_id='hh-z')
        beneficiary.ingest(self.db,[alien])
        r=report.decide(self.db,self.AS_OF)
        rd=r['evaluation']['rounds']['r1']
        self.assertIn('unknown_household',rd['markers']['hh-z'])
        self.assertEqual(rd['delivered_counts'],{'invited':1,'control':0})
        self.assertEqual(self.contracts(r)['contract-a']['estimate'],0.5)

    def test_complier_contract_without_frozen_assumptions_stays_pending(self):
        contracts=fixture('contracts_two.json')
        contracts[1]=dict(contracts[1],assumptions=[])
        self.base(contracts=contracts);r=report.decide(self.db,self.AS_OF)
        c=self.contracts(r)
        self.assertEqual((c['contract-a']['status'],c['contract-a']['estimate']),('estimated',0.5))
        self.assertEqual(c['contract-b']['status'],'pending_review')
        self.assertIn('assumptions_not_frozen',c['contract-b']['reasons'])

if __name__=='__main__':unittest.main()