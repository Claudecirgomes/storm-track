"""Read processed weather snapshots from the private PostgreSQL weather schema.

The Vercel frontend never connects to localhost or downloads raw Full Disk files.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import io
import json
import math
import re

from backend.app.core.config import get_settings

UTC=timezone.utc


def parse(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def stamp(value):
    return value.isoformat().replace('+00:00','Z')


@contextmanager
def connection(dsn=None):
    import psycopg
    from psycopg.rows import dict_row
    target=dsn or get_settings().database_url
    if not target:
        raise RuntimeError('Cloud weather database is not configured')
    with psycopg.connect(target,autocommit=True,connect_timeout=10,prepare_threshold=None,row_factory=dict_row) as db:
        db.execute('SET search_path TO stormtrack_weather, pg_catalog')
        yield db


def catalog():
    from backend.app.adapters.regional_satellite import STOPS,COLORS
    now=datetime.now(UTC)
    with connection() as db:
        frames=[json.loads(row['metadata']) for row in db.execute("SELECT metadata FROM objects WHERE kind='abi' ORDER BY observed,processed")]
        statuses=list(db.execute('SELECT * FROM status'))
        for kind in ('abi','glm','wind','rain'):
            status=next((s for s in statuses if s['product']==kind),None)
            if status is None:
                status={'product':kind,'checked':None,'error':None};statuses.append(status)
            latest=db.execute('SELECT max("end") AS latest FROM objects WHERE kind=%s',(kind,)).fetchone()['latest']
            age=max(0,int((now-parse(latest)).total_seconds())) if latest else None
            limit=900 if kind=='glm' else 7200 if kind=='wind' else 1800
            status.update(latest_observed_end=latest,age_seconds=age,state='unavailable' if latest is None else 'delayed' if age>limit or status['error'] else 'updated')
            counts=db.execute("SELECT count(*) AS pending,count(*) FILTER(WHERE error IS NOT NULL) AS retrying,min(observed) AS oldest_pending FROM satellite_queue WHERE kind=%s AND state='pending'",(kind,)).fetchone()
            status['queue']=dict(counts)
            product={'abi':'ABI-L2-CMIPF','glm':'GLM-L2-LCFA','wind':'ABI-L2-DMWF','rain':'ABI-L2-RRQPEF'}[kind]
            discovery=db.execute('SELECT checked,recovery_gap FROM satellite_discovery WHERE product=%s',(product,)).fetchone()
            status['discovered_at']=discovery['checked'] if discovery else None
            status['recovery_gap']=discovery['recovery_gap'] if discovery else None
    for frame in frames:
        age=max(0,int((now-parse(frame['end'])).total_seconds()))
        frame.update(age_seconds=age,stale_seconds=1800,state='updated' if age<=1800 else 'delayed')
    bounds=frames[-1]['bounds'] if frames else [-73,-40,-42,-14]
    return {'enabled':True,'frames':frames,'products':statuses,'bounds':bounds,
            'palette':{'values':STOPS,'colors':COLORS},'attribution':'NOAA GOES-19 · coleta online GitHub Actions',
            'collection_mode':'scheduled_cloud','schedule_minutes':5,
            'supported_layers':['reference','c13','combined','rgb','tops','gray','tops-overlay','l2-rrqpef']}


def flashes(end,minutes=10):
    if minutes not in (1,5,10,15):raise ValueError('Invalid GLM window')
    finish=parse(end)
    if finish.tzinfo is None:raise ValueError('Timezone required')
    begin=finish-timedelta(minutes=minutes)
    with connection() as db:
        rows=list(db.execute('SELECT * FROM flashes WHERE observed::timestamptz >= %s AND observed::timestamptz <= %s',(begin,finish)))
        intervals=list(db.execute("SELECT observed,\"end\" FROM objects WHERE kind='glm' AND \"end\"::timestamptz >= %s AND observed::timestamptz <= %s ORDER BY observed",(begin,finish)))
    cursor=begin;covered=0
    for row in intervals:
        start=max(begin,parse(row['observed']));stop=min(finish,parse(row['end']))
        covered+=max(0,(stop-max(cursor,start)).total_seconds());cursor=max(cursor,stop)
    fraction=min(1,covered/(minutes*60))
    return {'type':'FeatureCollection','features':[{'type':'Feature','id':r['id'],'geometry':{'type':'Point','coordinates':[r['lon'],r['lat']]},'properties':{'observed_at':r['observed']}} for r in rows],
            'start':stamp(begin),'end':stamp(finish),'count':len(rows),'coverage_fraction':fraction,
            'state':'unavailable' if not intervals else 'complete' if fraction>=.98 else 'partial',
            'rate_flashes_per_minute':len(rows)/minutes if fraction>=.98 else None,
            'bounds':[-73,-40,-42,-14]}


def asset(name):
    if not re.fullmatch(r'[a-f0-9]{24}(?:-[a-z0-9-]+)?\.(png|npz|json)',name):
        raise ValueError('Invalid asset name')
    with connection() as db:
        row=db.execute('SELECT payload FROM assets WHERE name=%s',(name,)).fetchone()
    if row is None:raise FileNotFoundError('Scene outside online retention')
    return bytes(row['payload'])


def scene(scene_id):
    if not re.fullmatch('[a-f0-9]{24}',scene_id):raise ValueError('Invalid scene')
    with connection() as db:
        rows=db.execute("SELECT metadata FROM objects WHERE kind='abi' AND metadata LIKE %s",('%'+scene_id+'%',))
        for row in rows:
            meta=json.loads(row['metadata'])
            if meta['id']==scene_id:return meta
    raise ValueError('Scene outside online retention')


def layer(scene_id,name):
    meta=scene(scene_id)
    if name=='l2-rrqpef':
        with connection() as db:
            row=db.execute("SELECT metadata FROM objects WHERE kind='rain' AND \"end\"::timestamptz<=%s ORDER BY \"end\" DESC LIMIT 1",(parse(meta['end']),)).fetchone()
        if not row:raise ValueError('Chuva estimada indisponível na fonte para este horário.')
        rain=json.loads(row['metadata'])
        return {'image':rain['images']['rain'],'unit':rain['units'],'scene':scene_id,'layer':name,
                'start':rain['start'],'end':rain['end'],'bounds':rain['bounds'],'status':'available' if rain['valid_fraction'] else 'not_applicable_or_no_valid_pixels',
                'range':rain['display_range'],'palette':None}
    if name not in ('reference','tops','gray','tops-overlay'):
        raise ValueError('Diagnóstico não incluído na coleta online básica; use os produtos já processados.')
    if name=='reference':
        from backend.app.adapters.regional_satellite import STOPS,COLORS
        return {'image':meta['images']['reference'],'unit':'°C','scene':scene_id,'layer':name,
                'start':meta['start'],'end':meta['end'],'bounds':meta['bounds'],'status':'available',
                'range':[-90,40],'palette':{'values':STOPS,'colors':COLORS}}
    from backend.app.adapters import goes_layers as layers
    # Return a fixed authenticated render URL; no temporary serverless filesystem.
    return {'image':f'{scene_id}-{name}.png','unit':'°C','scene':scene_id,'layer':name,
            'start':meta['start'],'end':meta['end'],'bounds':meta['bounds'],'status':'available',
            'range':[40,-100] if name=='gray' else [-100,40],
            'palette':None if name=='gray' else {'values':layers.TOP_STOPS,'colors':layers.TOP_COLORS}}


def rendered_asset(name):
    if not re.fullmatch(r'[a-f0-9]{24}-[a-z0-9-]+\.png',name):raise ValueError('Invalid image')
    try:return asset(name)
    except FileNotFoundError:
        match=re.fullmatch(r'([a-f0-9]{24})-(tops|gray|tops-overlay)\.png',name)
        if not match:raise
        import numpy as np
        from PIL import Image
        from backend.app.adapters.goes_layers import grayscale,tops
        scene_id,mode=match.groups();scene(scene_id)
        with np.load(io.BytesIO(asset(scene_id+'.npz')),allow_pickle=False) as saved:values=saved['c13_celsius']
        rgba=grayscale(values,40,-100) if mode=='gray' else tops(values,mode=='tops-overlay')
        output=io.BytesIO();Image.fromarray(rgba).save(output,format='PNG');return output.getvalue()


def sample(scene_id,name,lon,lat):
    if name not in ('reference','tops','gray','tops-overlay'):raise ValueError('Layer not available online')
    meta=scene(scene_id);west,south,east,north=meta['bounds']
    if not west<=lon<=east or not south<=lat<=north:raise ValueError('Point outside coverage')
    import numpy as np
    def mercator(latitude):return math.asinh(math.tan(math.radians(latitude)))
    with np.load(io.BytesIO(asset(scene_id+'.npz')),allow_pickle=False) as saved:values=saved['c13_celsius']
    h,w=values.shape;col=min(w-1,int((lon-west)/(east-west)*w));row=min(h-1,int((mercator(north)-mercator(lat))/(mercator(north)-mercator(south))*h))
    value=float(values[row,col])
    return {'value':value if math.isfinite(value) else None,'unit':'°C','quality':'CMIP DQF=0' if math.isfinite(value) else 'no-data',
            'source':'NOAA GOES-19 ABI','start':meta['start'],'end':meta['end'],'scene':scene_id,'layer':name}


def winds(end):
    finish=parse(end)
    if finish.tzinfo is None:raise ValueError('Timezone required')
    with connection() as db:
        row=db.execute("SELECT metadata FROM objects WHERE kind='wind' AND \"end\"::timestamptz<=%s ORDER BY \"end\" DESC,processed DESC LIMIT 1",(finish,)).fetchone()
    if not row:return {'type':'FeatureCollection','features':[],'state':'unavailable'}
    meta=json.loads(row['metadata']);data=json.loads(asset(meta['file']))
    data['features']=[f for f in data['features'] if parse(f['properties']['observed'])<=finish]
    return data
