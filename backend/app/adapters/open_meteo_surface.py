"""Budgeted, shared Open-Meteo model samples. Not station observations."""
from datetime import datetime, timezone
import json
import math
import sqlite3
import time

import httpx

from backend.app.core.config import get_settings

URL='https://api.open-meteo.com/v1/forecast'
BOUNDS=(-68,-39,-44,-18)
TTL=900
BACKOFF=300
VARIABLES='temperature_2m,wind_speed_10m,wind_direction_10m'


class SurfaceUnavailable(RuntimeError):
    pass


def locations():
    west,south,east,north=BOUNDS
    return [(round(south+i*(north-south)/6,5),round(west+j*(east-west)/5,5))
            for i in range(7) for j in range(6)]+[(-23.4205,-51.9386)]


def directory():
    path=get_settings().data_dir/'surface-model';path.mkdir(parents=True,exist_ok=True)
    return path


def connect():
    if get_settings().serverless:
        from backend.app.core.postgres import PostgresConnection
        db=PostgresConnection(get_settings().database_url)
        db.execute('SET search_path TO stormtrack_weather, pg_catalog')
        return db
    db=sqlite3.connect(directory()/'cache.sqlite3',timeout=5)
    db.execute('CREATE TABLE IF NOT EXISTS cache(id INTEGER PRIMARY KEY,payload TEXT,fetched REAL,attempt REAL,error TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS point_cache(id TEXT PRIMARY KEY,payload TEXT,fetched REAL,attempt REAL,error TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS budget(period TEXT PRIMARY KEY,units INTEGER NOT NULL)')
    db.commit()
    return db


def reserve(db, now, units):
    instant=datetime.fromtimestamp(now,timezone.utc)
    periods=[('minute:'+instant.strftime('%Y-%m-%dT%H:%M'),300),
             ('hour:'+instant.strftime('%Y-%m-%dT%H'),2000),
             ('day:'+instant.strftime('%Y-%m-%d'),8000),
             ('month:'+instant.strftime('%Y-%m'),240000)]
    db.execute('BEGIN IMMEDIATE')
    try:
        for period,limit in periods:
            row=db.execute('SELECT units FROM budget WHERE period=?',(period,)).fetchone()
            if (row[0] if row else 0)+units>limit:
                raise SurfaceUnavailable('Orçamento local do Open-Meteo atingido; aguardando renovação da cota.')
        for period,_ in periods:
            db.execute('INSERT INTO budget VALUES (?,?) ON CONFLICT(period) DO UPDATE SET units=budget.units+excluded.units',(period,units))
        db.commit()
    except Exception:
        db.rollback();raise


def number(value,low,high):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        return None
    return float(value)


def decode(payload, requested, fetched):
    rows=payload if isinstance(payload,list) else [payload]
    if len(rows)!=len(requested):
        raise SurfaceUnavailable('Resposta com número de locais diferente do solicitado.')
    points=[]
    for index,(row,(lat,lon)) in enumerate(zip(rows,requested)):
        current=row.get('current',{});units=row.get('current_units',{})
        if units.get('temperature_2m')!='°C' or units.get('wind_speed_10m')!='km/h' or units.get('wind_direction_10m')!='°':
            raise SurfaceUnavailable('Unidades inesperadas na resposta do modelo.')
        valid_time=number(current.get('time'),0,fetched+90)
        temp=number(current.get('temperature_2m'),-100,70)
        speed=number(current.get('wind_speed_10m'),0,500)
        direction=number(current.get('wind_direction_10m'),0,360)
        if valid_time is None:
            temp=speed=direction=None
        points.append({'type':'Feature','id':index,'geometry':{'type':'Point','coordinates':[lon,lat]},
                       'properties':{'temperature_2m':temp,'wind_speed_10m':speed,'wind_direction_10m':direction,
                                     'valid_at':datetime.fromtimestamp(valid_time,timezone.utc).isoformat() if valid_time is not None else None,
                                     'model_latitude':row.get('latitude'),'model_longitude':row.get('longitude'),
                                     'location_name':'Maringá' if abs(lat+23.4205)<.0001 and abs(lon+51.9386)<.0001 else None}})
    complete=sum(all(p['properties'][key] is not None for key in ('temperature_2m','wind_speed_10m','wind_direction_10m')) for p in points)
    if not any(any(p['properties'][key] is not None for key in ('temperature_2m','wind_speed_10m')) for p in points):
        raise SurfaceUnavailable('O modelo não retornou valores utilizáveis.')
    return {'type':'FeatureCollection','features':points,'bounds':BOUNDS,'state':'available' if complete==len(points) else 'partial',
            'source':'Open-Meteo','source_url':'https://open-meteo.com/','data_kind':'model_output',
            'model_selection':'best_match (seleção automática Open-Meteo)',
            'temperature_units':'°C','wind_speed_units':'km/h','temperature_height_m':2,'wind_height_m':10,
            'fetched_at':datetime.fromtimestamp(fetched,timezone.utc).isoformat(),
            'sampling':f'{len(points)} pontos solicitados; não representa a resolução espacial nativa do modelo',
            'complete_points':complete,'requested_points':len(points)}


def download(requested):
    params={'latitude':','.join(str(lat) for lat,lon in requested),
            'longitude':','.join(str(lon) for lat,lon in requested),
            'current':VARIABLES,'wind_speed_unit':'kmh','temperature_unit':'celsius',
            'timeformat':'unixtime','timezone':'GMT','forecast_days':1,'models':'best_match','cell_selection':'nearest'}
    with httpx.Client(timeout=25,follow_redirects=False) as client:
        with client.stream('GET',URL,params=params) as response:
            response.raise_for_status()
            content=bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content)>1024**2:
                    raise SurfaceUnavailable('Resposta Open-Meteo excedeu o limite local.')
    return json.loads(content)


def cache_result(row, now, error=None):
    result=json.loads(row[0]);result['cache_age_seconds']=max(0,int(now-row[1]))
    if error or now-row[1]>TTL:
        result['state']='delayed';result['error']=error or row[3] or 'Atualização pendente'
    return result


def _cached(requested,table,key):
    if table not in ('cache','point_cache'):
        raise ValueError('Invalid cache namespace')
    now=time.time()
    db=connect();lease=None;remote_locked=False
    try:
        row=db.execute(f'SELECT payload,fetched,attempt,error FROM {table} WHERE id=?',(key,)).fetchone()
        if row and row[0] and now-row[1]<TTL:
            return cache_result(row,now)
        if row and row[2] and now-row[2]<BACKOFF:
            if row[0]:
                return cache_result(row,now,row[3])
            raise SurfaceUnavailable(row[3] or 'Atualização em andamento; tente novamente em alguns minutos.')
        try:
            if get_settings().serverless:
                remote_locked=db.execute('SELECT pg_try_advisory_lock(5461320) AS acquired').fetchone()[0]
                if not remote_locked:raise sqlite3.OperationalError('locked')
            else:
                lease=sqlite3.connect(directory()/'lease.sqlite3',timeout=.1)
                lease.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError:
            if row and row[0]:
                return cache_result(row,now,'Atualização em andamento')
            raise SurfaceUnavailable('Primeira consulta ao modelo em andamento.')
        # Recheck after acquiring the process-independent lease.
        row=db.execute(f'SELECT payload,fetched,attempt,error FROM {table} WHERE id=?',(key,)).fetchone()
        if row and row[0] and now-row[1]<TTL:
            return cache_result(row,now)
        try:
            reserve(db,now,len(requested))
            db.execute(f'INSERT INTO {table} VALUES (?,NULL,NULL,?,NULL) ON CONFLICT(id) DO UPDATE SET attempt=excluded.attempt',(key,now));db.commit()
            result=decode(download(requested),requested,time.time())
            db.execute(f'UPDATE {table} SET payload=?,fetched=?,error=NULL WHERE id=?',(json.dumps(result,allow_nan=False),time.time(),key));db.commit()
            return result
        except Exception as exc:
            message=str(exc) if isinstance(exc,SurfaceUnavailable) else 'Não foi possível atualizar o Open-Meteo.'
            db.execute(f'INSERT INTO {table} VALUES (?,NULL,NULL,?,?) ON CONFLICT(id) DO UPDATE SET attempt=excluded.attempt,error=excluded.error',(key,now,message));db.commit()
            if row and row[0]:
                return cache_result(row,now,message)
            raise SurfaceUnavailable(message) from exc
    finally:
        if remote_locked:
            db.execute('SELECT pg_advisory_unlock(5461320)')
        if lease is not None:
            lease.close()
        db.close()


def surface():
    return _cached(locations(),'cache',1)


def point(lat,lon):
    west,south,east,north=BOUNDS
    if number(lat,south,north) is None or number(lon,west,east) is None:
        raise ValueError('Ponto fora da região Sul/corredor configurada.')
    lat,lon=round(lat,2),round(lon,2)
    return _cached([(lat,lon)],'point_cache',f'{lat:.2f},{lon:.2f}')
