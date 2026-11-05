"""NOAA L2 raster adapters. Product-specific flags are read from each file.

Profiles and atmospheric motion vectors deliberately require dedicated readers.
Candidate variable names never replace inspection of the actual file.
"""
from pathlib import Path
import hashlib
import json

import numpy as np
from netCDF4 import Dataset
from pyproj import CRS, Transformer

from backend.app.adapters import regional_satellite as regional

VARIABLES={
    'ACMF':('ACM',),'ACHAF':('HT',),'ACHTF':('TEMP',),'CTPF':('PRES',),
    'ACTPF':('Phase',),'CODF':('COD',),'CPSF':('CPS',),'TPWF':('TPW',),
    'DSIF':('CAPE','LI','KI','TT','SI'),'RRQPEF':('RRQPE',),
    'ADPF':('Smoke','Dust'),'AODF':('AOD',),'FDCF':('Mask',),
    'LSTF':('LST',),'GFLSF':('Fog_Prob',),'VAAF':('Ash',),
    'DSRF':('DSR',),'RSRF':('RSR',),'SSTF':('SST',)}
RASTER_LAYERS={
    ('l2-'+product.lower() if len(variables)==1 else 'l2-'+product.lower()+'-'+variable.lower()):(product,variable)
    for product,variables in VARIABLES.items() for variable in variables}
CATEGORY_COLORS=[[20,30,60],[80,110,140],[180,190,200],[255,255,255],[40,170,220],[220,100,40]]


def inspect(path):
    with Dataset(path) as ds:
        return {'satellite':getattr(ds,'platform_ID',None),'start':ds.time_coverage_start,
                'end':ds.time_coverage_end,'variables':{
                    name:{'shape':list(var.shape),'dimensions':list(var.dimensions),
                          'units':getattr(var,'units',None),'long_name':getattr(var,'long_name',None),
                          'flag_meanings':getattr(var,'flag_meanings',None),
                          'flag_values':np.asarray(getattr(var,'flag_values',[])).tolist()}
                    for name,var in ds.variables.items()}}


@regional.scientific
def read(path, product, variable=None):
    if product not in VARIABLES:
        raise ValueError('Product requires a dedicated non-raster adapter')
    with Dataset(path) as ds:
        if getattr(ds,'platform_ID',None) not in ('G19','GOES-19'):
            raise ValueError('Unexpected satellite identity')
        if variable is None:
            variable=next((n for n in VARIABLES[product] if n in ds.variables),None)
        if variable not in VARIABLES[product] or variable not in ds.variables:
            raise ValueError('Documented variable absent from source file')
        qname=next((n for n in ('DQF_'+variable,'DQF','DQF_Overall') if n in ds.variables),None)
        if not qname:
            raise ValueError('Quality decoder unavailable for this product')
        quality=ds[qname]
        meanings=getattr(quality,'flag_meanings','').split()
        flags=np.asarray(getattr(quality,'flag_values',[])).ravel().tolist()
        # Only explicit good-quality enum flags; unknown/bit-packed flags fail closed.
        good=[flag for flag,meaning in zip(flags,meanings) if meaning.lower() in
              ('good_quality_qf','good_quality','good_quality_retrieval','good_quality_retrieval_qf',
               'high_quality_retrieval_qf','good_quality_fire_pixel_qf','good_quality_fire_free_land_pixel_qf')]
        if product=='ACTPF' and 'overall_good_quality_qf' in meanings:
            good=[0]  # All six quality/degradation bits clear.
        elif product in ('CODF','CPSF') and 'good_quality_qf' in meanings and 'day_algorithm_pixel_qf' in meanings:
            good=[0,1,2,3]  # Bits 0/1 select algorithms; bits 2..9 are degradation flags.
        elif product=='ADPF' and f'high_confidence_{variable.lower()}_detection_qf' in meanings:
            mask={'Smoke':12,'Dust':48}[variable]
            good=[v for v in range(256) if v&mask==0]
        elif product=='LSTF' and 'high_quality_retrieval_qf' in meanings and flags==[0,1,2,3]:
            good=[0]
        elif hasattr(quality,'flag_masks'):
            good=[]
        if not good:
            raise ValueError('Product-specific DQF decoding not yet validated')
        extra=[]
        if product in ('TPWF','DSIF'):
            for name,meaning in [('DQF_Retrieval','good_retrieval_qf'),('DQF_SkinTemp','good_first_guess_skin_temp_qf')]:
                q=ds[name];ms=q.flag_meanings.split();vs=np.asarray(q.flag_values).tolist()
                if meaning not in ms:
                    raise ValueError('LAP retrieval quality schema changed')
                extra.append((name,[vs[ms.index(meaning)]]))
        var=ds[variable]
        categorical=hasattr(var,'flag_values')
        codes=np.asarray(getattr(var,'flag_values',[])).tolist()
        labels=getattr(var,'flag_meanings','').split()
    values,meta=regional.read_channel(path,variable,qname,good,False,extra)
    meta.update(variable=variable,product='ABI-L2-'+product,quality_variable=qname,
                accepted_flags=good,extra_quality=extra,categorical=categorical,categories=dict(zip(map(str,codes),labels)),
                resampling='nearest',parallax='not corrected',
                limitations='Retrieval conditions and product maturity require independent validation')
    return values,meta


def export_file(path,product,output,variable=None):
    """Equivalent numeric NPZ + metadata, with coordinates and explicit quality mask."""
    values,meta=read(path,product,variable)
    lon,lat=regional.grid();output=Path(output)
    if output.exists() or output.with_suffix('.json').exists():
        raise ValueError('Export already exists')
    temporary=output.with_suffix('.part')
    with temporary.open('wb') as stream:
        np.savez_compressed(stream,values=values,valid=np.isfinite(values),longitude=lon,latitude=lat)
    temporary.replace(output)
    from backend.app.adapters.goes_layers import file_hash
    meta.update(source_sha256=file_hash(path),
                bounds=regional.bounds(),crs='EPSG:3857',origin='real',annotation_state='pending')
    output.with_suffix('.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return meta


@regional.scientific
def profile_point(path,lon,lat):
    """All actual LAP pressure levels at a native pixel; never fills cloudy gaps."""
    with Dataset(path) as ds:
        if getattr(ds,'platform_ID',None) not in ('G19','GOES-19'):
            raise ValueError('Unexpected satellite')
        variable=next((name for name in ('LVT','LVM') if name in ds.variables),None)
        if variable is None:
            raise ValueError('LAP profile variable missing')
        projection=ds['goes_imager_projection']
        crs=CRS.from_cf({name:projection.getncattr(name) for name in projection.ncattrs()})
        x,y=Transformer.from_crs(4326,crs,always_xy=True).transform(lon,lat)
        height=projection.perspective_point_height
        xs=ds['x'][:]*height;ys=ds['y'][:]*height
        ix=int(round((x-xs[0])/(xs[1]-xs[0])));iy=int(round((y-ys[0])/(ys[1]-ys[0])))
        if not 0<=ix<len(xs) or not 0<=iy<len(ys):
            raise ValueError('Outside source grid')
        quality={name:int(ds[name][iy,ix]) if not np.ma.is_masked(ds[name][iy,ix]) else None
                 for name in ('DQF_Overall','DQF_Retrieval','DQF_SkinTemp')}
        for name,meaning in [('DQF_Overall','good_quality_qf'),('DQF_Retrieval','good_retrieval_qf'),('DQF_SkinTemp','good_first_guess_skin_temp_qf')]:
            if ds[name].flag_meanings.split()[0]!=meaning or int(ds[name].flag_values[0])!=0:
                raise ValueError('Unsupported LAP quality schema')
        good=all(value==0 for value in quality.values())
        values=np.ma.filled(ds[variable][iy,ix,:].astype(float),np.nan)
        if not good:
            values[:]=np.nan
        pressure=ds['pressure'][:]
        return {'product':variable,'units':ds[variable].units,'pressure_units':ds['pressure'].units,
                'start':ds.time_coverage_start,'end':ds.time_coverage_end,'satellite':'GOES-19',
                'quality':quality,'longitude':lon,'latitude':lat,'native_pixel':[iy,ix],
                'limitation':'Clear-sky retrieval; may incorporate NWP; no interpolation under clouds',
                'levels':[{'pressure':float(p),'value':float(v) if np.isfinite(v) else None} for p,v in zip(pressure,values)]}


@regional.scientific
def wind_vectors(path,reference,pressure_bounds=(100,1100)):
    """Native DMW vectors filtered by file and per-vector time, pressure and DQF."""
    from netCDF4 import num2date
    with Dataset(path) as ds:
        if getattr(ds,'platform_ID',None) not in ('G19','GOES-19'):
            raise ValueError('Unexpected satellite')
        finish=regional.parse(reference)
        if finish.tzinfo is None or regional.parse(ds.time_coverage_end)>finish:
            raise ValueError('Wind observation is later than replay reference')
        q=ds['DQF'];meanings=q.flag_meanings.split()
        if meanings[0]!='good_wind_qf' or int(q.flag_values[0])!=0:
            raise ValueError('Unknown DMW quality schema')
        arrays={name:np.ma.filled(ds[name][:].astype(float),np.nan) for name in
                ('lon','lat','pressure','wind_speed','wind_direction','DQF')}
        dates=num2date(ds['time'][:],ds['time'].units,only_use_cftime_datetimes=False)
        w,s,e,n=regional.bounds();features=[]
        for i in range(len(arrays['lon'])):
            if not all(np.isfinite(values[i]) for values in arrays.values()):
                continue
            if arrays['DQF'][i]!=0 or not pressure_bounds[0]<=arrays['pressure'][i]<=pressure_bounds[1]:
                continue
            if not w<=arrays['lon'][i]<=e or not s<=arrays['lat'][i]<=n:
                continue
            observed=dates[i].replace(tzinfo=regional.UTC)
            if observed>finish:
                continue
            features.append({'type':'Feature','id':i,'geometry':{'type':'Point','coordinates':[arrays['lon'][i],arrays['lat'][i]]},
                             'properties':{'pressure':arrays['pressure'][i],'pressure_units':ds['pressure'].units,
                             'speed':arrays['wind_speed'][i],'speed_units':ds['wind_speed'].units,
                             'direction':arrays['wind_direction'][i],'direction_units':ds['wind_direction'].units,
                             'quality':0,'observed':regional.stamp(observed),'channel':int(ds['band_id'][...].item())}})
        return {'type':'FeatureCollection','features':features,'start':ds.time_coverage_start,'end':ds.time_coverage_end,
                'satellite':'GOES-19','limitation':'Atmospheric motion vectors at retrieved pressure; not surface wind or cell trajectory'}
