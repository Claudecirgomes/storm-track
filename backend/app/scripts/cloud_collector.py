"""One bounded GitHub Actions acquisition batch, persisted in PostgreSQL.

Uses only the restricted stormtrack_weather machine identity. Raw NOAA files
remain transient; no account tables or curated scientific archives are copied.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from backend.app.adapters import regional_satellite as regional
from backend.app.adapters.cloud_weather import connection
from backend.app.ingestion import satellite_queue

TABLES={
 'objects':('key','observed','end','processed','kind','metadata'),
 'flashes':('id','observed','lon','lat'),
 'status':('product','checked','error'),
 'satellite_queue':('key','product','kind','size','observed','discovered','state','attempts','retry_at','error','completed','source_sha256'),
 'satellite_discovery':('product','checked','recovery_gap','started')}


def upsert(remote,table,columns,rows):
    from psycopg import sql
    if not rows:return
    names=sql.SQL(',').join(map(sql.Identifier,columns))
    values=sql.SQL(',').join(sql.Placeholder() for _ in columns)
    update=sql.SQL(',').join(sql.SQL('{}=excluded.{}').format(sql.Identifier(col),sql.Identifier(col)) for col in columns[1:])
    query=sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}').format(sql.Identifier(table),names,values,sql.Identifier(columns[0]),update)
    with remote.cursor() as cursor:cursor.executemany(query,rows)


def hydrate(remote):
    with regional.database() as local:
        satellite_queue.schema(local)
        for table in ('objects','status','satellite_discovery','satellite_queue'):
            where=" WHERE state='pending'" if table=='satellite_queue' else ''
            rows=list(remote.execute('SELECT * FROM '+table+where))
            columns=TABLES[table]
            quoted=','.join('"'+col+'"' for col in columns)
            local.executemany(f'INSERT OR REPLACE INTO {table} ({quoted}) VALUES ({",".join("?" for _ in columns)})',[tuple(row[col] for col in columns) for row in rows])
        local.commit()


def publish(remote,started):
    now=regional.now();cutoff=regional.stamp(now-timedelta(minutes=120))
    with regional.database() as local:
        objects=[dict(row) for row in local.execute('SELECT * FROM objects WHERE processed>=?',(started,))]
        with remote.transaction():
            size=remote.execute('SELECT pg_database_size(current_database()) AS bytes').fetchone()['bytes']
            if size>400*1024**2:raise RuntimeError('Cloud database reserve reached; acquisition publication paused')
            for obj in objects:
                meta=json.loads(obj['metadata']);scene=meta.get('id')
                if not scene:continue
                files=list(meta.get('images',{}).values())
                if meta.get('file'):files.append(meta['file'])
                if obj['kind']=='abi':files.append(scene+'.npz')
                for name in set(files):
                    path=regional.root()/name
                    if not path.is_file():raise RuntimeError('Incomplete scene artifact: '+name)
                    content=path.read_bytes()
                    if len(content)>16*1024**2:raise RuntimeError('Processed asset exceeds cloud limit')
                    digest=hashlib.sha256(content).hexdigest()
                    remote.execute('INSERT INTO assets VALUES (%s,%s,%s,%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,sha256=excluded.sha256,created=excluded.created WHERE assets.sha256<>excluded.sha256',(name,scene,content,digest,regional.stamp(now)))
            upsert(remote,'objects',TABLES['objects'],[tuple(obj[col] for col in TABLES['objects']) for obj in objects])
            flashes=local.execute('SELECT * FROM flashes').fetchall()
            if flashes:
                remote.execute('CREATE TEMP TABLE incoming_flashes(LIKE flashes INCLUDING DEFAULTS) ON COMMIT DROP')
                with remote.cursor().copy('COPY incoming_flashes(id,observed,lon,lat) FROM STDIN') as copy:
                    for row in flashes:copy.write_row(tuple(row[col] for col in TABLES['flashes']))
                remote.execute('INSERT INTO flashes SELECT * FROM incoming_flashes ON CONFLICT(id) DO NOTHING')
            for table in ('status','satellite_discovery','satellite_queue'):
                columns=TABLES[table]
                rows=local.execute('SELECT * FROM '+table).fetchall()
                if table=='satellite_queue':rows=[row for row in rows if row['state']=='pending' or (row['completed'] and row['completed']>=started)]
                upsert(remote,table,columns,[tuple(row[col] for col in columns) for row in rows])
            remote.execute('DELETE FROM flashes WHERE observed::timestamptz<%s::timestamptz',(cutoff,))
            remote.execute('DELETE FROM assets WHERE scene_id IN (SELECT metadata::jsonb->>\'id\' FROM objects WHERE "end"::timestamptz<%s::timestamptz)',(cutoff,))
            remote.execute('DELETE FROM objects WHERE "end"::timestamptz<%s::timestamptz',(cutoff,))
            remote.execute("DELETE FROM satellite_queue WHERE state='done' AND completed::timestamptz < %s",(now-timedelta(days=7),))
            # Disposable online cache only. Never touches accounts or local datasets.
            assets=list(remote.execute('SELECT scene_id,sum(octet_length(payload)) AS bytes,min(created) AS created FROM assets GROUP BY scene_id ORDER BY min(created)'))
            total=sum(row['bytes'] for row in assets)
            for row in assets:
                if total<=96*1024**2:break
                remote.execute('DELETE FROM assets WHERE scene_id=%s',(row['scene_id'],))
                remote.execute("DELETE FROM objects WHERE metadata::jsonb->>'id'=%s",(row['scene_id'],))
                total-=row['bytes']
    return {'objects':len(objects),'flashes':len(flashes),'asset_bytes':total,'published':regional.stamp(now)}


def main():
    dsn=os.environ.get('STORMTRACK_CLOUD_DATABASE_URL')
    if not dsn:raise SystemExit('STORMTRACK_CLOUD_DATABASE_URL is required')
    with connection(dsn) as remote:
        acquired=remote.execute('SELECT pg_try_advisory_lock(5461321) AS acquired').fetchone()['acquired']
        if not acquired:
            print('Another cloud acquisition batch is active');return
        try:
            with tempfile.TemporaryDirectory(prefix='stormtrack-cloud-') as directory:
                os.environ['STORMTRACK_DATA_DIR']=directory
                os.environ['STORMTRACK_SATELLITE_PROFILE']='basic'
                os.environ['STORMTRACK_SATELLITE_COLLECT_RGB']='false'
                os.environ.pop('VERCEL',None)
                hydrate(remote)
                def known(keys):
                    if not keys:return set()
                    return {row['key'] for row in remote.execute("SELECT key FROM satellite_queue WHERE state='done' AND key=ANY(%s)",(keys,))}
                regional.RECEIPT_LOOKUP=known
                started=regional.stamp(regional.now())
                regional.collect_once()
                print(json.dumps(publish(remote,started)))
        finally:
            remote.execute('SELECT pg_advisory_unlock(5461321)')


if __name__=='__main__':main()
