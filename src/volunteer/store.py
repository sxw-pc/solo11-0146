import sqlite3
from pathlib import Path

SCHEMA="""
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS evidence(event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,object_id TEXT NOT NULL,event_time TEXT NOT NULL,sha256 TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS call_revision(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),shift_id TEXT NOT NULL,version INTEGER NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,deadline TEXT NOT NULL,slots INTEGER NOT NULL,skill TEXT NOT NULL,site TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shift_signup(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,promised_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shift_slot(shift_id TEXT PRIMARY KEY,version INTEGER NOT NULL,slots INTEGER NOT NULL,skill TEXT NOT NULL,site TEXT NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS roster_decision(shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(shift_id,volunteer_id));
CREATE TABLE IF NOT EXISTS credential_evidence(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),volunteer_id TEXT NOT NULL,skill TEXT NOT NULL,issuer TEXT NOT NULL,valid_from TEXT NOT NULL,valid_until TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eligibility_case(shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(shift_id,volunteer_id));
CREATE TABLE IF NOT EXISTS assignment(shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,call_version INTEGER NOT NULL,decision TEXT NOT NULL,PRIMARY KEY(shift_id,volunteer_id));
CREATE TABLE IF NOT EXISTS attendance_event(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,site TEXT NOT NULL,arrived_at TEXT NOT NULL,left_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hours_claim(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,supervisor TEXT NOT NULL,decision TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hours_ledger(shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,minutes INTEGER NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(shift_id,volunteer_id));
CREATE TABLE IF NOT EXISTS absence_case(shift_id TEXT NOT NULL,volunteer_id TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(shift_id,volunteer_id));
CREATE TABLE IF NOT EXISTS report_history(id INTEGER PRIMARY KEY AUTOINCREMENT,as_of TEXT NOT NULL,body TEXT NOT NULL);
"""

def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.executescript(SCHEMA);return db

def rows(db,sql,args=()):return [dict(r) for r in db.execute(sql,args).fetchall()]
