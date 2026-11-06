"""Isolated normal API for campaign goal integration, never user persistence."""
import os
from pathlib import Path

ROOT=Path('.cache/qa/campaign-plan-2026-10-31/browser').resolve()
ROOT.mkdir(parents=True,exist_ok=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                   ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
    os.environ['GENTACTIX_'+key]=str(ROOT/suffix)
from backend import main,harness_engine
import uvicorn
try:
    uvicorn.run(main.app,host='127.0.0.1',port=19108,log_level='warning')
finally:
    harness_engine.close_harness()
