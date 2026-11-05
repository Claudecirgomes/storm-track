"""Bounded real-file inventory for product-specific L2 adapter validation."""
import json
from pathlib import Path

from backend.app.adapters import regional_satellite as regional
from backend.app.adapters.goes_products import inspect, read, VARIABLES


def main():
    report=json.loads(Path('output/goes-inventory.json').read_text())
    directory=Path('output/goes-l2-inspection');directory.mkdir(exist_ok=True)
    results=[]
    for entry in report['products']:
        code=entry['product'].removeprefix('ABI-L2-')
        if code not in {*VARIABLES,'LVTPF','LVMPF','DMWF','DMWVF'} or not entry.get('sample'):
            continue
        item=entry['sample']
        record={'product':code,'source_key':item[0]}
        try:
            if item[1]>64*1024**2:
                raise ValueError('Source exceeds bounded inspection budget')
            import hashlib
            path=directory/(hashlib.sha256(item[0].encode()).hexdigest()+'.nc')
            if not path.exists():
                regional.download(item,directory)
            record['metadata']=inspect(path)
            try:
                if code not in VARIABLES:
                    raise ValueError('Dedicated profile/vector reader required; native variables inspected')
                values,meta=read(path,code)
                record.update(adapter='real_read_passed',decoded=meta)
            except Exception as exc:
                record.update(adapter='blocked',error=str(exc))
        except Exception as exc:
            record.update(adapter='source_blocked',error=str(exc))
        results.append(record)
        Path('output/goes-products-real.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps([{r['product']:r['adapter']} for r in results]))


if __name__=='__main__':
    main()
