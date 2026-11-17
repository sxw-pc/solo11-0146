"""Recruitment revisions, deadlines and capacity-based roster."""
from .sources import record
from .store import rows


def ingest(db,events):
    made=0
    with db:
        for e in events:
            if e['op']=='call':
                if e['slots']<0 or e['starts_at']>=e['ends_at']:raise ValueError('invalid shift capacity/window')
                if record(db,e,'call',e['shift_id']):
                    db.execute('INSERT INTO call_revision VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (e['event_id'],e['shift_id'],e['version'],e['starts_at'],e['ends_at'],e['deadline'],e['slots'],e['skill'],e['site'],e['status']));made+=1
            elif e['op']=='signup':
                if record(db,e,'signup',e['shift_id']):
                    db.execute('INSERT INTO shift_signup VALUES (?,?,?,?)',(e['event_id'],e['shift_id'],e['volunteer_id'],e['promised_at']));made+=1
            else:raise ValueError('unknown call op '+e['op'])
        for r in rows(db,'SELECT DISTINCT shift_id FROM call_revision'):
            roster(db,r['shift_id'],max(e['event_time'] for e in events))
    return {'imported':made,'roster':rows(db,'SELECT * FROM roster_decision')}


def current(db,shift_id,as_of):
    records=rows(db,'SELECT c.*,e.event_time FROM call_revision c JOIN evidence e USING(event_id) WHERE c.shift_id=? AND e.event_time<=? ORDER BY c.version DESC,e.event_time DESC,c.event_id DESC',(shift_id,as_of))
    if not records:return {'shift_id':shift_id,'status':'missing','reason':'no_call'}
    top=[x for x in records if x['version']==records[0]['version']]
    fields=('slots','skill','site','starts_at','ends_at','status')
    if len({tuple(x[k] for k in fields) for x in top})>1:return {'shift_id':shift_id,'status':'disputed','reason':'same_version_conflict'}
    return records[0]


def roster(db,shift_id,as_of):
    shift=current(db,shift_id,as_of)
    if shift['status'] in ('missing','disputed'):return {'shift':shift,'people':[]}
    db.execute('INSERT INTO shift_slot VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(shift_id) DO UPDATE SET version=excluded.version,slots=excluded.slots,skill=excluded.skill,site=excluded.site,starts_at=excluded.starts_at,ends_at=excluded.ends_at,status=excluded.status',
               (shift_id,shift['version'],shift['slots'],shift['skill'],shift['site'],shift['starts_at'],shift['ends_at'],shift['status']))
    signups=rows(db,'SELECT s.*,e.event_time FROM shift_signup s JOIN evidence e USING(event_id) WHERE s.shift_id=? AND e.event_time<=? ORDER BY s.promised_at,s.event_id',(shift_id,as_of))
    seen=set();out=[];accepted=0
    for s in signups:
        if s['volunteer_id'] in seen:continue
        seen.add(s['volunteer_id'])
        if shift['status']!='open':decision='cancelled';reason='organizer_cancelled'
        elif s['promised_at']>shift['deadline']:decision='waitlist';reason='after_deadline'
        elif accepted>=shift['slots']:decision='waitlist';reason='organization_capacity'
        else:decision='accepted';reason='within_capacity';accepted+=1
        db.execute('INSERT INTO roster_decision VALUES (?,?,?,?) ON CONFLICT(shift_id,volunteer_id) DO UPDATE SET decision=excluded.decision,reason=excluded.reason',
                   (shift_id,s['volunteer_id'],decision,reason))
        out.append({'volunteer_id':s['volunteer_id'],'decision':decision,'reason':reason})
    return {'shift':shift,'people':out}
