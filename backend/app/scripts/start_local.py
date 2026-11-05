"""Start the local server AND NOAA worker without changing Windows script policy."""
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys


def main():
    workspace=Path(__file__).resolve().parents[3]
    output=workspace/'output';output.mkdir(exist_ok=True)
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    def start(name,arguments):
        with (output/(name+'.log')).open('ab') as out,(output/(name+'-error.log')).open('ab') as error:
            process=subprocess.Popen([sys.executable,*arguments],cwd=workspace,stdout=out,stderr=error,creationflags=flags)
        (output/(name+'.pid')).write_text(str(process.pid))
        return process.pid
    with socket.socket() as connection:
        listening=connection.connect_ex(('127.0.0.1',8000))==0
    if not listening:
        start('stormtrack-server',['-m','uvicorn','backend.app.api.main:app','--host','127.0.0.1','--port','8000'])
    from backend.app.adapters.regional_satellite import root
    def active(lease):
        if not lease.exists():
            return False
        connection=sqlite3.connect(lease,timeout=.05)
        try:
            connection.execute('BEGIN EXCLUSIVE');connection.rollback()
            return False
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower():
                raise
            return True
        finally:
            connection.close()
    if not active(root()/'worker-lock.sqlite3'):
        for stream in ('abi','glm','context'):
            if not active(root()/f'worker-lock-{stream}.sqlite3'):
                start('stormtrack-collector-'+stream,['-m','backend.app.adapters.regional_satellite','--profile','basic','--stream',stream])
    print('StormTrack: http://127.0.0.1:8000 — servidor e coletor iniciados; logs em output/.')


if __name__=='__main__':
    main()
