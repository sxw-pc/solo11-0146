"""Site-attested attendance, overlap-safe hours and absence responsibility."""
from datetime import datetime
from .sources import record
from .store import rows


def ingest(db,events):
    made=0
    with db:
        for e in events:
            if e['op']=='attendance':
                if e['arrived_at']>=e['left_at']:raise ValueError('invalid attendance interval')
                if record(db,e,'attendance',e['shift_id']):
                    db.execute('INSERT INTO attendance_event VALUES (?,?,?,?,?,?)',(e['event_id'],e['shift_id'],e['volunteer_id'],e['site'],e['arrived_at'],e['left_at']));made+=1
            elif e['op']=='approval':
                if record(db,e,'approval',e['shift_id']):
                    db.execute('INSERT INTO hours_claim VALUES (?,?,?,?,?)',(e['event_id'],e['shift_id'],e['volunteer_id'],e['supervisor'],e['decision']));made+=1
            else:raise ValueError('unknown attendance op '+e['op'])
    return {'imported':made,'attendance_events':len(rows(db,'SELECT event_id FROM attendance_event'))}


def minutes(a,b):
    return int((datetime.fromisoformat(b.replace('Z','+00:00'))-datetime.fromisoformat(a.replace('Z','+00:00'))).total_seconds()//60)


def uncovered_minutes(a,b,previous):
    intervals=sorted(previous)
    cursor=a;total=0
    for x,y in intervals:
        if y<=cursor:continue
        if x>=b:break
        if x>cursor:total+=minutes(cursor,min(x,b))
        cursor=max(cursor,y)
        if cursor>=b:break
    if cursor<b:total+=minutes(cursor,b)
    return total


def settle(db,rosters,assignments,as_of):
    db.execute('DELETE FROM hours_ledger');db.execute('DELETE FROM absence_case')
    covered={};out=[]
    for shift_id,roster in sorted(rosters.items(),key=lambda item:item[1]['shift'].get('starts_at','')):
        shift=roster['shift'];assigned={x['volunteer_id']:x for x in assignments[shift_id]}
        for person in roster['people']:
            volunteer=person['volunteer_id'];assignment=assigned[volunteer]
            event=db.execute('SELECT a.*,e.event_time FROM attendance_event a JOIN evidence e USING(event_id) WHERE a.shift_id=? AND a.volunteer_id=? AND e.event_time<=? ORDER BY e.event_time DESC,a.event_id DESC LIMIT 1',(shift_id,volunteer,as_of)).fetchone()
            approval=db.execute('SELECT h.*,e.event_time FROM hours_claim h JOIN evidence e USING(event_id) WHERE h.shift_id=? AND h.volunteer_id=? AND e.event_time<=? ORDER BY e.event_time DESC,h.event_id DESC LIMIT 1',(shift_id,volunteer,as_of)).fetchone()
            if person['reason']=='organization_capacity' or person['reason']=='organizer_cancelled':absence='organizer_reduced'
            elif assignment['reason']=='credential_revoked':absence='qualification_withdrawn'
            elif not event:absence='volunteer_no_show'
            else:absence='none'
            db.execute('INSERT INTO absence_case VALUES (?,?,?,?)',(shift_id,volunteer,absence,person['reason']))
            if assignment['decision']!='assigned':decision='frozen';reason='not_assigned';credit=0
            elif not event:decision='pending';reason='no_attendance';credit=0
            elif event['site']!=shift['site']:decision='rejected';reason='wrong_site';credit=0
            elif not approval or approval['decision']!='approve':decision='pending';reason='no_supervisor_review';credit=0
            elif approval['supervisor']==volunteer:decision='rejected';reason='self_review';credit=0
            else:
                start=max(event['arrived_at'],shift['starts_at']);end=min(event['left_at'],shift['ends_at'])
                if start>=end:decision='rejected';reason='outside_shift';credit=0
                else:
                    credit=uncovered_minutes(start,end,covered.get(volunteer,[]))
                    covered.setdefault(volunteer,[]).append((start,end))
                    decision='credited' if credit else 'rejected';reason='shift_intersection_without_overlap' if credit else 'duplicate_time'
            db.execute('INSERT INTO hours_ledger VALUES (?,?,?,?,?)',(shift_id,volunteer,credit,decision,reason))
            out.append({'shift_id':shift_id,'volunteer_id':volunteer,'minutes':credit,'decision':decision,'reason':reason,'absence':absence})
    return out
