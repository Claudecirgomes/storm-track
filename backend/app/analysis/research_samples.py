"""Causal research utilities: no tracking, inference or fabricated annotations."""
from datetime import timedelta
import numpy as np

from backend.app.adapters.regional_satellite import parse


def causal_sequence(samples, reference, offsets=(30,20,10,0), tolerance_seconds=90):
    reference=parse(reference)
    result=[];used=set()
    for minutes in offsets:
        target=reference-timedelta(minutes=minutes)
        candidates=[s for s in samples if s['scene_id'] not in used and
                    parse(s['observation_end'])<=reference and
                    abs((parse(s['observation_end'])-target).total_seconds())<=tolerance_seconds and
                    s.get('state')=='usable']
        if not candidates:
            return {'state':'incomplete','missing_offset_minutes':minutes,'samples':[]}
        chosen=min(candidates,key=lambda s:abs((parse(s['observation_end'])-target).total_seconds()))
        used.add(chosen['scene_id']);result.append(chosen)
    return {'state':'complete','samples':result,'reference':reference.isoformat()}


def eulerian_change(previous, current, previous_time, current_time, previous_transform, current_transform):
    elapsed=(parse(current_time)-parse(previous_time)).total_seconds()
    if elapsed<=0 or previous.shape!=current.shape or previous_transform!=current_transform:
        raise ValueError('Positive real delta-t and identical scientific grids required')
    delta=np.where(np.isfinite(previous)&np.isfinite(current),current-previous,np.nan)
    return {'difference_K':delta,'rate_K_per_minute':delta/(elapsed/60),
            'delta_t_seconds':elapsed,'method':'variação Euleriana no pixel; sem compensação de movimento'}


def patches(values, transform, size=256, stride=None):
    if size<1 or len(transform)!=6:
        raise ValueError('Positive patch size and affine transform required')
    stride=size if stride is None else stride
    if stride<1:
        raise ValueError('Positive stride required')
    h,w=values.shape[-2:]
    left,dx,rx,top,ry,dy=transform
    for row in range(0,h-size+1,stride):
        for col in range(0,w-size+1,stride):
            yield {'values':values[...,row:row+size,col:col+size], 'row':row,'column':col,
                   'transform':[left+col*dx+row*rx,dx,rx,top+col*ry+row*dy,ry,dy]}


def coco_template(samples):
    """Empty human-annotation exchange, never labels a cloud by threshold."""
    return {'info':{'annotation_state':'pending','label_policy':'human review; uncertainty required'},
            'categories':[{'id':1,'name':'candidato convectivo','supercategory':'curadoria'}],
            'images':[{'id':i+1,'file_name':s['file'],'width':s['shape'][1],'height':s['shape'][0],
                       'sample_id':s['sample_id'],'scene_id':s['scene_id'],'event_id':s.get('event_id'),
                       'affine_transform':s.get('transform'),'crs':s.get('crs')} for i,s in enumerate(samples)],
            'annotations':[]}


def validate_coco(document):
    images={im['id']:im for im in document['images']}
    categories={c['id'] for c in document['categories']}
    for ann in document['annotations']:
        if ann['image_id'] not in images or ann['category_id'] not in categories:
            raise ValueError('Annotation references unknown image/category')
        if ann.get('review_state') not in ('uncertain','reviewed') or not ann.get('annotator'):
            raise ValueError('Human annotations require reviewer identity and uncertainty/review state')
        if not ann.get('segmentation') and not ann.get('bbox'):
            raise ValueError('Annotation needs polygon/mask or bounding box')
    return document
