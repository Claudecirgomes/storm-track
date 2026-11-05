"""Physical ABI layers and bounded, reproducible local research sessions.

No model training, inference or operational database writes.
"""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import numpy as np
from netCDF4 import Dataset

from backend.app.adapters import regional_satellite as regional
from backend.app.adapters.goes_products import RASTER_LAYERS, CATEGORY_COLORS

VERSION = '1.0.0'


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

NAMES = ['Azul visível', 'Vermelho visível', 'Vegetação', 'Cirrus', 'Neve/gelo',
         'Microfísica', 'IR curto', 'Vapor alto', 'Vapor médio', 'Vapor baixo',
         'Fase de nuvem', 'Ozônio', 'Janela IR limpa', 'Janela IR', 'Janela úmida', 'CO₂']
WAVELENGTHS = [.47,.64,.86,1.38,1.61,2.24,3.9,6.19,6.95,7.34,8.5,9.6,10.3,11.2,12.3,13.3]
DIFFERENCES = {'split-window':(13,15), 'fog':(13,7), 'phase':(11,14),
               'split-vapor':(8,10), 'split-ozone':(12,13), 'vapor-window':(8,13)}
PROFILES = {'basic':(13,), 'convective':(8,9,10,11,13,15), 'research':tuple(range(1,17))}
L2 = ['ACMF','ACHAF','ACHTF','CTPF','ACTPF','CODF','CPSF','TPWF','DSIF','LVTPF',
      'LVMPF','DMWF','DMWVF','RRQPEF','ADPF','AODF','FDCF','LSTF','GFLSF','VAAF','DSRF','RSRF','SSTF']
# Explicit display recipe, not a Meteologix palette or a severity classification.
TOP_STOPS = [-100,-80,-70,-60,-50,-40,-30,40]
TOP_COLORS = [[180,0,30],[255,30,30],[255,220,0],[60,210,60],[0,220,240],[30,80,220],[235,235,235],[25,25,25]]
# Expressions, low/high stretch, gamma. Reflectances use fractions, IR uses K.
# ABI recipes checked against CIRA guides and Satpy ABI configuration.
RGB_SOURCE='https://github.com/pytroll/satpy/blob/main/satpy/etc/enhancements/abi.yaml'
RGB = {
    'airmass':(((8,10),(12,13),(8,)),(-26.2,-43.2,243.9),(.6,6.7,208.5),(1,1,1),'any'),
    'night-microphysics':(((15,13),(13,7),(13,)),(-6.7,-3.1,243.55),(2.6,5.2,292.65),(1,1,1),'night'),
    'dust':(((15,13),(14,11),(13,)),(-6.7,-.5,261.2),(2.6,20,288.7),(1,2.5,1),'any'),
    'ash':(((15,13),(14,11),(13,)),(-6.7,-6,243.6),(2.6,6.3,302.4),(1,1,1),'any'),
    'so2':(((9,10),(13,11),(13,)),(-4,-4,243),(2,5,303),(1,1,1),'any'),
    'day-convection':(((8,10),(7,13),(5,2)),(-35,-5,-.75),(5,60,.25),(1,1,1),'day'),
    'day-cloud-type':(((4,),(2,),(5,)),(0,0,0),(.1,.8,.8),(1.5,.75,1),'day'),
    'fire-temperature':(((7,),(6,),(5,)),(273.15,0,0),(333.15,1,.75),(.4,1,1),'day'),
    'day-cloud-phase':(((13,),(2,),(5,)),(280.65,0,.01),(219.65,.78,.59),(1,1,1),'day'),
    'simple-vapor':(((13,),(8,),(10,)),(278.96,242.67,261.03),(202.29,214.66,245.12),(1,1,1),'any'),
    'differential-vapor':(((10,8),(10,),(8,)),(30,278.15,243.90),(-3,213.15,208.50),(.2587,.4,.4),'any'),
    'day-cloud-convection':(((2,),(2,),(13,)),(0,0,323),(1,1,203),(1.7,1.7,1),'day'),
    'day-land-cloud':(((5,),(3,),(2,)),(0,0,0),(.975,1.086,1),(1,1,1),'day'),
    'day-land-cloud-fire':(((6,),(3,),(2,)),(0,0,0),(1,1,1),(1,1,1),'day'),
    'day-snow-fog':(((3,),(5,),(7,13)),(0,0,0),(1,.7,30),(1.7,1.7,1.7),'day'),
    'true-color':(((2,),(3,),(1,)),(0,0,0),(1,1,1),(2.2,2.2,2.2),'day'),
}


def render_rgb(fields, name, instant):
    if name=='true-color':
        fields=dict(fields)
        fields[3]=.45*fields[2]+.1*fields[3]+.45*fields[1]
    expressions,low,high,gamma,condition=RGB[name]
    components=[]
    for expression,a,b,g in zip(expressions,low,high,gamma):
        value=fields[expression[0]].copy()
        if len(expression)==2:
            value-=fields[expression[1]]
        components.append(np.clip((value-a)/(b-a),0,1)**(1/g))
    rgb=np.stack(components,axis=-1)
    mask=np.isfinite(rgb).all(axis=-1)
    if condition!='any':
        cosine=solar_cosine(instant)
        mask &= cosine>.1 if condition=='day' else cosine<0
    rgba=np.zeros((*mask.shape,4),dtype='uint8')
    rgba[...,:3]=np.nan_to_num(rgb*255).astype('uint8');rgba[...,3]=mask*255
    return rgba


def registry():
    return [{'id':f'abi{c:02d}', 'name':f'C{c:02d} — {NAMES[c-1]}',
             'group':'Canais ABI', 'unit':'1' if c<=6 else 'K',
             'wavelength_um':WAVELENGTHS[c-1],
             'native_nadir_km':.5 if c==2 else 1 if c in (1,3,5) else 2,
             'condition':'iluminação solar' if c<=6 else 'componente solar diurna' if c==7 else 'dia/noite',
             'status':'implemented_real_test_pending'} for c in range(1,17)] + [
             {'id':key,'name':f'C{a:02d} − C{b:02d}', 'group':'Pesquisa','unit':'K',
              'status':'implemented_real_test_pending'} for key,(a,b) in DIFFERENCES.items()] + [
              {'id':key,'name':key,'group':'RGB','unit':'RGB display only','recipe_version':VERSION,
               'recipe':recipe,'source':RGB_SOURCE,'solar_correction':'none; raw reflectance; terminator masked',
               'status':'implemented_real_test_pending'} for key,recipe in RGB.items()] + [
               {'id':key,'name':f'{product} — {variable}','group':'Produtos NOAA L2','unit':'source metadata',
                'status':'adapter_implemented_product_quality_gate_required'} for key,(product,variable) in RASTER_LAYERS.items()]


def dependencies(layer):
    if layer in RASTER_LAYERS:
        return ()
    if layer in RGB:
        return tuple(sorted({c for expr in RGB[layer][0] for c in expr}))
    if layer.startswith('abi') and layer[3:].isdigit() and 1<=int(layer[3:])<=16:
        return (int(layer[3:]),)
    if layer in DIFFERENCES:
        return DIFFERENCES[layer]
    raise ValueError('Unknown physical layer')


def solar_cosine(instant):
    lon,lat = regional.grid()
    decl=np.deg2rad(23.44*np.sin(2*np.pi*(instant.timetuple().tm_yday-81)/365.25))
    hour=np.deg2rad((instant.hour+instant.minute/60+instant.second/3600+lon/15-12)*15)
    return np.sin(np.deg2rad(lat))*np.sin(decl)+np.cos(np.deg2rad(lat))*np.cos(decl)*np.cos(hour)


@regional.scientific
def physical(path, channel):
    with Dataset(path) as ds:
        satellite=getattr(ds,'platform_ID',None)
        if satellite not in ('G19','GOES-19'):
            raise ValueError('File platform_ID does not identify GOES-19')
        if 'band_id' not in ds.variables or int(ds.variables['band_id'][...].item())!=channel:
            raise ValueError('NetCDF band_id disagrees with requested channel')
        source_grid={'native_shape':[len(ds.dimensions['y']),len(ds.dimensions['x'])],
                     'scan_angle_spacing_radians':[float(abs(ds['x'][1]-ds['x'][0])),float(abs(ds['y'][1]-ds['y'][0]))],
                     'nominal_wavelength_um':float(ds['band_wavelength'][...].item()) if 'band_wavelength' in ds.variables else None,
                     'calibration':'CMIP physical CMI, netCDF4 automatic mask/scale once; no Planck conversion',
                     'quality_meanings':getattr(ds['DQF'],'flag_meanings',None)}
    values,meta=regional.read_channel(path)
    if channel>=7:
        if meta['units']!='K':
            raise ValueError('Thermal ABI channel must have kelvin units')
        values=values+273.15
    elif meta['units'] not in ('1','unitless'):
        raise ValueError('Reflective ABI channel must be dimensionless')
    if channel<=6:
        values[solar_cosine(regional.parse(meta['start']))<=0]=np.nan
    meta.update(channel=channel,unit='K' if channel>=7 else '1',quality='CMIP DQF=0 only',
                resampling='nearest',crs='EPSG:3857',bounds=regional.bounds(),
                parallax='not corrected',illumination='approximate solar geometry; night masked' if channel<=6 else None)
    meta.update(source_grid)
    return values.astype('float32'),meta


def tops(values, overlay=False):
    result=np.zeros((*values.shape,4),dtype='uint8')
    for c in range(3):
        result[...,c]=np.interp(np.nan_to_num(values),TOP_STOPS,np.array(TOP_COLORS)[:,c]).astype('uint8')
    result[...,3]=np.where(np.isfinite(values),np.clip((-30-values)/10,0,1)*255 if overlay else 255,0).astype('uint8')
    return result


def grayscale(values, low, high):
    shade=(np.clip((values-low)/(high-low),0,1)*255)
    result=np.zeros((*values.shape,4),dtype='uint8')
    result[...,:3]=np.nan_to_num(shade)[...,None].astype('uint8')
    result[...,3]=np.where(np.isfinite(values),255,0)
    return result


def acquire(instant, channels, directory):
    """One listing, same satellite and scan; retain source bytes once per session."""
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    objects=regional.listing('ABI-L2-CMIPF',instant,minutes=20)
    anchors=[x for x in objects if 'C13_G19_' in x[0]]
    if not anchors:
        raise ValueError('No C13 anchor in bounded interval')
    anchor=anchors[-1]
    fields={}; sources=[]
    for channel in sorted(set(channels)):
        matches=[x for x in objects if f'C{channel:02d}_G19_' in x[0]
                 and abs((regional.parse(x[2])-regional.parse(anchor[2])).total_seconds())<=1]
        if not matches:
            raise ValueError(f'Missing required channel C{channel:02d} at scan {anchor[2]}')
        item=matches[-1]
        name=hashlib.sha256(item[0].encode()).hexdigest()+'.nc'
        target=directory/name
        if not target.exists():
            quota=int(os.getenv('STORMTRACK_RESEARCH_MAX_BYTES',str(2*1024**3)))
            if sum(p.stat().st_size for p in directory.glob('*.nc'))+item[1]>quota:
                raise RuntimeError('Research session quota reached; pinned files preserved')
            if shutil.disk_usage(directory).free < item[1]+256*1024**2:
                raise RuntimeError('Minimum free disk reserve reached')
            regional.download(item,directory)
        digest=file_hash(target)
        values,meta=physical(target,channel)
        fields[channel]=values
        sources.append(dict(meta,key=item[0],sha256=digest,source_file=name,bytes=target.stat().st_size,
                            source_available_at=None,source_available_reason='not provided by listing',
                            downloaded_at=regional.stamp(regional.now())))
    return fields,sources


def inventory(instant, output):
    """Real listing evidence. Listing is explicitly not scientific validation."""
    report={'checked_at':regional.stamp(regional.now()),'satellite':'GOES-19','products':[]}
    for product in ['ABI-L2-CMIPF','GLM-L2-LCFA']+['ABI-L2-'+code for code in L2]:
        record={'product':product,'status':'real_validation_pending'}
        try:
            objects=regional.listing(product,instant,minutes=60)
            record.update(objects=len(objects),sample=objects[-1] if objects else None,
                          interval_minutes=60,region_coverage='not verified',
                          state='objects_found' if objects else 'no_objects_in_checked_interval')
        except Exception as exc:
            record.update(state='source_unavailable',error=str(exc))
        report['products'].append(record)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def peak_ram():
    if os.name!='nt':
        return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    process=ctypes.windll.kernel32.GetCurrentProcess
    process.restype=wintypes.HANDLE
    query=ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if query(process(),ctypes.byref(counters),counters.cb):
        return counters.PeakWorkingSetSize
    return None


def derive(fields, layer):
    deps=dependencies(layer)
    value=fields[deps[0]].copy()
    if len(deps)==2:
        value-=fields[deps[1]]
    return value


def export_session(start, end, output, channels=(13,), event_id=None, origin='real'):
    start,end=regional.parse(start),regional.parse(end)
    if start.tzinfo is None or end.tzinfo is None or start.utcoffset()!=timedelta(0) or end.utcoffset()!=timedelta(0) or not start<=end or end-start>timedelta(hours=6):
        raise ValueError('UTC-aware bounded interval required (maximum six hours)')
    output=Path(output)
    if output.exists():
        raise ValueError('Use a new session directory; existing datasets are immutable')
    output.mkdir(parents=True)
    began=time.perf_counter(); cpu=time.process_time()
    manifest={'schema_version':VERSION,'dataset_version':VERSION,'run_id':output.name,
              'origin':origin,'event_id':event_id,'annotation_state':'pending','samples':[],
              'required_channels':list(channels),'optional_channels':[], 'bounds':regional.bounds(),
              'code_version':VERSION,'code_sha256':file_hash(__file__),'no_inference':True,
              'source_product':'ABI-L2-CMIPF','satellite':'GOES-19','sensor':'ABI',
              'interval':{'start':regional.stamp(start),'end':regional.stamp(end)}}
    try:
        anchors=regional.listing('ABI-L2-CMIPF',end,minutes=max(1,int((end-start).total_seconds()/60)+1),channel=13)
        for item in anchors:
            if regional.parse(item[2])<start:
                continue
            fields,sources=acquire(regional.parse(item[2])+timedelta(seconds=1),channels,output/'sources')
            sid=hashlib.sha256('|'.join(s['sha256'] for s in sources).encode()).hexdigest()[:24]
            path=output/(sid+'.nc')
            lon,lat=regional.grid(); height,width=lon.shape
            with Dataset(path.with_suffix('.part'),'w') as ds:
                ds.createDimension('y',height); ds.createDimension('x',width)
                ds.Conventions='CF-1.8'; ds.scene_id=sid; ds.satellite='GOES-19'; ds.sensor='ABI'
                ds.resampling='nearest'; ds.parallax='not corrected'; ds.origin=origin
                for name,data in [('longitude',lon),('latitude',lat)]:
                    v=ds.createVariable(name,'f8',('y','x')); v[:]=data
                    v.standard_name=name; v.units='degrees_east' if name=='longitude' else 'degrees_north'
                for channel,values in fields.items():
                    v=ds.createVariable(f'C{channel:02d}','f4',('y','x'),fill_value=np.nan,zlib=True)
                    v[:]=values; v.units='1' if channel<=6 else 'K'; v.coordinates='longitude latitude'
                    v.quality_filter='CMIP DQF=0'; v.source_sha256=next(s['sha256'] for s in sources if s['channel']==channel)
            path.with_suffix('.part').replace(path)
            from pyproj import Transformer
            project=Transformer.from_crs(4326,3857,always_xy=True)
            west,south,east,north=regional.bounds()
            left,bottom=project.transform(west,south);right,top=project.transform(east,north)
            scene_id=hashlib.sha256(('GOES-19:ABI:'+sources[0]['start']).encode()).hexdigest()[:24]
            sample={'sample_id':sid,'scene_id':scene_id,'revision':file_hash(path),
                    'event_id':event_id,'origin':origin,'state':'usable' if all(np.isfinite(v).any() for v in fields.values()) else 'incomplete',
                    'annotation_state':'pending','sources':sources,'file':path.name,
                    'shape':[height,width],'crs':'EPSG:3857','bounds':regional.bounds(),
                    'transform':[left,(right-left)/width,0,top,0,-(top-bottom)/height],
                    'effective_grid_spacing_m':[(right-left)/width,(top-bottom)/height],
                    'resampling':'nearest','parallax':'not corrected','missing_channels':[],
                    'observation_start':sources[0]['start'],'observation_end':max(s['end'] for s in sources),
                    'valid_fraction':{str(c):float(np.isfinite(v).mean()) for c,v in fields.items()},
                    'processed_at':regional.stamp(regional.now()),'published_at':None}
            manifest['samples'].append(sample)
            if 13 in fields:
                from PIL import Image
                Image.fromarray(tops(fields[13]-273.15)).save(output/(sid+'.png'))
        if not manifest['samples']:
            raise ValueError('No real observations in requested interval')
        from backend.app.analysis.research_samples import coco_template
        (output/'annotations.coco.json').write_text(json.dumps(coco_template(manifest['samples']),ensure_ascii=False,indent=2),encoding='utf-8')
        (output/'experiments.json').write_text(json.dumps({'state':'planned_not_trained',
            'input_sets':{'c13':[13],'ir_vapor':[8,9,10,13,15],'daylight':[1,2,3,5,13]},
            'normalization_fit_split':'train_only','split_unit':'human curated event; temporal embargo and spatial overlap checks required',
            'rgb_independent_observations':False},indent=2),encoding='utf-8')
        manifest['state']='complete'
    except Exception as exc:
        manifest['state']='incomplete';manifest['error']=str(exc)
        raise
    finally:
        manifest['benchmark']={'wall_seconds':time.perf_counter()-began,'cpu_seconds':time.process_time()-cpu,
                               'source_bytes':sum(p.stat().st_size for p in (output/'sources').glob('*.nc')),
                               'disk_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
                               'peak_ram_bytes':peak_ram(),'peak_ram_reason':'process high-water mark on Windows'}
        tmp=output/'manifest.part'; tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(output/'manifest.json')
    return manifest


def validate_splits(samples, embargo_minutes=60):
    """Conservative scene/hash/event/time leakage guard; overlapping regional scenes."""
    for i,a in enumerate(samples):
        for b in samples[i+1:]:
            if a['split']==b['split']:
                continue
            if (a.get('event_id') and a['event_id']==b.get('event_id')) or a['scene_id']==b['scene_id']:
                raise ValueError('Event/scene leakage across splits')
            if set(a.get('source_hashes',[])) & set(b.get('source_hashes',[])):
                raise ValueError('Source hash leakage across splits')
            if abs((regional.parse(a['start'])-regional.parse(b['start'])).total_seconds())<embargo_minutes*60:
                raise ValueError('Temporal embargo violation across splits')


def scene_metadata(scene):
    import re
    if not re.fullmatch('[a-f0-9]{24}',scene):
        raise ValueError('Invalid scene identifier')
    with regional.database() as db:
        for row in db.execute("SELECT metadata FROM objects WHERE kind='abi'"):
            meta=json.loads(row[0])
            if meta['id']==scene:
                return meta
    raise ValueError('Scene outside local retention')


def prepare_layer(scene, layer):
    """Explicit on-demand acquisition, serialized independently of browser tabs."""
    import sqlite3
    from PIL import Image
    meta=scene_metadata(scene)
    if tuple(meta['bounds'])!=tuple(regional.bounds()):
        raise ValueError('Configured grid changed; reprocess scene before adding physical layers')
    if os.getenv('STORMTRACK_SATELLITE_ENABLED','true').lower()=='false' or regional.get_settings().serverless:
        raise ValueError('Local extension disabled')
    special=layer in ('tops','tops-overlay','gray','reference')
    deps=(13,) if special else dependencies(layer)
    lock=sqlite3.connect(regional.root()/'layers-lock.sqlite3',timeout=.1)
    try:
        lock.execute('CREATE TABLE IF NOT EXISTS singleton(id INTEGER)');lock.commit();lock.execute('BEGIN EXCLUSIVE')
        numeric=regional.root()/f'{scene}-{layer}.npz'
        image=regional.root()/f'{scene}-{layer}.png'
        details=regional.root()/f'{scene}-{layer}.json'
        if layer=='l2-rrqpef':
            with regional.database() as db:
                rows=db.execute("SELECT metadata FROM objects WHERE kind='rain' AND julianday(end)<=julianday(?) ORDER BY julianday(end) DESC,processed DESC LIMIT 6",(meta['end'],)).fetchall()
            for row in rows:
                collected=json.loads(row[0])
                source_numeric=regional.root()/collected['file']
                source_image=regional.root()/collected['images']['rain']
                if tuple(collected['bounds'])!=tuple(meta['bounds']) or not source_numeric.is_file() or not source_image.is_file():
                    continue
                previous=json.loads(details.read_text(encoding='utf-8')) if details.exists() else {}
                if not numeric.exists() or previous.get('source')!=collected['source']:
                    shutil.copyfile(source_numeric,numeric.with_suffix('.part'));numeric.with_suffix('.part').replace(numeric)
                    temporary=details.with_suffix('.part');temporary.write_text(json.dumps(collected),encoding='utf-8');temporary.replace(details)
                return {'image':source_image.name,'unit':collected['units'],'scene':scene,'layer':layer,
                        'start':collected['start'],'end':collected['end'],'status':'available' if collected['valid_fraction']>0 else 'not_applicable_or_no_valid_pixels',
                        'bounds':collected['bounds'],'palette':None,'categories':None,'category_colors':None,'range':collected['display_range']}
        if not image.exists() or not numeric.exists():
            if sum(p.stat().st_size for p in regional.root().rglob('*') if p.is_file())>512*1024**2:
                raise RuntimeError('Disposable cache quota reached; collection paused')
            if layer in RASTER_LAYERS:
                from backend.app.adapters.goes_products import read
                product,variable=RASTER_LAYERS[layer]
                candidates=regional.listing('ABI-L2-'+product,regional.parse(meta['end']),minutes=60)
                value=None
                for item in reversed(candidates[-3:]):
                    file=regional.download(item,regional.root()/'demand-sources')
                    try:
                        candidate,product_meta=read(file,product,variable)
                        if regional.parse(product_meta['end'])<=regional.parse(meta['end']):
                            value=candidate
                            product_meta['source_key']=item[0]
                            product_meta['source_sha256']=file_hash(file)
                            break
                    finally:
                        file.unlink(missing_ok=True)
                if value is None:
                    raise ValueError('No product observation at or before replay reference')
                finite=value[np.isfinite(value)]
                product_meta['display_range']=np.percentile(finite,[2,98]).tolist() if finite.size else [0,1]
                if product_meta['display_range'][0]==product_meta['display_range'][1]:
                    product_meta['display_range'][1]+=1
                temporary=details.with_suffix('.part');temporary.write_text(json.dumps(product_meta),encoding='utf-8');temporary.replace(details)
            elif special:
                with np.load(regional.root()/(scene+'.npz'),allow_pickle=False) as saved:
                    value=saved['c13_celsius'].copy()
                sources=[{'key':meta.get('source'),'units':'degC','quality':'CMIP DQF=0'}]
            else:
                directory=regional.root()/'demand-sources'
                try:
                    fields={};sources=[];missing=[]
                    for channel in deps:
                        cached=regional.root()/f'{scene}-abi{channel:02d}.npz'
                        if cached.exists():
                            with np.load(cached,allow_pickle=False) as stored:
                                fields[channel]=stored['values'].copy()
                        else:
                            missing.append(channel)
                    if missing:
                        acquired,sources=acquire(regional.parse(meta['start'])+timedelta(seconds=1),missing,directory)
                        fields.update(acquired)
                        for channel,physical_values in acquired.items():
                            cached=regional.root()/f'{scene}-abi{channel:02d}.npz'
                            with cached.with_suffix('.part').open('wb') as stream:
                                np.savez_compressed(stream,values=physical_values)
                            cached.with_suffix('.part').replace(cached)
                            source=next(s for s in sources if s['channel']==channel)
                            cached.with_suffix('.json').write_text(json.dumps(source),encoding='utf-8')
                    value=fields[deps[0]] if layer in RGB else derive(fields,layer)
                finally:
                    # This directory is disposable, separate from pinned session sources.
                    for file in directory.glob('*.nc'):
                        file.unlink(missing_ok=True)
            if layer in RASTER_LAYERS:
                if product_meta['categorical']:
                    colors=np.array(CATEGORY_COLORS,dtype='uint8')
                    rgba=np.zeros((*value.shape,4),dtype='uint8')
                    for index,code in enumerate(product_meta['categories']):
                        valid=np.isfinite(value)&(value==float(code))
                        rgba[valid,:3]=colors[index%len(colors)];rgba[valid,3]=255
                else:
                    rgba=grayscale(value,*product_meta['display_range'])
            else:
                rgba=regional.reference_clouds(value) if layer=='reference' else render_rgb(fields,layer,regional.parse(meta['start'])) if layer in RGB else tops(value,layer=='tops-overlay') if special and layer!='gray' else grayscale(value,40,-100) if layer=='gray' else grayscale(value,0,1) if deps[0]<=6 else grayscale(value,-20,20) if len(deps)>1 else grayscale(value,313.15,173.15)
            with numeric.with_suffix('.part').open('wb') as stream:
                np.savez_compressed(stream,values=value)
            numeric.with_suffix('.part').replace(numeric)
            temporary=image.with_suffix('.part');Image.fromarray(rgba).save(temporary,format='PNG');temporary.replace(image)
        product_meta=json.loads(details.read_text(encoding='utf-8')) if details.exists() else meta
        unit=('categoria' if product_meta['categorical'] else product_meta['units']) if layer in RASTER_LAYERS else 'RGB' if layer in RGB else '°C' if special else 'K' if deps[0]>=7 or len(deps)>1 else '1'
        with Image.open(image) as rendered:
            applicable=bool(np.asarray(rendered)[...,3].any())
        return {'image':image.name,'unit':unit,'scene':scene,'layer':layer,'start':product_meta['start'],'end':product_meta['end'],
                'status':'available' if applicable else 'not_applicable_or_no_valid_pixels','bounds':meta['bounds'],'palette':{'values':regional.STOPS,'colors':regional.COLORS} if layer=='reference' else {'values':TOP_STOPS,'colors':TOP_COLORS} if layer.startswith('tops') else None,
                'categories':product_meta.get('categories'),
                'category_colors':CATEGORY_COLORS if product_meta.get('categorical') else None,
                'range':product_meta['display_range'] if layer in RASTER_LAYERS else [TOP_STOPS[0],TOP_STOPS[-1]] if layer.startswith('tops') else [40,-100] if layer=='gray' else [0,1] if deps[0]<=6 else [-20,20] if len(deps)>1 else [313.15,173.15]}
    finally:
        lock.close()


def sample_point(scene,layer,lon,lat):
    meta=scene_metadata(scene)
    if layer in RGB:
        raise ValueError('RGB is a display representation; query individual ABI channels for physical values')
    west,south,east,north=meta['bounds']
    if not west<=lon<=east or not south<=lat<=north:
        raise ValueError('Point outside scene coverage')
    path=regional.root()/f'{scene}-{layer}.npz'
    if layer not in ('tops','tops-overlay','gray','reference'):
        dependencies(layer)
    if not path.is_file():
        raise ValueError('Prepare layer before numerical query')
    from pyproj import Transformer
    project=Transformer.from_crs(4326,3857,always_xy=True)
    left,bottom=project.transform(west,south);right,top=project.transform(east,north);x,y=project.transform(lon,lat)
    with np.load(path,allow_pickle=False) as data:
        values=data['values'];h,w=values.shape
        value=float(values[min(h-1,int((top-y)/(top-bottom)*h)),min(w-1,int((x-left)/(right-left)*w))])
    details=regional.root()/f'{scene}-{layer}.json'
    if details.exists():
        meta.update(json.loads(details.read_text(encoding='utf-8')))
    return {'value':value if np.isfinite(value) else None,'quality':'valid accepted DQF' if np.isfinite(value) else 'no-data / night / invalid',
            'category':meta.get('categories',{}).get(str(int(value))) if np.isfinite(value) else None,
            'unit':('categoria' if meta['categorical'] else meta['units']) if layer in RASTER_LAYERS else '°C' if layer in ('tops','tops-overlay','gray','reference') else '1' if layer.startswith('abi') and int(layer[3:])<=6 else 'K',
            'start':meta['start'],'end':meta['end'],'source':'NOAA GOES-19 ABI','scene':scene,'layer':layer}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start');parser.add_argument('--end',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--event-id')
    parser.add_argument('--inventory',action='store_true')
    parser.add_argument('--estimate',action='store_true',help='List source volume without downloading')
    parser.add_argument('--profile',choices=PROFILES,default='basic')
    parser.add_argument('--channels',help='Comma-separated required ABI channel numbers')
    args=parser.parse_args()
    if args.inventory:
        inventory(regional.parse(args.end),args.output)
        return
    if not args.start:
        parser.error('--start is required for export/estimate')
    channels=tuple(int(c) for c in args.channels.split(',')) if args.channels else PROFILES[args.profile]
    if not channels or any(c<1 or c>16 for c in channels):
        parser.error('Channels must be between 1 and 16')
    if args.estimate:
        start,end=regional.parse(args.start),regional.parse(args.end)
        if start.tzinfo is None or end.tzinfo is None or not start<=end or end-start>timedelta(hours=6):
            parser.error('Interval must be timezone-aware and at most six hours')
        objects=regional.listing('ABI-L2-CMIPF',end,minutes=int((end-start).total_seconds()/60)+1)
        chosen=[item for item in objects if regional.parse(item[2])>=start and any(f'C{c:02d}_G19_' in item[0] for c in channels)]
        print(json.dumps({'objects':len(chosen),'source_bytes':sum(x[1] for x in chosen),
                          'free_disk_bytes':shutil.disk_usage('.').free,'estimated_time_seconds':None,
                          'reason':'requires measured throughput for chosen channels'}))
        return
    export_session(args.start,args.end,args.output,channels,args.event_id)


if __name__=='__main__':
    main()
