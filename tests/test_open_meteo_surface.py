import sqlite3
from unittest.mock import patch

import pytest

from backend.app.adapters import open_meteo_surface as model


def response(temp=24.6,speed=9.7,direction=282,time=1000):
    return {'latitude':-23.44,'longitude':-51.96,
            'current_units':{'temperature_2m':'°C','wind_speed_10m':'km/h','wind_direction_10m':'°'},
            'current':{'time':time,'temperature_2m':temp,'wind_speed_10m':speed,'wind_direction_10m':direction}}


def test_model_units_time_nulls_and_station_distinction():
    data=model.decode([response(),response(temp=None,speed=0,direction=None)],[(0,0),(-23.4205,-51.9386)],1000)
    assert data['data_kind']=='model_output'
    assert data['state']=='partial'
    assert data['features'][1]['properties']['temperature_2m'] is None
    assert data['features'][1]['properties']['wind_speed_10m']==0
    assert data['features'][1]['properties']['location_name']=='Maringá'
    assert data['features'][0]['properties']['location_name'] is None
    bad=response();bad['current_units']['wind_speed_10m']='m/s'
    with pytest.raises(model.SurfaceUnavailable,match='Unidades'):
        model.decode(bad,[(0,0)],1000)


def test_future_model_values_cannot_masquerade_as_current():
    with pytest.raises(model.SurfaceUnavailable,match='utilizáveis'):
        model.decode(response(time=2000),[(0,0)],1000)


def test_shared_cache_prevents_upstream_poll_per_tab(tmp_path):
    with patch.object(model,'directory',return_value=tmp_path),patch.object(model,'locations',return_value=[(-23.4205,-51.9386)]),patch.object(model,'download',return_value=response()) as fetch,patch.object(model.time,'time',return_value=1000):
        first=model.surface();second=model.surface()
        assert fetch.call_count==1
        assert second['features']==first['features']
    db=sqlite3.connect(tmp_path/'cache.sqlite3')
    assert db.execute("SELECT units FROM budget WHERE period LIKE 'day:%'").fetchone()[0]==1
    db.close()


def test_network_failure_preserves_old_model_and_backs_off(tmp_path):
    with patch.object(model,'directory',return_value=tmp_path),patch.object(model,'locations',return_value=[(0,0)]),patch.object(model,'download',return_value=response()),patch.object(model.time,'time',return_value=1000):
        model.surface()
    with patch.object(model,'directory',return_value=tmp_path),patch.object(model,'locations',return_value=[(0,0)]),patch.object(model,'download',side_effect=TimeoutError('network')) as fetch,patch.object(model.time,'time',return_value=2000):
        old=model.surface();again=model.surface()
        assert old['state']==again['state']=='delayed'
        assert old['features'][0]['properties']['temperature_2m']==24.6
        assert fetch.call_count==1


def test_coordinate_budget_and_region_guard(tmp_path):
    with patch.object(model,'directory',return_value=tmp_path):
        db=model.connect()
        model.reserve(db,1000,43)
        db.execute("UPDATE budget SET units=8000 WHERE period LIKE 'day:%'");db.commit()
        with pytest.raises(model.SurfaceUnavailable): model.reserve(db,1000,1)
        db.close()
        with pytest.raises(ValueError): model.point(60,-50)
        with pytest.raises(ValueError): model.point(float('nan'),-50)
