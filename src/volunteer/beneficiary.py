"""Beneficiary originals: frozen invitation lists, dual-signed delivery slips,
independent outcome surveys and signed evaluation contracts.

All records are synthetic and offline. Every original keeps its SHA-256 digest
and ingestion time in the evidence table, and its business time plus version in
its own table. Grouping comes only from the frozen invitation list; it is never
derived from attendance, eligibility or survey completion. Same-version
divergence or cross-table identity conflicts stay disputed and are never
resolved by import order.
"""
import json
from .sources import record
from .store import rows

ARMS=('invited','control')
REQUIRED_ASSUMPTIONS=('random_assignment','monotonic_compliance_exclusion','no_interference')
EXPOSURES=('any_confirmed_delivery',)


def _earliest_activity(db):
    stamps=[]
    for sql in ('SELECT promised_at AS t FROM shift_signup',
                'SELECT arrived_at AS t FROM attendance_event',
                'SELECT delivered_at AS t FROM delivery_slip'):
        stamps+=[r['t'] for r in rows(db,sql)]
    return min(stamps) if stamps else None


def ingest(db,events):
    made=0
    with db:
        for e in events:
            op=e['op']
            if op=='invite':
                if e['arm'] not in ARMS:raise ValueError('unknown invite arm '+e['arm'])
                known=db.execute('SELECT 1 FROM evidence WHERE event_id=?',(e['event_id'],)).fetchone()
                if not known:
                    first=_earliest_activity(db)
                    if first and e['frozen_at']>first:raise ValueError('invite list not frozen before signup/dispatch')
                if record(db,e,'invite',e['household_id']):
                    db.execute('INSERT INTO invite_roster VALUES (?,?,?,?,?,?)',
                               (e['event_id'],e['round_id'],e['household_id'],e['arm'],e['version'],e['frozen_at']));made+=1
            elif op=='delivery':
                if record(db,e,'delivery',e['household_id']):
                    db.execute('INSERT INTO delivery_slip VALUES (?,?,?,?,?,?,?,?,?)',
                               (e['event_id'],e['round_id'],e['household_id'],e['volunteer_id'],e.get('shift_id'),
                                int(bool(e.get('household_sign'))),int(bool(e.get('volunteer_sign'))),e['delivered_at'],e['version']));made+=1
            elif op=='questionnaire':
                if e['status'] not in ('completed','refused'):raise ValueError('unknown questionnaire status '+e['status'])
                if (e['status']=='completed')!=(e.get('outcome') is not None):raise ValueError('outcome required iff questionnaire completed')
                if record(db,e,'questionnaire',e['household_id']):
                    db.execute('INSERT INTO outcome_survey VALUES (?,?,?,?,?,?,?,?)',
                               (e['event_id'],e['round_id'],e['household_id'],e['investigator'],e['status'],e.get('outcome'),e['surveyed_at'],e['version']));made+=1
            elif op=='contract':
                if e['kind'] not in ('invite_policy','complier_effect'):raise ValueError('unknown contract kind '+e['kind'])
                if record(db,e,'contract',e['contract_id']):
                    db.execute('INSERT INTO evaluation_contract VALUES (?,?,?,?,?,?,?,?,?)',
                               (e['event_id'],e['contract_id'],e['round_id'],e['kind'],
                                json.dumps(e.get('assumptions',[]),ensure_ascii=False,sort_keys=True),
                                int(bool(e.get('qualification_prerequisite'))),e.get('exposure','any_confirmed_delivery'),
                                e['signed_at'],e['version']));made+=1
            else:raise ValueError('unknown beneficiary op '+op)
    return {'imported':made,'rounds':len(rows(db,'SELECT DISTINCT round_id FROM evaluation_contract'))}


def _consistent_group(records,key,fields):
    """Highest version per key wins; same-version divergence stays disputed."""
    by={}
    for r in records:by.setdefault(r[key],{}).setdefault(r['version'],[]).append(r)
    ok={};disputed={}
    for k,versions in by.items():
        top=versions[max(versions)]
        if len({tuple(r[f] for f in fields) for r in top})>1:disputed[k]=top
        else:ok[k]=top[0]
    return ok,disputed


def _original(rec,kind):
    base={'event_id':rec['event_id'],'kind':kind,'version':rec['version'],'recorded_at':rec['event_time'],'sha256':rec['sha256']}
    if kind=='invite':base.update(household_id=rec['household_id'],arm=rec['arm'],business_time=rec['frozen_at'])
    elif kind=='delivery':base.update(household_id=rec['household_id'],volunteer_id=rec['volunteer_id'],household_sign=bool(rec['household_sign']),volunteer_sign=bool(rec['volunteer_sign']),business_time=rec['delivered_at'])
    elif kind=='questionnaire':base.update(household_id=rec['household_id'],investigator=rec['investigator'],status=rec['status'],outcome=rec['outcome'],business_time=rec['surveyed_at'])
    else:base.update(contract_id=rec['contract_id'],contract_kind=rec['kind'],business_time=rec['signed_at'])
    return base


def evaluate(db,as_of,hours=None):
    if hours is None:hours=rows(db,'SELECT shift_id,volunteer_id,absence,reason FROM absence_case')
    withdrawn={h['volunteer_id'] for h in hours if h.get('absence')=='qualification_withdrawn'}
    round_ids=[r['round_id'] for r in rows(db,'SELECT round_id FROM invite_roster UNION SELECT round_id FROM delivery_slip UNION SELECT round_id FROM outcome_survey UNION SELECT round_id FROM evaluation_contract ORDER BY 1')]
    out={'rounds':{}}
    for rid in round_ids:
        invites=rows(db,'SELECT i.*,e.event_time,e.sha256 FROM invite_roster i JOIN evidence e USING(event_id) WHERE i.round_id=? AND e.event_time<=? ORDER BY i.version,i.event_id',(rid,as_of))
        slips=rows(db,'SELECT d.*,e.event_time,e.sha256 FROM delivery_slip d JOIN evidence e USING(event_id) WHERE d.round_id=? AND e.event_time<=? ORDER BY d.version,d.event_id',(rid,as_of))
        surveys=rows(db,'SELECT q.*,e.event_time,e.sha256 FROM outcome_survey q JOIN evidence e USING(event_id) WHERE q.round_id=? AND e.event_time<=? ORDER BY q.version,q.event_id',(rid,as_of))
        contracts_raw=rows(db,'SELECT c.*,e.event_time,e.sha256 FROM evaluation_contract c JOIN evidence e USING(event_id) WHERE c.round_id=? AND e.event_time<=? ORDER BY c.version,c.event_id',(rid,as_of))

        arm_of,invite_disputed=_consistent_group(invites,'household_id',('arm',))
        grouping={a:sorted(h for h in arm_of if arm_of[h]['arm']==a) for a in ARMS}

        confirmed={};unconfirmed=set();delivery_conflicts=[]
        by_hh_ver={}
        for s in slips:by_hh_ver.setdefault((s['household_id'],s['version']),[]).append(s)
        for (hh,ver),group in sorted(by_hh_ver.items()):
            vals={(g['volunteer_id'],g['delivered_at'],g['household_sign'],g['volunteer_sign']) for g in group}
            if len(vals)>1:
                delivery_conflicts.append({'household_id':hh,'version':ver,'reason':'delivery_same_version_conflict','records':sorted(g['event_id'] for g in group)})
            else:
                g=group[0]
                if g['household_sign'] and g['volunteer_sign']:confirmed.setdefault(hh,[]).append(g)
                else:unconfirmed.add(hh)

        survey_of,survey_disputed=_consistent_group(surveys,'household_id',('status','outcome','investigator'))

        conflicts=[];markers={}
        def mark(hh,m):
            markers.setdefault(hh,[])
            if m not in markers[hh]:markers[hh].append(m)
        for hh,group in sorted(invite_disputed.items()):
            mark(hh,'invite_conflict')
            conflicts.append({'household_id':hh,'reason':'invite_same_version_conflict','records':sorted(g['event_id'] for g in group)})
        for c in delivery_conflicts:
            mark(c['household_id'],'delivery_conflict');conflicts.append(c)
        for hh,group in sorted(survey_disputed.items()):
            mark(hh,'survey_conflict')
            conflicts.append({'household_id':hh,'reason':'survey_same_version_conflict','records':sorted(g['event_id'] for g in group)})

        observed={}
        for hh,s in sorted(survey_of.items()):
            deliverers={x['volunteer_id'] for x in confirmed.get(hh,[])}
            if s['investigator']==hh or s['investigator'] in deliverers:
                mark(hh,'investigator_not_independent')
                conflicts.append({'household_id':hh,'reason':'investigator_not_independent','records':[s['event_id']]})
            elif s['status']=='completed':observed[hh]=s['outcome']
            else:mark(hh,'questionnaire_refused')
        for hh in arm_of:
            if hh not in survey_of and hh not in survey_disputed:mark(hh,'questionnaire_missing')
        for hh in sorted(confirmed):
            if hh in arm_of and arm_of[hh]['arm']=='control':mark(hh,'cross_group_delivery')
        for hh in sorted(unconfirmed-set(confirmed)):
            if hh not in {c['household_id'] for c in delivery_conflicts}:mark(hh,'delivery_not_dual_signed')
        for hh in sorted((set(confirmed)|set(survey_of)|set(survey_disputed))-set(arm_of)):
            mark(hh,'unknown_household')
            conflicts.append({'household_id':hh,'reason':'unknown_household_not_in_frozen_invite_list','records':sorted({g['event_id'] for g in confirmed.get(hh,[])}|({survey_of[hh]['event_id']} if hh in survey_of else set())|{g['event_id'] for g in survey_disputed.get(hh,[])})})

        qual_disputes=[];seen=set()
        for hh in sorted(confirmed):
            if hh not in arm_of:continue
            for s in confirmed[hh]:
                key=(s['volunteer_id'],hh)
                if s['volunteer_id'] in withdrawn and key not in seen:
                    seen.add(key)
                    qual_disputes.append({'volunteer_id':s['volunteer_id'],'household_id':hh,'absence':'qualification_withdrawn','note':'dual-signed delivery retained; frozen hours cannot erase confirmed service'})

        group_counts={a:len(grouping[a]) for a in ARMS}
        delivered={a:sorted(h for h in grouping[a] if h in confirmed) for a in ARMS}
        delivered_counts={a:len(delivered[a]) for a in ARMS}
        observed_by_arm={a:sorted(h for h in grouping[a] if h in observed) for a in ARMS}
        observed_counts={a:len(observed_by_arm[a]) for a in ARMS}
        follow_up_gaps=sorted(h for h in arm_of if h not in observed)
        grouping_ok=not invite_disputed and all(grouping[a] for a in ARMS)
        follow_ok=not follow_up_gaps
        delivery_ok=not delivery_conflicts

        contracts={};contract_disputes={}
        by_cid={}
        for c in contracts_raw:by_cid.setdefault(c['contract_id'],{}).setdefault(c['version'],[]).append(c)
        for cid,versions in by_cid.items():
            top=versions[max(versions)]
            vals={(g['kind'],g['assumptions'],g['qualification_prerequisite'],g['exposure'],g['signed_at']) for g in top}
            if len(vals)>1:contract_disputes[cid]=sorted(g['event_id'] for g in top)
            else:contracts[cid]=top[0]

        def itt():
            s1=sum(observed[h] for h in grouping['invited']);s0=sum(observed[h] for h in grouping['control'])
            return s1/group_counts['invited']-s0/group_counts['control'],s1,s0

        results=[]
        for cid in sorted(set(contracts)|set(contract_disputes)):
            res={'contract_id':cid,'round_id':rid,'status':'estimated','estimate':None,'reasons':[],'assumption_checks':[],'previous':None}
            if cid in contract_disputes:
                res.update(status='pending_review',contract_version=None)
                res['reasons'].append('contract_disputed')
                res['assumption_checks'].append({'check':'contract_consistent','status':'fail','detail':contract_disputes[cid]})
                results.append(res);continue
            c=contracts[cid]
            assumptions=json.loads(c['assumptions'])
            res.update(kind=c['kind'],contract_version=c['version'],signed_at=c['signed_at'],exposure_definition=c['exposure'],
                       qualification_prerequisite=bool(c['qualification_prerequisite']))
            res['assumption_checks'].append({'check':'frozen_grouping','status':'pass' if grouping_ok else 'fail','detail':'grouping read only from frozen invite list'})
            if not grouping_ok:res['reasons'].append('grouping_disputed' if invite_disputed else 'grouping_missing')
            res['assumption_checks'].append({'check':'complete_follow_up','status':'pass' if follow_ok else 'fail','detail':follow_up_gaps})
            if not follow_ok:res['reasons'].append('follow_up_incomplete')
            if c['kind']=='invite_policy':
                res['assumption_checks'].append({'check':'no_household_dropped','status':'pass','detail':'households of no-show volunteers stay in their frozen arm'})
                if grouping_ok and follow_ok:
                    est,s1,s0=itt()
                    res['estimate']=est
                    res['formula']='mean(outcome|invited)-mean(outcome|control)'
                    res['numerator']={'outcome_sum_invited':s1,'outcome_sum_control':s0}
                    res['denominator']={'n_invited':group_counts['invited'],'n_control':group_counts['control']}
            else:
                frozen={a.get('key'):a for a in assumptions}
                for key in REQUIRED_ASSUMPTIONS:
                    a=frozen.get(key)
                    if a and a.get('provable_from_data') is False:
                        res['assumption_checks'].append({'check':'assumption:'+key,'status':'frozen_unverifiable','detail':a.get('statement')})
                    else:
                        res['assumption_checks'].append({'check':'assumption:'+key,'status':'missing' if a is None else 'fail','detail':'assumption must be frozen at signing and marked unprovable from this batch'})
                        res['reasons'].append('assumptions_not_frozen')
                res['assumption_checks'].append({'check':'delivery_records_consistent','status':'pass' if delivery_ok else 'fail','detail':delivery_conflicts})
                if not delivery_ok:res['reasons'].append('delivery_disputed')
                exposure_ok=c['exposure'] in EXPOSURES
                if not exposure_ok:res['reasons'].append('unknown_exposure_definition')
                if c['qualification_prerequisite']:
                    qual_ok=not qual_disputes
                    res['assumption_checks'].append({'check':'qualification_prerequisite','status':'pass' if qual_ok else 'fail','detail':qual_disputes})
                    if not qual_ok:res['reasons'].append('qualification_dispute')
                first_stage=None
                if grouping_ok and delivery_ok and exposure_ok:
                    first_stage=delivered_counts['invited']/group_counts['invited']-delivered_counts['control']/group_counts['control']
                    res['assumption_checks'].append({'check':'first_stage_nonzero','status':'pass' if first_stage!=0 else 'fail','detail':first_stage})
                    if first_stage==0:res['reasons'].append('first_stage_zero')
                if not res['reasons']:
                    est,s1,s0=itt()
                    res['estimate']=est/first_stage
                    res['formula']='invite_effect_on_outcome / invite_effect_on_delivery_rate'
                    res['numerator']={'label':'invite_effect_on_outcome','value':est}
                    res['denominator']={'label':'invite_effect_on_delivery_rate','value':first_stage}
            if res['reasons']:
                res['status']='pending_review';res['estimate']=None
                res.pop('numerator',None);res.pop('denominator',None);res.pop('formula',None)
            results.append(res)

        out['rounds'][rid]={
            'grouping':grouping,'grouping_version':max((i['version'] for i in invites),default=None),
            'group_counts':group_counts,'delivered':delivered,'delivered_counts':delivered_counts,
            'observed':observed_by_arm,'observed_counts':observed_counts,
            'exposure_definition':'any_confirmed_delivery: multiple confirmed slips count once',
            'markers':{k:sorted(v) for k,v in sorted(markers.items())},
            'conflicts':conflicts,'qualification_disputes':qual_disputes,
            'contracts':results,
            'originals':{
                'invites':[_original(i,'invite') for i in invites],
                'deliveries':[_original(s,'delivery') for s in slips],
                'surveys':[_original(q,'questionnaire') for q in surveys],
                'contracts':[_original(c,'contract') for c in contracts_raw],
            }}
    return out


def attach_previous(evaluation,prev_evaluation,prev_report_id):
    evaluation['previous_report_id']=prev_report_id
    prev={}
    if prev_evaluation:
        for rd in prev_evaluation.get('rounds',{}).values():
            for c in rd.get('contracts',[]):
                prev[c['contract_id']]={'report_id':prev_report_id,'status':c['status'],'estimate':c['estimate']}
    for rd in evaluation['rounds'].values():
        for c in rd['contracts']:
            c['previous']=prev.get(c['contract_id'])
