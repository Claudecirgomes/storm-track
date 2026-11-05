from datetime import datetime, timezone
from unittest.mock import patch
import json

import numpy as np
import pytest
from backend.app.adapters import regional_satellite as regional


def test_thermal_mask_and_legend_agree():
    values=np.array([[-90.,-70.,-30.,-29.,np.nan,-34.,-38.]])
    colored=regional.thermal(values,True)
    assert colored[0,0,:3].tolist()==regional.COLORS[0]
    assert colored[0,1,:3].tolist()==regional.COLORS[regional.STOPS.index(-70)]
    assert colored[0,:,3].tolist()==[255,255,0,0,0,127,255]
    assert regional.thermal(values)[0,4,3]==0


def test_paginated_listing_year_transition():
    calls=[]
    def request(url,**kwargs):
        calls.append(url)
        if 'continuation-token' not in url:
            return b'<ListBucketResult><IsTruncated>true</IsTruncated><NextContinuationToken>page2</NextContinuationToken></ListBucketResult>'
        return b'<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>'
    with patch.object(regional,'_request_bytes',side_effect=request):
        assert regional.listing('ABI-L2-CMIPF',datetime(2026,1,1,0,10,tzinfo=timezone.utc),minutes=30,channel=13)==[]
    assert len(calls)==4
    assert any('2025%2F365%2F23' in url for url in calls)
    assert any('2026%2F001%2F00' in url for url in calls)


def test_replay_window_composite_ids_and_completeness(tmp_path):
    with patch.object(regional,'root',return_value=tmp_path):
        with regional.database() as db:
            for id,time in [('file1:1','2026-01-01T00:05:00Z'),('file2:1','2026-01-01T00:06:00Z'),('future:1','2026-01-01T00:10:01Z'),('past:1','2025-12-31T23:59:59Z')]:
                db.execute('INSERT OR IGNORE INTO flashes VALUES (?,?,?,?)',(id,time,-51.9,-23.4))
            db.execute('INSERT OR IGNORE INTO flashes VALUES (?,?,?,?)',('file1:1','2026-01-01T00:05:00Z',-51.9,-23.4))
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',('glm','2026-01-01T00:00:00Z','2026-01-01T00:10:00Z','2026-01-01T00:11:00Z','glm','{}'))
        data=regional.flashes('2026-01-01T00:10:00Z')
        assert data['count']==2
        assert data['state']=='complete'
        assert regional.flashes('2026-01-02T00:10:00Z')['state']=='unavailable'
        with pytest.raises(ValueError):
            regional.flashes('2026-01-01T00:10:00')


def test_netcdf_scaled_kelvin_quality_and_projection(tmp_path):
    from netCDF4 import Dataset
    path=tmp_path/'test.nc'
    with Dataset(path,'w') as ds:
        ds.createDimension('x',3); ds.createDimension('y',3)
        x=ds.createVariable('x','f8',('x',));x[:]=[-.01,0,.01]
        y=ds.createVariable('y','f8',('y',));y[:]=[.01,0,-.01]
        p=ds.createVariable('goes_imager_projection','i4')
        p.grid_mapping_name='geostationary';p.perspective_point_height=35786023.
        p.longitude_of_projection_origin=-75.2;p.latitude_of_projection_origin=0.
        p.semi_major_axis=6378137.;p.semi_minor_axis=6356752.31414;p.sweep_angle_axis='x'
        c=ds.createVariable('CMI','i2',('y','x'),fill_value=-1)
        c.units='K';c.scale_factor=.01;c.add_offset=200.
        c[:]=np.full((3,3),273.15)
        q=ds.createVariable('DQF','u1',('y','x'));q[:]=0;q[1,2]=1
        ds.time_coverage_start='2026-01-01T00:00:00Z';ds.time_coverage_end='2026-01-01T00:10:00Z'
    with patch.object(regional,'grid',return_value=(np.array([[-75.2]]),np.array([[0.]]))):
        values,meta=regional.read_channel(path)
    assert abs(values[0,0])<.011
    assert meta['units']=='K'


def test_stale_catalog_preserves_frame(tmp_path):
    with patch.object(regional,'root',return_value=tmp_path):
        with regional.database() as db:
            meta={'id':'test','start':'2020-01-01T00:00:00Z','end':'2020-01-01T00:10:00Z'}
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',('abi',meta['start'],meta['end'],meta['end'],'abi',json.dumps(meta)))
        assert regional.catalog()['frames'][0]['state']=='delayed'


def test_reference_display_keeps_values_and_transparency():
    values=np.array([[20.,15.,0.,-15.,np.nan]])
    original=values.copy()
    result=regional.reference_clouds(values)
    assert result[0,:,3].tolist()==[0,0,127,255,0]
    np.testing.assert_array_equal(values,original)


def test_latest_c13_is_published_before_optional_rgb(tmp_path):
    item=('new-C13.nc',10,'2026-11-05T20:20:00Z')
    def listing(*args,**kwargs):
        if kwargs.get('channel')==13:
            return [('old-C13.nc',10,'2026-11-05T20:10:00Z'),item]
        with regional.database() as check:
            assert check.execute("SELECT key FROM objects WHERE kind='abi'").fetchone()[0]==item[0]
        raise RuntimeError('Visible source is unavailable')
    source=tmp_path/'source.nc';source.write_bytes(b'source')
    metadata={'start':'2026-11-05T20:20:00Z','end':'2026-11-05T20:29:00Z','units':'K','valid_fraction':1}
    with patch.object(regional,'root',return_value=tmp_path),patch.object(regional,'listing',side_effect=listing),patch.object(regional,'download',return_value=source) as downloads,patch.object(regional,'read_channel',return_value=(np.array([[-60.]]),metadata)),patch.dict('os.environ',{'STORMTRACK_SATELLITE_COLLECT_RGB':'true','STORMTRACK_SATELLITE_PROFILE':'basic','STORMTRACK_ABI_BATCH_SIZE':'1'}):
        with regional.database() as db:
            regional.abi(db,datetime(2026,11,5,20,30,tzinfo=timezone.utc))
            rows=db.execute("SELECT metadata FROM objects WHERE kind='abi'").fetchall()
        assert len(rows)==1
        assert 'Visible source' in json.loads(rows[0][0])['composite_error']
        assert downloads.call_count==1
