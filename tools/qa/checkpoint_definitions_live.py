"""Isolated import/export and continuation over a normal branch of real T6."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import urllib.request

ROOT=Path('.cache/qa/checkpoint-definitions-2026-11-03')


def save(path,value):
    if path.exists():raise ValueError('Preserve previous evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def request(base,path,body=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),
                              headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=90))


def seed():
    base='http://127.0.0.1:19257/api/sessions/';sid='e5cf86bd092f'
    before=request(base,sid+'/export')['session'];assert before['turn_count']==6
    assert not request(base,sid+'/progress')['active']
    view=request(base,sid+'/commands')
    value=request(base,sid+'/commands/open-branch',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version']))
    session=request(base,value['session_id']+'/export')['session']
    assert session['war_state']==before['war_state'] and not session['command_state']['agent_sessions']
    assert request(base,sid+'/export')['session']==before
    folder=ROOT/'source-api/sessions';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(session['id']+'.json');save(path,dict(format='gentactix-session-v1',session=session))
    save(ROOT/'seed-original.json',session)
    save(ROOT/'seed-file.json',dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),mtime_ns=path.stat().st_mtime_ns))
    info=dict(session_id=session['id'],source_api='http://127.0.0.1:19267',target_api='http://127.0.0.1:19268',ui='http://127.0.0.1:19269')
    save(ROOT/'case.json',info);print('Seeded normal fresh-role T6 branch',session['id'],flush=True)


def serve(side):
    folder=(ROOT/(side+'-api')).resolve();folder.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    from backend import main,harness_engine as h,runtime_bridge
    import uvicorn
    def dispatch(context,payload):
        before=copy.deepcopy(context['session']['war_state']);result=main._native_tool_dispatch(context,payload)
        assert context['session']['war_state']==before
        with (ROOT/(side+'-public-tools.jsonl')).open('a') as stream:
            stream.write(json.dumps(dict(tool=payload['tool'],args=payload.get('args'),response=result),ensure_ascii=False)+'\n')
        return result
    runtime_bridge.register_dispatcher(dispatch)
    try:uvicorn.run(main.app,host='127.0.0.1',port=19267 if side=='source' else 19268,log_level='warning')
    finally:h.close_harness()


def verify_import():
    from backend import checkpoint_codec as c,session_store,afsim_state
    from gentactix import commands,missions
    info=json.loads((ROOT/'case.json').read_text());sid=info['session_id']
    source=request(info['source_api'],'/api/sessions/'+sid+'/export')['session']
    target=request(info['target_api'],'/api/sessions/'+sid+'/export')['session']
    assert json.dumps(source,sort_keys=True)==json.dumps(target,sort_keys=True)
    source_path=ROOT/'source-api/sessions'/(sid+'.json');target_path=ROOT/'target-api/sessions'/(sid+'.json')
    before=json.loads((ROOT/'seed-file.json').read_text())
    assert hashlib.sha256(source_path.read_bytes()).hexdigest()==before['sha256']
    assert source_path.stat().st_mtime_ns==before['mtime_ns']
    packed=json.loads(target_path.read_text());assert packed['format']==c.V2
    assert json.dumps(c.decode(packed),sort_keys=True)==json.dumps(session_store.serializable(target),sort_keys=True)
    assert commands.world_version(source)==commands.world_version(target)
    rows=[];offset=0
    while True:
        data=afsim_state.observation(target,dict(limit=16,offset=offset,detail=True));rows+=data['units'];offset=data['next_offset']
        if offset is None:break
    assert len(rows)==22
    assert {r['name'] for r in rows}=={u['name'] for _,u in missions.units(source['war_state'])}
    save(ROOT/'import-authoritative.json',target)
    save(ROOT/'import-review.json',dict(passed=True,source_v1_bytes_and_mtime_unchanged=True,
        target_v2_complete_typed_session_equal=True,world_and_command_hash_equal=True,all22_details_available=True,
        saved_native_settings_preserved=True,actual_model=False,physical_turn=False))
    save(ROOT/'turn-before-authoritative.json',target)
    folder=ROOT/'real-ui-t7';folder.mkdir()
    save(folder/'turn-case.json',dict(session_id=sid,turn=7,api=info['target_api'],ui=info['ui']))
    print('PASS complete typed import, source V1 unchanged, target V2, all22 details',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['seed','source','target','verify-import'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required')
    if args.mode=='seed':seed()
    elif args.mode=='verify-import':verify_import()
    else:serve(args.mode)
