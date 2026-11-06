"""Serve the normal unmocked API; keep generated QA games outside user storage."""
import os
import json
import time
from pathlib import Path

ROOT=Path('.cache/qa/synthetic-campaign-2026-10-31/browser').resolve()
ROOT.mkdir(parents=True,exist_ok=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                   ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
    os.environ['GENTACTIX_'+key]=str(ROOT/suffix)

from backend import main,harness_engine

_real_response=harness_engine.get_ai_response
def capture_response(*args,**kwargs):
    value=_real_response(*args,**kwargs)
    if isinstance(value,dict) and isinstance(value.get('unit_updates'),list):
        selected=[r for r in value['unit_updates'] if isinstance(r,dict) and '前端' in str(r.get('unit',''))]
        if selected:
            folder=ROOT.parent/'dsh';folder.mkdir(exist_ok=True)
            (folder/f'candidate-{time.time_ns()}.json').write_text(json.dumps({
                'unit_updates':selected,'resource_ledger':value.get('resource_ledger'),
                'orders':value.get('orders')},ensure_ascii=False,indent=2)+'\n')
    return value
harness_engine.get_ai_response=capture_response

import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=19103,log_level='warning')
