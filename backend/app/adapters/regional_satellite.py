"""Local NOAA ABI/GLM worker. No writes to the StormTrack operational database."""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import shutil
import argparse
import hashlib
import json
import logging
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from threading import RLock
from functools import wraps

import numpy as np
from netCDF4 import Dataset, num2date
from PIL import Image
from pyproj import CRS, Transformer

from backend.app.core.config import get_settings
from backend.app.adapters.noaa_goes19_glm import _request_bytes, _time_from_key

UTC = timezone.utc
HOST = 'https://noaa-goes19.s3.amazonaws.com/'
LOG = logging.getLogger(__name__)
SCIENCE_LOCK=RLock()
RECEIPT_LOOKUP=None


def scientific(function):
    @wraps(function)
    def guarded(*args,**kwargs):
        with SCIENCE_LOCK:
            return function(*args,**kwargs)
    return guarded
STOPS = [-90, -80, -75, -70, -65, -60, -55, -50, -40, -30, 0, 40]
# Visual approximation, not the official SIMEPAR palette. Keep the temperature
# range while concentrating color bands on colder tops and retaining grey edges.
COLORS = [[10,8,14], [24,12,30], [80,20,100], [205,55,185], [235,42,55], [255,145,35], [250,235,65], [65,190,95], [70,200,225], [210,218,220], [100,100,100], [10,10,15]]


class _SkipVisible(Exception):
    """Internal control flow for the explicitly identified economical IR base."""

def now():
    return datetime.now(UTC)

def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')

def parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def root():
    return get_settings().data_dir / 'regional-satellite'

@contextmanager
def database():
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'catalog.sqlite3', timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE IF NOT EXISTS objects (key TEXT PRIMARY KEY, observed TEXT, end TEXT, processed TEXT, kind TEXT, metadata TEXT);
    CREATE TABLE IF NOT EXISTS flashes (id TEXT PRIMARY KEY, observed TEXT, lon REAL, lat REAL);
    CREATE INDEX IF NOT EXISTS flash_time ON flashes(observed);
    CREATE TABLE IF NOT EXISTS status (product TEXT PRIMARY KEY, checked TEXT, error TEXT);
    ''')
    try:
        with db:
            yield db
    finally:
        db.close()

def bounds():
    result = tuple(float(x) for x in os.getenv('STORMTRACK_SATELLITE_BOUNDS', '-73,-40,-42,-14').split(','))
    if len(result) != 4 or not (-180 <= result[0] < result[2] <= 180 and -80 <= result[1] < result[3] <= 80):
        raise ValueError('Invalid satellite bounds: west,south,east,north')
    return result

def history_minutes():
    return max(10,min(120,int(os.getenv('STORMTRACK_SATELLITE_HISTORY_MINUTES','120'))))

def listing(product, instant, minutes=120, channel=None):
    """Paginated hourly listing, including UTC day/year transitions."""
    cutoff = instant - timedelta(minutes=minutes)
    hour = cutoff.replace(minute=0, second=0, microsecond=0)
    found = []
    while hour <= instant:
        prefix = f'{product}/{hour:%Y}/{hour:%j}/{hour:%H}/'
        token = None
        for _ in range(30):
            args = {'list-type':'2', 'prefix':prefix, 'max-keys':1000}
            if token:
                args['continuation-token'] = token
            doc = ET.fromstring(_request_bytes(HOST + '?' + urlencode(args), max_bytes=4_000_000))
            for entry in doc.findall('{*}Contents'):
                key = entry.findtext('{*}Key') or ''
                start = _time_from_key(key)
                if not start or (channel and f'C{channel:02d}_G19_' not in key):
                    continue
                if '_G19_' not in key or not key.endswith('.nc'):
                    continue
                if cutoff <= parse(start) <= instant:
                    found.append((key, int(entry.findtext('{*}Size')), start))
            if doc.findtext('{*}IsTruncated') != 'true':
                break
            token = doc.findtext('{*}NextContinuationToken')
            if not token:
                raise RuntimeError('Missing S3 continuation token')
        else:
            raise RuntimeError('S3 page bound exceeded')
        hour += timedelta(hours=1)
    return sorted(found, key=lambda item:item[2])

def download(item, directory=None):
    key, size, _ = item
    if not 0 < size <= 512*1024*1024:
        raise ValueError('NOAA object size outside limit')
    directory = Path(directory) if directory is not None else root()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (hashlib.sha256(key.encode()).hexdigest() + '.nc')
    if directory.resolve().is_relative_to(root().resolve()) and sum(p.stat().st_size for p in root().rglob('*') if p.is_file()) + size > 512*1024*1024:
        raise RuntimeError('Regional cache reached 512 MiB limit')
    if shutil.disk_usage(directory).free < size+256*1024*1024:
        raise RuntimeError('Minimum disk reserve reached')
    for attempt in range(3):
        try:
            temporary = target.with_suffix('.part')
            # C02 Full Disk can exceed 400 MB; never buffer the whole source in RAM.
            with urlopen(Request(HOST+key,headers={'User-Agent':'StormTrackLocalMVP/1.0'}),timeout=45) as response:
                if not response.geturl().startswith(HOST):
                    raise ValueError('Unexpected NOAA redirect')
                total=0
                with temporary.open('wb') as stream:
                    while chunk:=response.read(1024*1024):
                        total+=len(chunk)
                        if total>size:
                            raise ValueError('NOAA response exceeded listed size')
                        stream.write(chunk)
                if total!=size:
                    raise ValueError('Incomplete NOAA download')
            temporary.replace(target)
            return target
        except Exception:
            target.with_suffix('.part').unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

def grid():
    west, south, east, north = bounds()
    project = Transformer.from_crs(4326, 3857, always_xy=True)
    left, bottom = project.transform(west, south)
    right, top = project.transform(east, north)
    width = 900
    height = min(1800,max(100,round(width * (top-bottom)/(right-left))))
    xx, yy = np.meshgrid(left+(np.arange(width)+.5)*(right-left)/width,
                         top-(np.arange(height)+.5)*(top-bottom)/height)
    return Transformer.from_crs(3857, 4326, always_xy=True).transform(xx, yy)

@scientific
def read_channel(path, variable='CMI', quality_name='DQF', quality_values=(0,), convert_celsius=True, extra_quality=()):
    """Inverse map pixel centers through file geostationary CRS; read ROI only."""
    lon, lat = grid()
    with Dataset(path) as ds:
        p = ds.variables['goes_imager_projection']
        crs = CRS.from_cf({name:p.getncattr(name) for name in p.ncattrs()})
        gx, gy = Transformer.from_crs(4326, crs, always_xy=True).transform(lon, lat)
        x, y = ds.variables['x'][:]*p.perspective_point_height, ds.variables['y'][:]*p.perspective_point_height
        ix = np.rint((gx-x[0])/(x[1]-x[0])).astype(int)
        iy = np.rint((gy-y[0])/(y[1]-y[0])).astype(int)
        valid = (ix>=0)&(ix<len(x))&(iy>=0)&(iy<len(y))
        ix, iy = np.clip(ix,0,len(x)-1), np.clip(iy,0,len(y)-1)
        x0,x1,y0,y1 = ix.min(),ix.max()+1,iy.min(),iy.max()+1
        var = ds.variables[variable]
        if var.dimensions != ('y','x'):
            raise ValueError('Raster adapter requires two-dimensional y,x variable')
        values = np.ma.filled(var[y0:y1,x0:x1].astype(float), np.nan)[iy-y0,ix-x0]
        quality = np.ma.filled(ds.variables[quality_name][y0:y1,x0:x1],255)[iy-y0,ix-x0]
        values[~valid | ~np.isin(quality,quality_values)] = np.nan
        for extra_name,extra_values in extra_quality:
            extra=np.ma.filled(ds.variables[extra_name][y0:y1,x0:x1],255)[iy-y0,ix-x0]
            values[~np.isin(extra,extra_values)]=np.nan
        units = getattr(var,'units',None)
        if convert_celsius and units == 'K':
            values -= 273.15
        elif convert_celsius and units not in ('1', 'unitless'):
            raise ValueError(f'Unexpected CMI units {units}')
        return values, {'start':ds.time_coverage_start, 'end':ds.time_coverage_end, 'units':units,
                        'valid_fraction':float(np.isfinite(values).mean())}

def thermal(values, enhancement=False):
    rgba = np.zeros((*values.shape,4), dtype=np.uint8)
    for c in range(3):
        rgba[:,:,c] = np.interp(np.nan_to_num(values),STOPS,np.array(COLORS)[:,c]).astype('uint8')
    # Fade into the unchanged RGB/IR cloud texture over -30 to -38 C.
    # This is display opacity, not a cloud mask or a change in physical values.
    alpha = np.clip((-30-values)/8,0,1)*255 if enhancement else 255
    rgba[:,:,3] = np.where(np.isfinite(values),np.nan_to_num(alpha),0).astype('uint8')
    return rgba


def reference_clouds(values):
    """Thermal display opacity, not a physical cloud mask or terrain observation."""
    rgba=thermal(values)
    rgba[...,3]=np.where(np.isfinite(values),np.nan_to_num(np.clip((15-values)/30,0,1))*255,0).astype('uint8')
    return rgba

def save_image(frame, product, array):
    name = f'{frame}-{product}.png'
    target = root()/name
    temporary = target.with_suffix('.part')
    Image.fromarray(array).save(temporary, format='PNG')
    temporary.replace(target)
    return name

def _run_source(db, instant, product, kind, method, limit, channel=None):
    from backend.app.ingestion import satellite_queue as queue
    queue.discover(db,product,kind,instant,listing,parse,stamp,channel,completed_lookup=RECEIPT_LOOKUP)
    errors=[]
    for item in queue.batch(db,kind,now(),stamp,limit):
        if db.execute('SELECT 1 FROM objects WHERE key=?',(item[0],)).fetchone():
            queue.completed(db,item,now(),stamp)
            continue
        try:
            method(db,item)
            row=db.execute('SELECT metadata FROM objects WHERE key=?',(item[0],)).fetchone()
            digest=json.loads(row[0]).get('source_sha256') if row else None
            queue.completed(db,item,now(),stamp,digest)
        except Exception as exc:
            db.rollback()
            queue.failed(db,item,now(),stamp,exc)
            errors.append(f'{item[0]}: {exc}')
            LOG.exception('Acquisition queued for retry: %s',item[0])
    if errors:
        raise RuntimeError('; '.join(errors))


def abi(db, instant):
    _run_source(db,instant,'ABI-L2-CMIPF','abi',_abi_item,
                max(1,min(12,int(os.getenv('STORMTRACK_ABI_BATCH_SIZE','3')))),channel=13)


def _abi_item(db,item):
    LOG.info('ABI processing %s', item[0])
    path = download(item)
    try:
        with path.open('rb') as source:
            digest=hashlib.file_digest(source,'sha256').hexdigest()
        values, meta = read_channel(path)
    finally:
        path.unlink(missing_ok=True)
    frame = hashlib.sha256(item[0].encode()).hexdigest()[:24]
    meta.update(id=frame, bounds=bounds(), source=item[0], source_sha256=digest, collected_at=stamp(now()),
                images={'c13':save_image(frame,'c13',thermal(values)),
                        'reference':save_image(frame,'reference',reference_clouds(values)),
                        'enhancement':save_image(frame,'enhancement',thermal(values,True))},
                composite_status='unavailable', composite_label='RGB diurno + IR noturno (não é GeoColor CIRA)')
    numeric = root()/f'{frame}.npz'
    with numeric.with_suffix('.part').open('wb') as stream:
        np.savez_compressed(stream,c13_celsius=values)
    numeric.with_suffix('.part').replace(numeric)
    # Publish the physical C13 immediately. Optional RGB cannot hold up live data.
    db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',(item[0],stamp(parse(meta['start'])),stamp(parse(meta['end'])),stamp(now()),'abi',json.dumps(meta)))
    db.commit()
    # Independent composite: failure cannot prevent publishing the C13 frame.
    try:
        if os.getenv('STORMTRACK_SATELLITE_PROFILE','basic')=='basic' and os.getenv('STORMTRACK_SATELLITE_COLLECT_RGB','false').lower()!='true':
            # Explicit IR fallback keeps the existing combined view usable while
            # avoiding a 400 MB C02 download on every background scan.
            from backend.app.adapters.goes_layers import grayscale
            meta['images']['rgb']=save_image(frame,'rgb',grayscale(values,40,-100))
            meta['composite_status']='ir_only'
            meta['composite_label']='C13 em cinza; RGB diurno disponível sob demanda em True Color'
            raise _SkipVisible()
        channels=[]
        for channel in (1,2,3):
            matches = listing('ABI-L2-CMIPF',parse(item[2])+timedelta(seconds=1),minutes=2,channel=channel)
            match = next((m for m in matches if abs((parse(m[2])-parse(item[2])).total_seconds()) <= 1),None)
            if match is None:
                raise ValueError('Visible channels unavailable at matching scan start')
            file = download(match)
            try:
                channels.append(read_channel(file)[0])
            finally:
                file.unlink(missing_ok=True)
        blue,red,vegetation = [np.clip(c,0,1)**(1/2.2) for c in channels]
        green = .45*red+.1*vegetation+.45*blue
        rgb = np.stack([red,green,blue],axis=-1)
        # Solar zenith approximation for day/night blending; documented locally.
        lon,lat=grid()
        t=parse(meta['start']); day=t.timetuple().tm_yday
        decl=np.deg2rad(23.44*np.sin(2*np.pi*(day-81)/365.25))
        hour=np.deg2rad((t.hour+t.minute/60+lon/15-12)*15)
        cosine=np.sin(np.deg2rad(lat))*np.sin(decl)+np.cos(np.deg2rad(lat))*np.cos(decl)*np.cos(hour)
        blend=np.clip(cosine/.15,0,1)[:,:,None]
        night=np.clip((30-values)/110,0,1)[:,:,None]
        rgba=np.zeros((*values.shape,4),dtype='uint8')
        rgba[:,:,:3]=np.nan_to_num(255*(blend*rgb+(1-blend)*night)).astype('uint8')
        rgba[:,:,3]=np.where(np.isfinite(values)&np.isfinite(rgb).all(axis=-1),255,0)
        meta['images']['rgb']=save_image(frame,'rgb',rgba)
        meta['composite_status']='available'
    except _SkipVisible:
        pass
    except Exception as exc:
        meta['composite_error']=str(exc)
        LOG.exception('RGB failed; preserving C13')
    db.execute('UPDATE objects SET metadata=? WHERE key=?',(json.dumps(meta),item[0]))
    db.commit()
    profile=os.getenv('STORMTRACK_SATELLITE_PROFILE','basic')
    if profile!='basic':
        from backend.app.adapters.goes_layers import PROFILES, dependencies, prepare_layer
        recipes=[v.strip() for v in os.getenv('STORMTRACK_SATELLITE_RECIPES','simple-vapor,split-window').split(',') if v.strip()]
        channels=set(PROFILES[profile])
        for recipe in recipes:
            channels.update(dependencies(recipe))
        for layer in [*(f'abi{c:02d}' for c in sorted(channels)),*recipes]:
            prepare_layer(frame,layer)


def glm(db, instant):
    _run_source(db,instant,'GLM-L2-LCFA','glm',_glm_item,24)


def _glm_item(db,item):
    file=download(item)
    try:
        with file.open('rb') as source:
            digest=hashlib.file_digest(source,'sha256').hexdigest()
        with Dataset(file) as ds:
            lon=ds.variables['flash_lon'][:]; lat=ds.variables['flash_lat'][:]
            ids=ds.variables['flash_id'][:]; quality=ds.variables['flash_quality_flag'][:]
            times=ds.variables['flash_time_offset_of_first_event']
            dates=num2date(times[:],times.units,only_use_cftime_datetimes=False)
            west,south,east,north=bounds()
            for i in range(len(ids)):
                if np.ma.is_masked(lon[i]) or np.ma.is_masked(lat[i]) or quality[i] != 0:
                    continue
                if west<=lon[i]<=east and south<=lat[i]<=north:
                    observed=dates[i].replace(tzinfo=UTC)
                    db.execute('INSERT OR IGNORE INTO flashes VALUES (?,?,?,?)',
                               (item[0]+':'+str(ids[i]),stamp(observed),float(lon[i]),float(lat[i])))
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',
                       (item[0],ds.time_coverage_start,ds.time_coverage_end,stamp(now()),'glm',json.dumps({'source_sha256':digest})))
            db.commit()
    finally:
        file.unlink(missing_ok=True)


def wind(db,instant):
    _run_source(db,instant,'ABI-L2-DMWF','wind',lambda db,item:_context_item(db,item,'wind'),4)


def rain(db,instant):
    _run_source(db,instant,'ABI-L2-RRQPEF','rain',lambda db,item:_context_item(db,item,'rain'),3)


def _context_item(db,item,kind):
    from backend.app.adapters.goes_products import wind_vectors, read
    directory=root()/'context-sources'
    file=download(item,directory)
    frame=hashlib.sha256(item[0].encode()).hexdigest()[:24]
    try:
        with file.open('rb') as source:
            digest=hashlib.file_digest(source,'sha256').hexdigest()
        if kind=='wind':
            data=wind_vectors(file,stamp(now()))
            artifact=f'{frame}-winds.json'
            temporary=root()/(artifact+'.part')
            data.update(state='available',source=item[0])
            temporary.write_text(json.dumps(data),encoding='utf-8');temporary.replace(root()/artifact)
            meta={'id':frame,'start':data['start'],'end':data['end'],'file':artifact,'count':len(data['features'])}
        else:
            from backend.app.adapters.goes_layers import grayscale
            values,meta=read(file,'RRQPEF')
            numeric=root()/f'{frame}-l2-rrqpef.npz'
            with numeric.with_suffix('.part').open('wb') as stream:
                np.savez_compressed(stream,values=values)
            numeric.with_suffix('.part').replace(numeric)
            finite=values[np.isfinite(values)]
            high=max(1,float(np.percentile(finite,98))) if finite.size else 1
            meta.update(id=frame,file=numeric.name,images={'rain':save_image(frame,'l2-rrqpef',grayscale(values,0,high))},display_range=[0,high])
        meta.update(source=item[0],source_sha256=digest,bounds=bounds(),collected_at=stamp(now()))
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',(item[0],meta['start'],meta['end'],stamp(now()),kind,json.dumps(meta)))
        db.commit()
    finally:
        file.unlink(missing_ok=True)

def catalog():
    enabled = os.getenv('STORMTRACK_SATELLITE_ENABLED','true').lower() != 'false' and not get_settings().serverless
    if not enabled:
        return {'frames':[],'products':[],'bounds':bounds(),'enabled':False}
    with database() as db:
        frames=[json.loads(row[0]) for row in db.execute("SELECT metadata FROM objects WHERE kind='abi' ORDER BY observed")]
        statuses=[dict(row) for row in db.execute('SELECT * FROM status')]
        from backend.app.ingestion import satellite_queue as queue
        for product in ('abi','glm','wind','rain'):
            status=next((s for s in statuses if s['product']==product),None)
            if status is None:
                status={'product':product,'checked':None,'error':None}; statuses.append(status)
            row=db.execute('SELECT max(end) FROM objects WHERE kind=?',(product,)).fetchone()
            status['latest_observed_end']=row[0]
            status['age_seconds']=max(0,int((now()-parse(row[0])).total_seconds())) if row[0] else None
            limit=int(os.getenv('STORMTRACK_GLM_STALE_SECONDS','180')) if product=='glm' else 7200 if product=='wind' else 1800 if product=='rain' else int(os.getenv('STORMTRACK_SATELLITE_STALE_SECONDS','1800'))
            status['state']='unavailable' if row[0] is None else 'delayed' if status['error'] or status['age_seconds']>limit else 'updated'
            status['queue']=queue.status(db,product)
            prefix={'abi':'ABI-L2-CMIPF','glm':'GLM-L2-LCFA','wind':'ABI-L2-DMWF','rain':'ABI-L2-RRQPEF'}[product]
            discovery=db.execute('SELECT checked,recovery_gap FROM satellite_discovery WHERE product=?',(prefix,)).fetchone()
            status['discovered_at']=discovery[0] if discovery else None
            status['recovery_gap']=discovery[1] if discovery else None
    threshold=int(os.getenv('STORMTRACK_SATELLITE_STALE_SECONDS','1800'))
    for frame in frames:
        frame['age_seconds']=max(0,int((now()-parse(frame['end'])).total_seconds()))
        failure = any(s['product']=='abi' and s['error'] for s in statuses)
        frame['state']='delayed' if frame['age_seconds']>threshold or failure else 'updated'
        frame['stale_seconds']=threshold
    return {'frames':frames,'products':statuses,'bounds':bounds(),'enabled':True,'attribution':'NOAA GOES-19; processamento StormTrack',
            'palette':{'values':STOPS,'colors':COLORS},'composite':'RGB diurno + IR noturno; não é GeoColor CIRA'}

def flashes(end, minutes=10):
    if minutes not in (1,5,10,15):
        raise ValueError('GLM window must be 1, 5, 10 or 15 minutes')
    finish=parse(end)
    if finish.tzinfo is None:
        raise ValueError('Timezone required')
    begin=finish-timedelta(minutes=minutes)
    with database() as db:
        rows=db.execute('SELECT * FROM flashes WHERE julianday(observed)>=julianday(?) AND julianday(observed)<=julianday(?)',(stamp(begin),stamp(finish))).fetchall()
        intervals=db.execute("SELECT observed,end FROM objects WHERE kind='glm' AND julianday(end)>=julianday(?) AND julianday(observed)<=julianday(?) ORDER BY observed",(stamp(begin),stamp(finish))).fetchall()
    cursor=begin; covered=0
    for row in intervals:
        start=max(begin,parse(row[0])); stop=min(finish,parse(row[1]))
        if stop>max(cursor,start):
            covered+=(stop-max(cursor,start)).total_seconds()
        cursor=max(cursor,stop)
    fraction=min(1,covered/(minutes*60))
    return {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[r['lon'],r['lat']]},
            'properties':{'observed_at':r['observed']},'id':r['id']} for r in rows],
            'count':len(rows),'start':stamp(begin),'end':stamp(finish),'bounds':bounds(),'coverage_fraction':fraction,
            'rate_flashes_per_minute':len(rows)/minutes if fraction>=.98 else None,
            'state':'unavailable' if not intervals else 'complete' if fraction>=.98 else 'partial'}

def collect_once(stream='all'):
    kinds={'all':('abi','glm','wind','rain'),'abi':('abi',),'glm':('glm',),'context':('wind','rain')}[stream]
    with database() as db:
        for product,method,default_interval in [('abi',abi,10),('glm',glm,10),('wind',wind,30),('rain',rain,30)]:
            if product not in kinds:
                continue
            variable={'abi':'STORMTRACK_SATELLITE_INTERVAL_SECONDS','glm':'STORMTRACK_GLM_INTERVAL_SECONDS','wind':'STORMTRACK_WIND_INTERVAL_SECONDS','rain':'STORMTRACK_RAIN_INTERVAL_SECONDS'}[product]
            interval=max(10,min(3600,int(os.getenv(variable,str(default_interval)))))
            previous=db.execute('SELECT checked FROM status WHERE product=?',(product,)).fetchone()
            if previous and (now()-parse(previous[0])).total_seconds()<interval:
                continue
            error=None
            try:
                method(db,now())
            except Exception as exc:
                error=str(exc); LOG.exception('NOAA %s collection failed',product)
            db.execute('INSERT OR REPLACE INTO status VALUES (?,?,?)',(product,stamp(now()),error)); db.commit()
        cutoff=stamp(now()-timedelta(minutes=history_minutes()+10))
        for row in db.execute("SELECT key,metadata,kind FROM objects WHERE end<?",(cutoff,)).fetchall():
            if row['kind'] not in kinds:
                continue
            meta=json.loads(row['metadata'])
            names=list(meta.get('images',{}).values())
            if meta.get('file'):
                names.append(meta['file'])
            if row['kind']=='abi':
                names.append(meta['id']+'.npz')
            for name in names:
                (root()/name).unlink(missing_ok=True)
            if meta.get('id'):
                for pattern in (meta['id']+'-*.npz',meta['id']+'-*.png',meta['id']+'-*.json'):
                    for file in root().glob(pattern):
                        file.unlink(missing_ok=True)
            db.execute('DELETE FROM objects WHERE key=?',(row['key'],))
        if 'glm' in kinds:
            db.execute('DELETE FROM flashes WHERE observed<?',(cutoff,))
        db.commit()
    # All transient files belong to this dedicated cache; never traverse other directories.
    for pattern in ('*.part','*.nc'):
        for file in root().glob(pattern):
            if time.time()-file.stat().st_mtime>3600:
                file.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--once',action='store_true')
    parser.add_argument('--stream',choices=('all','abi','glm','context'),default='all')
    parser.add_argument('--profile',choices=('basic','convective','research'),default=os.getenv('STORMTRACK_SATELLITE_PROFILE','basic'))
    parser.add_argument('--until',help='Required UTC end time for bounded research collection (maximum 6 hours)')
    args=parser.parse_args()
    os.environ['STORMTRACK_SATELLITE_PROFILE']=args.profile
    until=parse(args.until) if args.until else None
    if until and (until.tzinfo is None or until.utcoffset()!=timedelta(0) or not now()<until<=now()+timedelta(hours=6)):
        parser.error('--until must be a future UTC instant within six hours')
    if args.profile=='research' and until is None:
        parser.error('Research collection requires --until; use the exporter --estimate first')
    logging.basicConfig(level=logging.INFO)
    if os.getenv('VERCEL')=='1':
        raise SystemExit('Regional worker is local-only')
    if os.getenv('STORMTRACK_SATELLITE_ENABLED','true').lower()=='false':
        return
    root().mkdir(parents=True,exist_ok=True)
    # OS-owned lock is released on crashes; separate connection never commits while held.
    locks=[]
    try:
        if args.stream!='all':
            probe=sqlite3.connect(root()/'worker-lock.sqlite3',timeout=.1)
            try:
                probe.execute('BEGIN EXCLUSIVE');probe.rollback()
            finally:
                probe.close()
        names=['worker-lock.sqlite3',*(f'worker-lock-{s}.sqlite3' for s in ('abi','glm','context'))] if args.stream=='all' else [f'worker-lock-{args.stream}.sqlite3']
        for name in names:
            lock=sqlite3.connect(root()/name,timeout=.1);locks.append(lock)
            lock.execute('CREATE TABLE IF NOT EXISTS singleton (id INTEGER)');lock.commit()
            lock.execute('BEGIN EXCLUSIVE')
    except sqlite3.OperationalError:
        for lock in locks:
            lock.close()
        raise SystemExit('Satellite collector stream already running')
    try:
        while True:
            if until and now()>=until:
                break
            collect_once(args.stream)
            if args.once:
                break
            time.sleep(2)
    finally:
        for lock in locks:
            lock.close()

if __name__ == '__main__':
    main()
