"""Durable NOAA discovery receipts and fair, retryable acquisition queues."""
from datetime import timedelta
import os


def schema(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='satellite_discovery'").fetchone():
        if 'started' in {row[1] for row in db.execute('PRAGMA table_info(satellite_discovery)')}:
            return
    db.executescript('''
    CREATE TABLE IF NOT EXISTS satellite_queue (
      key TEXT PRIMARY KEY, product TEXT NOT NULL, kind TEXT NOT NULL,
      size INTEGER NOT NULL, observed TEXT NOT NULL, discovered TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
      retry_at TEXT, error TEXT, completed TEXT, source_sha256 TEXT);
    CREATE INDEX IF NOT EXISTS satellite_queue_ready ON satellite_queue(kind,state,retry_at);
    CREATE TABLE IF NOT EXISTS satellite_discovery (
      product TEXT PRIMARY KEY, checked TEXT NOT NULL, recovery_gap TEXT, started TEXT);
    ''')
    if 'started' not in {row[1] for row in db.execute('PRAGMA table_info(satellite_discovery)')}:
        db.execute('ALTER TABLE satellite_discovery ADD COLUMN started TEXT')


def discover(db, product, kind, instant, listing, parse, stamp, channel=None, completed_lookup=None):
    schema(db)
    previous=db.execute('SELECT checked,recovery_gap,started FROM satellite_discovery WHERE product=?',(product,)).fetchone()
    recovery_hours=max(1,min(168,int(os.getenv('STORMTRACK_RECOVERY_HOURS','24'))))
    earliest=instant-timedelta(hours=recovery_hours)
    overlap={'abi':30,'glm':15,'wind':120,'rain':60}.get(kind,15)
    start=parse(previous[0])-timedelta(minutes=overlap) if previous else instant-timedelta(minutes=overlap)
    started=previous[2] if previous and previous[2] else stamp(start)
    gap=previous[1] if previous else None
    if start<earliest:
        if previous and parse(previous[0])<earliest:
            gap=f'Recovery bounded: source interval {previous[0]} to {stamp(earliest)} requires explicit historical import'
        start=max(earliest,parse(started))
    # A rolling overlap catches delayed objects and new creation-key revisions.
    # An hourly full recovery-window sweep also finds unusually late publication.
    if previous and parse(previous[0]).hour!=instant.hour:
        start=max(earliest,parse(started))
    minutes=max(1,int((instant-start).total_seconds()/60)+1)
    objects=listing(product,instant,minutes=minutes,channel=channel)
    already_done=completed_lookup([item[0] for item in objects]) if completed_lookup else set()
    for key,size,observed in objects:
        done=key in already_done or db.execute('SELECT 1 FROM objects WHERE key=?',(key,)).fetchone() is not None
        db.execute('INSERT OR IGNORE INTO satellite_queue(key,product,kind,size,observed,discovered,state) VALUES (?,?,?,?,?,?,?)',
                   (key,product,kind,size,observed,stamp(instant),'done' if done else 'pending'))
    # Checkpoint advances only AFTER the entire paginated listing was queued.
    db.execute('INSERT OR REPLACE INTO satellite_discovery(product,checked,recovery_gap,started) VALUES (?,?,?,?)',(product,stamp(instant),gap,started))
    db.commit()


def batch(db,kind,instant,stamp,limit):
    schema(db)
    ready=db.execute("SELECT key,size,observed FROM satellite_queue WHERE kind=? AND state='pending' AND (retry_at IS NULL OR julianday(retry_at)<=julianday(?)) ORDER BY observed,key",(kind,stamp(instant))).fetchall()
    if not ready:
        return []
    # Latest first for the live view, then oldest first: gaps cannot starve.
    newest=max(ready,key=lambda row:(row[2],row[0]))
    selected=[newest,*[row for row in ready if row[0]!=newest[0]][:max(0,limit-1)]]
    return [tuple(row) for row in selected]


def completed(db,item,instant,stamp,digest=None):
    db.execute("UPDATE satellite_queue SET state='done',completed=?,retry_at=NULL,error=NULL,source_sha256=COALESCE(?,source_sha256) WHERE key=?",(stamp(instant),digest,item[0]))
    db.commit()


def failed(db,item,instant,stamp,error):
    row=db.execute('SELECT attempts FROM satellite_queue WHERE key=?',(item[0],)).fetchone()
    attempts=(row[0] if row else 0)+1
    delay=min(300,10*2**min(attempts-1,5))
    db.execute("UPDATE satellite_queue SET attempts=?,retry_at=?,error=? WHERE key=?",(attempts,stamp(instant+timedelta(seconds=delay)),str(error),item[0]))
    db.commit()


def status(db,kind):
    schema(db)
    row=db.execute("SELECT count(*),sum(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END),min(observed) FROM satellite_queue WHERE kind=? AND state='pending'",(kind,)).fetchone()
    return {'pending':row[0],'retrying':row[1] or 0,'oldest_pending':row[2]}
