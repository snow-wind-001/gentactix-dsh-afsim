#!/usr/bin/env python3
"""Run the existing API and static gateway; keep all writable state in /data."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.umask(0o077)
DATA = Path('/data')
for folder in ('sessions', 'trajectories', 'config', 'cache', 'dsh-home', 'dsh-workspace',
               'afsim/state', 'afsim/workspace', 'afsim/wineprefix'):
    (DATA / folder).mkdir(parents=True, exist_ok=True)
(DATA / 'cache').chmod(0o700)

# Initialize a fresh, container-owned prefix; never mount a user's live prefix.
mission = Path('/app/vendor/afsim/local/afsim/runtime/afsim-2.9.0-win64/bin/mission.exe')
wine = Path('/app/vendor/afsim/local/afsim/compat/usr/lib/wine/wine64')
if mission.is_file() and wine.is_file():
    from tools.afsim.launch import prepare_runtime
    prepare_runtime()

# Read a supplied secret only at runtime. Its contents are never printed.
secret = os.environ.get('GENTACTIX_LLM_API_KEY_FILE')
if secret:
    os.environ['GENTACTIX_LLM_API_KEY'] = Path(secret).read_text().strip()

children = []
stopping = False

def stop(signum=None, frame=None):
    global stopping
    stopping = True
    for process in children:
        if process.poll() is None:
            process.terminate()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    children.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.main:app',
        '--host', '127.0.0.1', '--port', '8700', '--no-access-log']))
    children.append(subprocess.Popen(['nginx', '-c', '/app/docker/nginx.conf', '-g', 'daemon off;']))
    while not stopping:
        for process in children:
            code = process.poll()
            if code is not None:
                stop()
                raise SystemExit(code if code else 1)
        time.sleep(.25)
finally:
    stop()
    for process in children:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
