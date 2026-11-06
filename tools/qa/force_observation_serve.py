"""Isolated normal API for multi-level UI checks; keep user games untouched."""
import os
from pathlib import Path

ROOT=Path('.cache/qa/force-observation-2026-10-31/browser').resolve()
ROOT.mkdir(parents=True,exist_ok=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                   ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
    os.environ['GENTACTIX_'+key]=str(ROOT/suffix)

from backend import main,session_store
from tools.qa.large_formation_fixture import inputs
from gentactix import historical_operations as ho,reporting

sid='e'*12
if sid not in main._SESSIONS and not (ROOT/'sessions'/f'{sid}.json').exists():
    snapshot,parameters=inputs();world=ho.initial(snapshot,parameters)
    session=main._new_session('79单位指挥与短引用QA，数值非历史部署','30分钟',False,
        world['mission']['definition']['battle'],False,False)
    session.update(id=sid,war_state=world,turn_count=0,execution_backend='afsim',product_mode='historical',
        simulation_mode='open',mission_id=world['mission']['id'],historical_definition=world['mission']['definition'],
        history=[reporting.initial_status(world)])
    session_store.validate(session);session_store.save(session);main._SESSIONS[sid]=session

import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=19105,log_level='warning')
