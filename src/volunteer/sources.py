import json,hashlib

def record(db,e,kind,obj):
    body=json.dumps(e,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(body.encode()).hexdigest()
    old=db.execute('SELECT sha256 FROM evidence WHERE event_id=?',(e['event_id'],)).fetchone()
    if old:
        if old['sha256']!=digest:raise ValueError('conflicting event id '+e['event_id'])
        return False
    db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?)',(e['event_id'],kind,obj,e['event_time'],digest,body));return True
