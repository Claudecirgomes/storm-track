from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest

from backend.app.adapters import goes_layers as layers


def test_dependency_graph_and_subtraction_order():
    assert layers.dependencies('abi16')==(16,)
    assert layers.dependencies('night-microphysics')==(7,13,15)
    a=np.array([[280.,np.nan]]); b=np.array([[278.,279.]])
    result=layers.derive({13:a,15:b},'split-window')
    assert result[0,0]==2
    assert np.isnan(result[0,1])
    with pytest.raises(ValueError): layers.dependencies('../secrets')


def test_cold_palette_is_shared_and_no_data_transparent():
    data=np.array([layers.TOP_STOPS+[np.nan]],dtype=float)
    pixels=layers.tops(data)
    assert pixels[0,:-1,:3].tolist()==layers.TOP_COLORS
    assert pixels[0,-1,3]==0
    assert layers.tops(np.array([[-30.,-40.]]),True)[0,:,3].tolist()==[0,255]


def test_rgb_night_mask_and_intersection():
    fields={7:np.array([[280.,280.]]),13:np.array([[280.,np.nan]]),15:np.array([[280.,280.]])}
    with patch.object(layers,'solar_cosine',return_value=np.array([[-1.,1.]])):
        rgba=layers.render_rgb(fields,'night-microphysics',datetime.now(timezone.utc))
    assert rgba[0,0,3]==255
    assert rgba[0,1,3]==0
    # Zero differences and 280 K: independent hand-computed red component.
    assert rgba[0,0,0]==int(255*6.7/9.3)


def test_splits_block_events_hashes_and_nearby_frames():
    a={'scene_id':'a','event_id':'storm','split':'train','start':'2026-01-01T00:00:00Z'}
    b=dict(a,scene_id='b',split='test',start='2026-01-03T00:00:00Z')
    with pytest.raises(ValueError,match='Event'): layers.validate_splits([a,b])
    b.update(event_id='other',start='2026-01-01T00:10:00Z')
    with pytest.raises(ValueError,match='Temporal'): layers.validate_splits([a,b])
    b['start']='2026-01-03T00:00:00Z'
    layers.validate_splits([a,b])


def test_export_rejects_empty_real_interval_and_writes_failure_manifest(tmp_path):
    with patch.object(layers.regional,'listing',return_value=[]):
        with pytest.raises(ValueError,match='No real observations'):
            layers.export_session('2026-01-01T00:00:00Z','2026-01-01T00:10:00Z',tmp_path/'empty')
    import json
    assert json.loads((tmp_path/'empty/manifest.json').read_text())['samples']==[]


def test_glm_window_contract():
    with pytest.raises(ValueError): layers.regional.flashes('2026-01-01T00:00:00Z',2)


def test_causal_sequence_never_reuses_or_looks_ahead():
    from backend.app.analysis.research_samples import causal_sequence
    samples=[{'scene_id':str(i),'observation_start':f'2026-01-01T00:{i:02d}:00Z',
              'observation_end':f'2026-01-01T00:{i+9:02d}:00Z','state':'usable'} for i in (0,10,20,30)]
    result=causal_sequence(samples,'2026-01-01T00:30:00Z')
    assert result['state']=='incomplete'  # t scan has not completed at reference time.
    result=causal_sequence(samples,'2026-01-01T00:39:00Z',tolerance_seconds=600)
    assert result['state']=='complete'
    assert len({s['scene_id'] for s in result['samples']})==4


def test_eulerian_rate_uses_elapsed_time_and_common_mask():
    from backend.app.analysis.research_samples import eulerian_change, patches
    grid=[0,2,0,100,0,-2]
    result=eulerian_change(np.array([[280.,np.nan]]),np.array([[274.,280.]]),
        '2026-01-01T00:00:00Z','2026-01-01T00:12:00Z',grid,grid)
    assert result['rate_K_per_minute'][0,0]==-.5
    assert np.isnan(result['rate_K_per_minute'][0,1])
    crop=list(patches(np.zeros((4,4)),grid,size=2))[-1]
    assert crop['transform']==[4,2,0,96,0,-2]


def test_no_fabricated_annotations():
    from backend.app.analysis.research_samples import coco_template, validate_coco
    empty=coco_template([])
    assert empty['annotations']==[]
    assert validate_coco(empty)==empty


def test_l2_unknown_quality_fails_closed(tmp_path):
    from netCDF4 import Dataset
    from backend.app.adapters.goes_products import read
    file=tmp_path/'unknown.nc'
    with Dataset(file,'w') as ds:
        ds.platform_ID='G19'
        ds.createDimension('x',1);ds.createDimension('y',1)
        ds.createVariable('ACM','u1',('y','x'))
        q=ds.createVariable('DQF','u1',('y','x'));q.flag_values=np.array([0],dtype='u1');q.flag_meanings='unknown'
    with pytest.raises(ValueError,match='DQF decoding'):
        read(file,'ACMF')


def test_artifact_receiver_publishes_only_verified_revision(tmp_path):
    from zipfile import ZipFile
    from backend.app.ingestion import satellite_artifacts as artifacts
    scene='a'*24
    cache=tmp_path/'cache';cache.mkdir()
    (cache/(scene+'.npz')).write_bytes(b'physical-values')
    with patch.object(artifacts,'scene_metadata',return_value={'start':'2026-01-01T00:00:00Z'}),patch.object(artifacts.regional,'root',return_value=cache):
        manifest=artifacts.build(scene,tmp_path/'scene.zip')
    receipt=artifacts.receive(tmp_path/'scene.zip',tmp_path/'receiver')
    assert receipt['persisted'] and receipt['revision']==manifest['revision']
    assert artifacts.receive(tmp_path/'scene.zip',tmp_path/'receiver')==receipt
    with ZipFile(tmp_path/'scene.zip') as source,ZipFile(tmp_path/'corrupt.zip','w') as corrupt:
        corrupt.writestr('manifest.json',source.read('manifest.json'))
        corrupt.writestr(scene+'.npz',b'bad-data')
    with pytest.raises(ValueError,match='size mismatch'):
        artifacts.receive(tmp_path/'corrupt.zip',tmp_path/'rejected')
    assert list((tmp_path/'rejected').iterdir())==[]


def test_wind_memory_cache_cannot_supply_future_scan_to_replay(tmp_path):
    import time
    from types import SimpleNamespace
    from backend.app.adapters import monitor_feeds
    cached={'type':'FeatureCollection','features':[],'end':'2026-01-01T00:10:50Z','state':'available'}
    with patch.dict(monitor_feeds.MEMORY,{'2026-01-01T00:10:00+00:00':(time.monotonic(),cached)},clear=True),patch.object(monitor_feeds.regional,'root',return_value=tmp_path),patch.object(monitor_feeds.regional,'get_settings',return_value=SimpleNamespace(serverless=False)),patch.object(monitor_feeds.regional,'catalog',return_value={'enabled':True}),patch.object(monitor_feeds.regional,'listing',return_value=[]):
        assert monitor_feeds.winds('2026-01-01T00:10:05Z')['state']=='unavailable'
