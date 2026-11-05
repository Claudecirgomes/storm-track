"""Local reference contract for immutable satellite artifacts over HTTPS.

No upload runs automatically. Remote durable storage must be configured separately.
Raw NOAA archives and credentials never enter this publication bundle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from backend.app.adapters.goes_layers import file_hash, scene_metadata, VERSION
from backend.app.adapters import regional_satellite as regional

MAX_BYTES=64*1024**2


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def build(scene,output):
    meta=scene_metadata(scene)
    files=sorted(path for path in regional.root().glob(scene+'*') if path.suffix in ('.png','.npz','.json'))
    if not files or sum(path.stat().st_size for path in files)>MAX_BYTES:
        raise ValueError('No artifacts or publication quota exceeded')
    manifest={'schema_version':VERSION,'scene_id':scene,'observation':meta,
              'files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':file_hash(p)} for p in files]}
    manifest['revision']=hashlib.sha256(canonical(manifest)).hexdigest()
    output=Path(output)
    if output.exists():
        raise ValueError('Bundle already exists')
    temporary=output.with_suffix('.part')
    with ZipFile(temporary,'w',ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file,file.name)
        archive.writestr('manifest.json',canonical(manifest))
    temporary.replace(output)
    return manifest


def receive(bundle,destination):
    """Testable local receiver: verify, persist, then announce manifest revision."""
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with ZipFile(bundle) as archive:
        infos=archive.infolist()
        if len(infos)>128 or sum(info.file_size for info in infos)>MAX_BYTES:
            raise ValueError('Bundle exceeds receiver quota')
        if len({info.filename for info in infos})!=len(infos):
            raise ValueError('Duplicate archive entry')
        manifest=json.loads(archive.read('manifest.json'))
        revision=manifest.pop('revision')
        if hashlib.sha256(canonical(manifest)).hexdigest()!=revision:
            raise ValueError('Manifest revision mismatch')
        manifest['revision']=revision
        scene=manifest['scene_id']
        if not re.fullmatch('[a-f0-9]{24}',scene):
            raise ValueError('Invalid scene ID')
        names={entry['name'] for entry in manifest['files']}
        if names|{'manifest.json'}!={info.filename for info in infos}:
            raise ValueError('Manifest and bundle disagree')
        for entry in manifest['files']:
            name=entry['name']
            if not re.fullmatch(re.escape(scene)+r'(?:-[a-z0-9-]+)?\.(png|npz|json)',name):
                raise ValueError('Unsafe artifact path')
            info=archive.getinfo(name)
            if info.file_size!=entry['bytes']:
                raise ValueError('Artifact size mismatch')
            if hashlib.sha256(archive.read(name)).hexdigest()!=entry['sha256']:
                raise ValueError('Artifact digest mismatch')
        target=destination/(scene+'-'+revision)
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=destination) as temp:
                stage=Path(temp)/'scene';stage.mkdir()
                for entry in manifest['files']:
                    (stage/entry['name']).write_bytes(archive.read(entry['name']))
                (stage/'manifest.json').write_bytes(canonical(manifest))
                stage.replace(target)
    return {'persisted':True,'scene_id':scene,'revision':revision,'manifest':str(target/'manifest.json')}


def publish(bundle,url,machine_token):
    import httpx
    from urllib.parse import urlparse
    if urlparse(url).scheme!='https' or len(machine_token)<32:
        raise ValueError('HTTPS endpoint and restricted machine token of at least 32 characters required')
    # The receiver must enforce the same byte/digest contract on durable storage.
    with Path(bundle).open('rb') as stream:
        response=httpx.post(url,headers={'Authorization':'Bearer '+machine_token},
                            files={'bundle':('scene.zip',stream,'application/zip')},timeout=60)
    response.raise_for_status()
    acknowledgement=response.json()
    with ZipFile(bundle) as archive:
        expected=json.loads(archive.read('manifest.json'))
    if acknowledgement.get('persisted') is not True or acknowledgement.get('revision')!=expected['revision'] or acknowledgement.get('scene_id')!=expected['scene_id']:
        raise ValueError('Remote receiver did not acknowledge the persisted scene revision')
    return acknowledgement


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(build(args.scene,args.output)))
