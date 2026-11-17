"""Credential source, expiry, revocation and task assignment."""
from .sources import record
from .store import rows

TRUSTED_ISSUERS={'synthetic-rescue-school','synthetic-community-center'}


def ingest(db,events):
    made=0
    with db:
        for e in events:
            if e['op']!='credential':raise ValueError('credential input required')
            if record(db,e,'credential',e['volunteer_id']):
                db.execute('INSERT INTO credential_evidence VALUES (?,?,?,?,?,?,?)',
                           (e['event_id'],e['volunteer_id'],e['skill'],e['issuer'],e['valid_from'],e['valid_until'],e['status']));made+=1
    return {'imported':made,'credentials':len(rows(db,'SELECT DISTINCT volunteer_id FROM credential_evidence'))}


def eligible(db,shift,volunteer_id,as_of):
    if shift['skill']=='general':return {'decision':'eligible','reason':'general_role'}
    records=rows(db,'SELECT c.*,e.event_time FROM credential_evidence c JOIN evidence e USING(event_id) WHERE c.volunteer_id=? AND c.skill=? AND e.event_time<=? ORDER BY e.event_time DESC,c.event_id DESC',
                 (volunteer_id,shift['skill'],as_of))
    if not records:return {'decision':'ineligible','reason':'skill_missing'}
    c=records[0]
    if c['issuer'] not in TRUSTED_ISSUERS:return {'decision':'ineligible','reason':'issuer_untrusted'}
    if c['status']!='valid':return {'decision':'ineligible','reason':'credential_revoked'}
    if not(c['valid_from']<=shift['starts_at']<=c['valid_until']):return {'decision':'ineligible','reason':'credential_expired'}
    return {'decision':'eligible','reason':'current_skill'}


def assign(db,roster,as_of):
    shift=roster['shift'];out=[]
    if shift['status'] in ('missing','disputed'):return out
    for person in roster['people']:
        skill=eligible(db,shift,person['volunteer_id'],as_of)
        decision='assigned' if person['decision']=='accepted' and skill['decision']=='eligible' else 'unassigned'
        reason=person['reason'] if person['decision']!='accepted' else skill['reason']
        db.execute('INSERT INTO eligibility_case VALUES (?,?,?,?) ON CONFLICT(shift_id,volunteer_id) DO UPDATE SET decision=excluded.decision,reason=excluded.reason',
                   (shift['shift_id'],person['volunteer_id'],skill['decision'],skill['reason']))
        db.execute('INSERT INTO assignment VALUES (?,?,?,?) ON CONFLICT(shift_id,volunteer_id) DO UPDATE SET call_version=excluded.call_version,decision=excluded.decision',
                   (shift['shift_id'],person['volunteer_id'],shift['version'],decision))
        out.append({'volunteer_id':person['volunteer_id'],'decision':decision,'reason':reason})
    return out
