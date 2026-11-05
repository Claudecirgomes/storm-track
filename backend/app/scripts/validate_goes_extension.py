"""Offline reproducibility checks against retained real NOAA inputs."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from PIL import Image

from backend.app.adapters import goes_layers as layers
from backend.app.adapters import goes_products as products
from backend.app.adapters import regional_satellite as regional

REGIONS={'PR':(-54.7,-26.8,-48,-22.4),'SC':(-54,-29.5,-48,-25.8),
         'RS':(-58,-34,-49,-27),'Paraguay':(-63,-28,-54,-19),
         'Uruguay':(-59,-35,-53,-30),'Argentina norte/NE':(-68,-34,-53,-22)}


def validate(directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    evidence={'session':str(directory),'origin':manifest['origin'],'samples':[]}
    for sample in manifest['samples']:
        fields={}
        with Dataset(directory/sample['file']) as ds:
            for source in sample['sources']:
                path=directory/'sources'/source['source_file']
                assert layers.file_hash(path)==source['sha256']
                actual,meta=layers.physical(path,source['channel'])
                stored=np.ma.filled(ds[f"C{source['channel']:02d}"][:],np.nan)
                np.testing.assert_array_equal(actual,stored)
                assert meta['start']==source['start']
                fields[source['channel']]=actual
        lon,lat=regional.grid();coverage={}
        for region,(w,s,e,n) in REGIONS.items():
            roi=(lon>=w)&(lon<=e)&(lat>=s)&(lat<=n)
            assert roi.any()
            coverage[region]={str(c):float(np.isfinite(v[roi]).mean()) for c,v in fields.items()}
        for name in layers.RGB:
            if set(layers.dependencies(name))<=set(fields):
                Image.fromarray(layers.render_rgb(fields,name,regional.parse(sample['sources'][0]['start']))).save(directory/(sample['scene_id']+'-'+name+'.png'))
        evidence['samples'].append({'scene':sample['scene_id'],'reproduced':True,'coverage_bounding_boxes':coverage})
    return evidence


def main():
    began=time.perf_counter();cpu=time.process_time()
    sessions=['output/goes-research-real-day','output/goes-research-real-night']
    if Path('output/goes-research-real-visible-v2/manifest.json').exists():
        sessions.append('output/goes-research-real-visible-v2')
    if Path('output/goes-research-all16/manifest.json').exists():
        sessions.append('output/goes-research-all16')
    report={'sessions':[validate(directory) for directory in sessions]}
    path=next(Path('output/goes-l2-inspection').glob('*.nc'))
    dest=Path('output/goes-l2-inspection/cloud-mask.npz')
    report['ACMF']=json.loads(dest.with_suffix('.json').read_text()) if dest.exists() else products.export_file(path,'ACMF',dest)
    product_evidence=json.loads(Path('output/goes-products-real.json').read_text())
    report['products']=[]
    for entry in product_evidence:
        code=entry['product'];source=Path('output/goes-l2-inspection')/(hashlib.sha256(entry['source_key'].encode()).hexdigest()+'.nc')
        if code in ('LVTPF','LVMPF'):
            data=products.profile_point(source,-51.9,-23.4)
            output=source.parent/(code+'-profile.json')
            output.write_text(json.dumps(data,indent=2),encoding='utf-8')
            report['products'].append({'product':code,'kind':'profile','levels':len(data['levels']),'valid_values':sum(v['value'] is not None for v in data['levels'])})
        elif code in ('DMWF','DMWVF'):
            data=products.wind_vectors(source,'2026-11-05T20:00:00Z')
            (source.parent/(code+'-vectors.geojson')).write_text(json.dumps(data),encoding='utf-8')
            report['products'].append({'product':code,'kind':'vectors','count':len(data['features'])})
        elif entry['adapter']=='real_read_passed':
            for variable in products.VARIABLES[code]:
                output=source.parent/(code+'-'+variable+'.npz')
                metadata=json.loads(output.with_suffix('.json').read_text()) if output.exists() else products.export_file(source,code,output,variable)
                report['products'].append({'product':code,'variable':variable,'kind':'raster','units':metadata['units']})
    report['benchmark']={'wall_seconds':time.perf_counter()-began,'cpu_seconds':time.process_time()-cpu,'peak_ram_bytes':layers.peak_ram(),
                         'scope':'offline reproduction and render; no network'}
    Path('output/goes-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'reproduced_sessions':len(sessions),'l2':'ACMF decoded with enum quality and nearest sampling'}))


if __name__=='__main__':
    main()
