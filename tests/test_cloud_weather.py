from contextlib import contextmanager
from unittest.mock import patch

import pytest

from backend.app.adapters import cloud_weather as cloud
from backend.app.adapters import regional_satellite as regional
from backend.app.ingestion import satellite_queue as queue


def test_cloud_glm_overlaps_count_once_and_incomplete_is_not_zero_activity():
    class Database:
        def execute(self, query, params):
            if 'FROM flashes' in query:
                return []
            return [
                {'observed':'2026-11-05T20:00:00Z','end':'2026-11-05T20:03:00Z'},
                {'observed':'2026-11-05T20:02:00Z','end':'2026-11-05T20:04:00Z'},
            ]
    @contextmanager
    def connection():
        yield Database()
    with patch.object(cloud,'connection',connection):
        result=cloud.flashes('2026-11-05T20:10:00Z',10)
    assert result['coverage_fraction']==.4
    assert result['state']=='partial'
    assert result['rate_flashes_per_minute'] is None


@pytest.mark.parametrize('name',['../secret.png','x.png','a'*24+'.json/secret'])
def test_asset_path_rejected_before_database_access(name):
    with patch.object(cloud,'connection') as connect:
        with pytest.raises(ValueError):cloud.asset(name)
        connect.assert_not_called()


def test_remote_receipt_prevents_redownload_after_asset_retention(tmp_path):
    import sqlite3
    instant=regional.parse('2026-11-05T20:55:00Z')
    db=sqlite3.connect(tmp_path/'queue.sqlite3')
    db.execute('CREATE TABLE objects(key TEXT PRIMARY KEY)')
    items=[('already-processed.nc',1,'2026-11-05T20:50:00Z'),('new.nc',1,'2026-11-05T20:54:00Z')]
    queue.discover(db,'ABI-L2-CMIPF','abi',instant,lambda *a,**kw:items,
                   regional.parse,regional.stamp,13,completed_lookup=lambda keys:{keys[0]})
    assert [item[0] for item in queue.batch(db,'abi',instant,regional.stamp,10)]==['new.nc']
    db.close()
