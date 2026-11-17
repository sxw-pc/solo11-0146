"""Recompute roster, skill assignments and service-hour liability."""
import json
from . import call,credential,attendance
from .store import rows


def decide(db,as_of):
    with db:
        shifts=[r['shift_id'] for r in rows(db,'SELECT DISTINCT shift_id FROM call_revision')]
        rosters={sid:call.roster(db,sid,as_of) for sid in shifts}
        assignments={sid:credential.assign(db,rosters[sid],as_of) for sid in shifts}
        hours=attendance.settle(db,rosters,assignments,as_of)
        result={'as_of':as_of,'rosters':rosters,'assignments':assignments,'hours':hours}
        db.execute('INSERT INTO report_history(as_of,body) VALUES (?,?)',(as_of,json.dumps(result,sort_keys=True)))
        return result
