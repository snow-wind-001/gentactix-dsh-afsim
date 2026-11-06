"""Isolated real SDK server/branch for wall-clock recovery; no model stubs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

ROOT=Path('.cache/qa/operation-clock-2026-11-03')


def call(path,body=None):
    request=urllib.request.Request('http://127.0.0.1:19227/api'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(request,timeout=60))


def seed():
    expected=json.loads(Path('.cache/qa/native-effect-amendments-2026-11-03/seven-before-final-cold.json').read_text())
    current={}
    for sid,before in expected.items():
        assert not call('/sessions/'+sid+'/progress')['active']
        value=call('/sessions/'+sid+'/export')['session'];assert value==before,sid;current[sid]=value
    saved=ROOT/'original7-before.json';assert not saved.exists();saved.write_text(json.dumps(current,ensure_ascii=False))
    view=call('/sessions/d2c74153c82c/commands')
    branch=call('/sessions/d2c74153c82c/commands/open-branch',
        dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version']))
    sid=branch['session_id'];session=call('/sessions/'+sid+'/export')['session']
    assert session['turn_count']==4 and not session['command_state'].get('agent_sessions')
    folder=ROOT/'live-api/sessions';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(sid+'.json');assert not path.exists()
    path.write_text(json.dumps(dict(format='gentactix-session-v1',session=session),ensure_ascii=False))
    (ROOT/'live-case.json').write_text(json.dumps(dict(session_id=sid,source='d2c74153c82c',
        turn=4,api='http://127.0.0.1:19247',ui='http://127.0.0.1:19248'),indent=2))
    (ROOT/'live-before.json').write_text(json.dumps(session,ensure_ascii=False))
    print('Fresh normal branch seeded for independent SDK server',sid,flush=True)


def serve():
    folder=(ROOT/'live-api').resolve();folder.mkdir(parents=True,exist_ok=True)
    for name,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('ROLE_INDEX','roles.json'),
                        ('DSH_HOME','.dsh-wargame-home'),('DSH_WORKSPACE','workspace')]:
        os.environ['GENTACTIX_'+name]=str(folder/suffix)
    from backend import main,runtime_bridge,harness_engine
    import uvicorn
    def dispatch(context,payload):
        before=json.dumps(context['session']['war_state'],ensure_ascii=False,sort_keys=True)
        reply=main._native_tool_dispatch(context,payload)
        assert json.dumps(context['session']['war_state'],ensure_ascii=False,sort_keys=True)==before
        row=dict(tool=payload['tool'],args=payload.get('args'),response=reply,session_id=payload.get('session_id'))
        with (ROOT/'live-public-tools.jsonl').open('a') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        print('Native public tool',payload['tool'],'world unchanged',flush=True)
        return reply
    runtime_bridge.register_dispatcher(dispatch)
    try:uvicorn.run(main.app,host='127.0.0.1',port=19247,log_level='warning')
    finally:harness_engine.close_harness()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['seed','serve'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required')
    seed() if args.mode=='seed' else serve()


if __name__=='__main__':main()
