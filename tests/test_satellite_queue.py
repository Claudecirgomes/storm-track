from datetime import timedelta
import sqlite3
from unittest.mock import patch

import pytest

from backend.app.adapters import regional_satellite as regional
from backend.app.ingestion import satellite_queue as queue

T=regional.parse('2026-11-05T20:55:00Z')
ITEMS=[('old.nc',10,'2026-11-05T20:40:00Z'),('middle.nc',10,'2026-11-05T20:45:00Z'),('new.nc',10,'2026-11-05T20:50:00Z')]


def discover(db,items,instant=T):
    queue.discover(db,'ABI-L2-CMIPF','abi',instant,lambda *a,**kw:items,regional.parse,regional.stamp,13)


def test_all_updates_are_durable_and_oldest_cannot_starve(tmp_path):
    path=tmp_path/'queue.sqlite3'
    db=sqlite3.connect(path);db.execute('CREATE TABLE objects(key TEXT PRIMARY KEY)')
    discover(db,ITEMS)
    assert [item[0] for item in queue.batch(db,'abi',T,regional.stamp,2)]==['new.nc','old.nc']
    queue.completed(db,ITEMS[-1],T,regional.stamp,'digest')
    db.close()
    db=sqlite3.connect(path)
    assert {item[0] for item in queue.batch(db,'abi',T,regional.stamp,3)}=={'old.nc','middle.nc'}
    discover(db,ITEMS)
    assert db.execute('SELECT count(*) FROM satellite_queue').fetchone()[0]==3
    db.close()


def test_listing_failure_keeps_discovery_checkpoint(tmp_path):
    db=sqlite3.connect(tmp_path/'queue.sqlite3');db.execute('CREATE TABLE objects(key TEXT PRIMARY KEY)')
    discover(db,ITEMS)
    def unavailable(*args,**kwargs):
        raise TimeoutError('NOAA listing interrupted')
    with pytest.raises(TimeoutError):
        queue.discover(db,'ABI-L2-CMIPF','abi',T+timedelta(minutes=5),unavailable,regional.parse,regional.stamp,13)
    assert db.execute('SELECT checked FROM satellite_discovery').fetchone()[0]==regional.stamp(T)
    db.close()


def test_failed_download_does_not_block_other_updates(tmp_path):
    def process(db,item):
        if item[0]=='new.nc':
            raise TimeoutError('single failed file')
        db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',(item[0],item[2],item[2],regional.stamp(T),'abi','{}'));db.commit()
    with patch.object(regional,'root',return_value=tmp_path),patch.object(regional,'now',return_value=T),patch.object(regional,'listing',return_value=ITEMS):
        with regional.database() as db:
            with pytest.raises(RuntimeError):
                regional._run_source(db,T,'ABI-L2-CMIPF','abi',process,3,13)
            assert db.execute("SELECT count(*) FROM satellite_queue WHERE state='done'").fetchone()[0]==2
            assert queue.batch(db,'abi',T,regional.stamp,3)==[]
            assert queue.batch(db,'abi',T+timedelta(seconds=10),regional.stamp,3)[0][0]=='new.nc'


def test_new_revision_is_not_deduplicated_as_old_scan(tmp_path):
    db=sqlite3.connect(tmp_path/'queue.sqlite3');db.execute('CREATE TABLE objects(key TEXT PRIMARY KEY)')
    discover(db,[ITEMS[-1]])
    queue.completed(db,ITEMS[-1],T,regional.stamp)
    revision=('new_creation_revision.nc',11,ITEMS[-1][2])
    discover(db,[ITEMS[-1],revision])
    assert queue.batch(db,'abi',T,regional.stamp,3)==[revision]
    db.close()


def test_hourly_sweep_starts_at_collection_session_not_unbounded_history(tmp_path):
    db=sqlite3.connect(tmp_path/'queue.sqlite3');db.execute('CREATE TABLE objects(key TEXT PRIMARY KEY)')
    discover(db,[])
    seen=[]
    queue.discover(db,'ABI-L2-CMIPF','abi',T+timedelta(minutes=10),lambda *a,**kw:seen.append(kw['minutes']) or [],regional.parse,regional.stamp,13)
    assert seen==[41]  # Initial ABI 30 minutes plus ten since first discovery, inclusive.
    db.close()


def test_wind_discovery_includes_slower_product_publication(tmp_path):
    db=sqlite3.connect(tmp_path/'queue.sqlite3');db.execute('CREATE TABLE objects(key TEXT PRIMARY KEY)')
    seen=[]
    queue.discover(db,'ABI-L2-DMWF','wind',T,lambda *a,**kw:seen.append(kw['minutes']) or [],regional.parse,regional.stamp)
    assert seen==[121]
    db.close()
