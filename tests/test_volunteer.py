import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import volunteer
from volunteer import call,credential,attendance,report
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

if __name__=='__main__':unittest.main()
