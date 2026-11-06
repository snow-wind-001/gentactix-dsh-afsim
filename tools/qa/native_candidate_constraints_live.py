"""Owned normal branch and real Native server; explicit --live only."""
import argparse
import copy
import json
import os
from pathlib import Path
import urllib.request

ROOT=Path('.cache/qa/candidate-constraints-2026-11-03')


def save(path,value):
    if path.exists():raise ValueError('Preserve previous evidence: '+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def get(api,path,body=None):
    req=urllib.request.Request(api+path,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as response:return json.load(response)


def seed(api='http://127.0.0.1:19268',sid='b5c7d72fc507',*,turn=8,port=19278,ui='http://127.0.0.1:19269'):
    path='/api/sessions/'+sid
    assert not get(api,path+'/progress')['active']
    before=get(api,path+'/export')['session'];assert before['turn_count']==turn-1
    view=get(api,path+'/commands')
    branch=get(api,path+'/commands/open-branch',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version']))
    current=get(api,'/api/sessions/'+branch['session_id']+'/export')['session']
    assert current['war_state']==before['war_state'] and not current['command_state']['agent_sessions']
    assert get(api,path+'/export')['session']==before
    save(ROOT/f'source-original-t{turn-1}.json',before);save(ROOT/'turn-before-authoritative.json',current)
    os.environ['GENTACTIX_SESSION_DIR']=str((ROOT/'api/sessions').resolve())
    from backend import session_store
    session_store.validate(current);session_store.save(current)
    info=dict(session_id=current['id'],turn=turn,api=f'http://127.0.0.1:{port}',ui=ui)
    save(ROOT/f'real-ui-t{turn}/turn-case.json',info);print('Seeded actual normal branch for T'+str(turn),current['id'],flush=True)


def serve(port=19278):
    folder=(ROOT/'api').resolve()
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    from backend import main,harness_engine as h,runtime_bridge
    import uvicorn
    def dispatch(context,payload):
        # Scenario configuration tools own a draft, not a running session.
        # Retain the world invariant whenever a battle context is present.
        session=context.get('session')
        before=copy.deepcopy(session['war_state']) if session is not None else None
        result=main._native_tool_dispatch(context,payload)
        if session is not None:assert session['war_state']==before
        with (ROOT/'public-tools.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(tool=payload['tool'],args=payload.get('args'),response=result),ensure_ascii=False)+'\n')
        return result
    runtime_bridge.register_dispatcher(dispatch)
    try:uvicorn.run(main.app,host='127.0.0.1',port=port,log_level='warning')
    finally:h.close_harness()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['seed','serve']);parser.add_argument('--live',action='store_true')
    parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--port',type=int,default=19278)
    parser.add_argument('--source-api',default='http://127.0.0.1:19268');parser.add_argument('--source-session',default='b5c7d72fc507')
    parser.add_argument('--turn',type=int,default=8);parser.add_argument('--ui',default='http://127.0.0.1:19269');args=parser.parse_args()
    if not args.live:parser.error('--live required')
    if not 18000<=args.port<=19999 or args.turn<1:parser.error('Owned isolated port and positive attempted turn required')
    ROOT=args.root
    seed(args.source_api,args.source_session,turn=args.turn,port=args.port,ui=args.ui) if args.mode=='seed' else serve(args.port)
