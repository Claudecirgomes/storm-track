"""Bounded live/replay atmospheric wind feed, independent of the ABI timeline."""
from datetime import timedelta
import hashlib
import json
from threading import Lock
import time

from backend.app.adapters import regional_satellite as regional
from backend.app.adapters.goes_products import wind_vectors

LOCK=Lock()
MEMORY={}


def winds(end):
    reference=regional.parse(end)
    if reference.tzinfo is None or reference>regional.now()+timedelta(minutes=1):
        raise ValueError('Timezone-aware reference cannot be in the future')
    if regional.get_settings().serverless or not regional.catalog()['enabled']:
        return {'type':'FeatureCollection','features':[],'state':'unavailable','reason':'Coleta local desativada'}
    with regional.database() as db:
        rows=db.execute("SELECT metadata FROM objects WHERE kind='wind' AND julianday(end)<=julianday(?) ORDER BY julianday(end) DESC,processed DESC LIMIT 6",(regional.stamp(reference),)).fetchall()
    for row in rows:
        metadata=json.loads(row[0])
        path=regional.root()/metadata['file']
        if tuple(metadata['bounds'])==regional.bounds() and path.is_file():
            result=json.loads(path.read_text(encoding='utf-8'))
            result['features']=[f for f in result['features'] if regional.parse(f['properties']['observed'])<=reference]
            return result
    cache_key=reference.replace(second=0,microsecond=0).isoformat()
    with LOCK:
        cached=MEMORY.get(cache_key)
        if cached and time.monotonic()-cached[0]<30 and (not cached[1].get('end') or regional.parse(cached[1]['end'])<=reference):
            return cached[1]
        objects=regional.listing('ABI-L2-DMWF',reference,minutes=120)
        directory=regional.root()/'wind-cache';directory.mkdir(exist_ok=True)
        result=None
        for item in reversed(objects[-6:]):
            digest=hashlib.sha256(item[0].encode()).hexdigest()
            metadata=directory/(digest+'.json')
            if metadata.exists():
                candidate=json.loads(metadata.read_text())
                if regional.parse(candidate['end'])>reference:
                    continue
            else:
                file=regional.download(item,directory)
                try:
                    try:
                        candidate=wind_vectors(file,regional.stamp(reference))
                    except ValueError as exc:
                        if 'later than replay' in str(exc):
                            continue
                        raise
                finally:
                    file.unlink(missing_ok=True)
                candidate.update(source=item[0],state='available',kind='atmospheric_motion',
                                 age_seconds=max(0,int((regional.now()-regional.parse(candidate['end'])).total_seconds())))
                temporary=metadata.with_suffix('.part');temporary.write_text(json.dumps(candidate),encoding='utf-8');temporary.replace(metadata)
            result=candidate;break
        if result is None:
            result={'type':'FeatureCollection','features':[],'state':'unavailable','reason':'Sem vetores disponíveis até o horário escolhido'}
        MEMORY.clear();MEMORY[cache_key]=(time.monotonic(),result)
        for file in directory.glob('*.json'):
            if time.time()-file.stat().st_mtime>7200:
                file.unlink(missing_ok=True)
        return result
