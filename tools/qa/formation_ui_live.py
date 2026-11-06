"""Isolated normal APIs for the runtime conversion UI; old actual T1 copies."""
import argparse
import json
from pathlib import Path
import time
import urllib.error

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/formation-ui-2026-11-02');api.ROOT=ROOT;api.PORT=19214


def save(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('Preserve existing evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def setup():
    for attempt in range(30):
        try:api.call('GET','/health');break
        except urllib.error.URLError:
            if attempt==29:raise
            time.sleep(.25)
    cases={}
    for engine in ('afsim','narrative'):
        old=Path('.cache/qa/converted-phases-2026-11-02')/engine/'turn-1.json'
        source=json.loads(old.read_text())['after']
        sid=source['id']
        if not (ROOT/'api/sessions'/f'{sid}.json').exists():
            sid=api.call('POST','/sessions/import',dict(format='gentactix-session-v1',session=source))['session_id']
        base='/sessions/'+sid;v=api.call('GET',base+'/commands')
        existing=[json.loads(p.read_text())['session']['id'] for p in (ROOT/'api/sessions').glob('*.json')
            if json.loads(p.read_text())['session'].get('branch_origin',{}).get('session_id')==sid]
        assert len(existing)<=1
        bid=existing[0] if existing else api.call('POST',base+'/commands/open-branch',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version']))['session_id']
        snapshot=api.call('GET','/sessions/'+bid)
        assert snapshot['settings']['execution_backend']==engine and snapshot['war_state']==source['war_state']
        cases[engine]=dict(session_id=bid,source_id=sid,source_hash=api.digest(source['war_state']),
            root_name='第159师',turn=1,scope='Copied actual damage with fixed estimated QA inputs; no configuration-generation or historical-calibration claim')
        save(engine+'/before.json',api.call('GET','/sessions/'+bid+'/export')['session'])
    save('cases.json',cases);print('Prepared isolated two-backend UI branches',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('serve','setup'));a=p.parse_args()
    if a.mode=='serve':api.serve()
    else:setup()
