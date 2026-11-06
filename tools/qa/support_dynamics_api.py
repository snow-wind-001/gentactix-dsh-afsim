"""Isolated UI/API review over a completed real native sustainment checkpoint."""
import argparse
import copy
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--checkpoint',type=Path);source.add_argument('--restore-session',type=Path)
    parser.add_argument('--port',type=int,default=18992)
    parser.add_argument('--root',type=Path,default=Path('.cache/qa/support-dynamics-ui/runtime'));args=parser.parse_args()
    root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import main as app,runtime_bridge,harness_engine as h
    from gentactix import missions
    import uvicorn
    runtime_bridge.register_dispatcher(app._native_tool_dispatch)
    if args.restore_session:
        from backend import session_store
        saved=json.loads(args.restore_session.read_text())
        assert saved['format']=='gentactix-session-v1'
        session=saved['session'];session_store.validate(session)
        session.update(adj_spec=None,active_observer=None,progress=None,cancel_requested=False)
    else:
        record=json.loads(args.checkpoint.read_text());w=record['after'];spec=w['mission']['definition'];missions.validate(w)
        session=app._new_session('时间保障实测检查点','30分钟',False,spec['battle'],False,False,persist_roles=False)
        session.update(war_state=copy.deepcopy(w),last_war_state=copy.deepcopy(record['before']),turn_count=w['mission']['turn'],
            execution_backend='afsim',product_mode='historical',simulation_mode='open',scenario_input='时间保障原生检查点，参数仅为QA假设',
            mission_id=spec['id'],historical_definition=copy.deepcopy(spec))
    app._SESSIONS[session['id']]=session
    (root/'session-id.json').write_text(json.dumps({'session_id':session['id'],'policy':{role:h.role_policy(role) for role in ('engine','chat')}}))
    print('QA session '+session['id'],flush=True)
    uvicorn.run(app.app,host='127.0.0.1',port=args.port,log_level='warning')


if __name__=='__main__':main()
