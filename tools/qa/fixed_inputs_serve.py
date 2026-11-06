"""Run only the isolated fixed-input frontend QA backend."""
import os
from pathlib import Path

root=Path('.cache/qa/fixed-parameters-2026-11-01/browser').resolve()
root.mkdir(parents=True,exist_ok=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                   ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
    os.environ['GENTACTIX_'+key]=str(root/suffix)
from backend import main,harness_engine
import uvicorn

try:uvicorn.run(main.app,host='127.0.0.1',port=19131,log_level='warning')
finally:harness_engine.close_harness()
