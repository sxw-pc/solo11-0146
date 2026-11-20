"""Recompute roster, skill assignments, service-hour liability and beneficiary evaluation."""
import json
from . import call,credential,attendance,beneficiary
from .store import rows


def decide(db,as_of):
    with db:
        shifts=[r['shift_id'] for r in rows(db,'SELECT DISTINCT shift_id FROM call_revision')]
        rosters={sid:call.roster(db,sid,as_of) for sid in shifts}
        assignments={sid:credential.assign(db,rosters[sid],as_of) for sid in shifts}
        hours=attendance.settle(db,rosters,assignments,as_of)
        evaluation=beneficiary.evaluate(db,as_of,hours=hours)
        prev=db.execute('SELECT id,body FROM report_history ORDER BY id DESC LIMIT 1').fetchone()
        prev_eval=None;prev_id=None
        if prev:
            prev_id=prev['id']
            try:prev_eval=json.loads(prev['body']).get('evaluation')
            except ValueError:prev_eval=None
        beneficiary.attach_previous(evaluation,prev_eval,prev_id)
        result={'as_of':as_of,'rosters':rosters,'assignments':assignments,'hours':hours,'evaluation':evaluation}
        cur=db.execute('INSERT INTO report_history(as_of,body) VALUES (?,?)',(as_of,json.dumps(result,sort_keys=True)))
        result['report_id']=cur.lastrowid
        return result
