"""Opt-in normal HTTP conversion and execution on copied damaged QA games."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import uuid

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/formation-commit-2026-11-02')
SOURCE=Path('.cache/qa/formation-conversion-2026-11-02')


def save(backend,name,value):
    path=ROOT/backend/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('Preserve evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def seed(backend):
    case=json.loads((SOURCE/'equipped-afsim/case.json').read_text());sid=case['session_id']
    source=SOURCE/'api/sessions'/(sid+'.json');target=ROOT/backend/'api/sessions'/source.name
    if not target.exists():
        value=json.loads(source.read_text());value['session']['execution_backend']=backend
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(value,ensure_ascii=False)+'\n')
        save(backend,'source.json',dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),session_id=sid))
    return sid


def configure(backend):
    api.ROOT=ROOT/backend;api.PORT=19206 if backend=='afsim' else 19207


def convert(backend,url,kind,unit_ids,label):
    old=api.call('GET',url);commands=api.call('GET',url+'/commands');org=api.call('GET',url+'/force-organization')
    request=dict(expected_turn=commands['turn'],revision=commands['revision'],world_version=commands['world_version'],
        organization_revision=org['revision'],kind=kind,unit_ids=unit_ids,
        assumption='有损合成软件QA，经正常API提交；不是历史编制命令或逐场标定')
    if kind=='split':
        selected=next(u for u in old['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')
        n=selected['personnel']['committed'];request['allocations']=[dict(id='left',label='提交左',committed=n//2),dict(id='right',label='提交右',committed=n-n//2)]
    preview=api.call('POST',url+'/force-organization/conversion-preview',request)
    result=api.call('POST',url+'/force-organization/conversion-commit',{**request,'view_version':preview['view_version'],'commit_id':uuid.uuid4().hex})
    assert result['conversion_result']['runtime_admitted'] and not result['conversion_result']['physics_executed']
    after=api.call('GET',url)
    assert after['turn_count']==old['turn_count'] and after['history']==old['history']
    assert after['war_state']['simulation_clock']==old['war_state']['simulation_clock']
    from gentactix import formation_conversion
    for team in ('red','blue'):
        assert formation_conversion._totals(after['war_state'][team+'_units'])==formation_conversion._totals(old['war_state'][team+'_units'])
    save(backend,label+'/conversion.json',dict(before=old,preview=preview,result=result,after=after))
    print('PASS real HTTP',backend,label,'conversion atT',after['turn_count'],flush=True)
    return after


def step(backend,url,label):
    before=api.call('GET',url);view=api.call('GET',url+'/commands')
    api.call('PUT',url+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units'] if u['available']],
        control_team='red',director=True,no_fire=False,intent='软件连续性QA，双方待命，保留既有人员装备伤损'))
    view=api.call('GET',url+'/commands');started=time.monotonic()
    after=api.call('POST',url+'/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        batch_id=uuid.uuid4().hex,instruction='合成软件连续性QA，双方已明确待命；不得恢复旧人员装备，不得虚构交战或航空，不是历史过程验收。'))
    assert after['turn_count']==before['turn_count']+1
    assert after['war_state']['simulation_clock']['elapsed_seconds']==before['war_state']['simulation_clock']['elapsed_seconds']+1800
    old={u['name']:u for team in ('red','blue') for u in before['war_state'][team+'_units']}
    for team in ('red','blue'):
        for u in after['war_state'][team+'_units']:
            assert u['personnel']==old[u['name']]['personnel']
            for e,p in zip(u['equipment'],old[u['name']]['equipment']):
                assert all(e[k]==p[k] for k in ('category','committed','operational','damaged','destroyed'))
    if backend=='afsim':assert after['war_state']['afsim']['returncode']==0 and 'dsh_execution' not in after['war_state']
    else:assert after['war_state']['dsh_execution'] and 'afsim' not in after['war_state']
    save(backend,label+'/step.json',dict(before=before,after=after,seconds=time.monotonic()-started))
    print('PASS actual',backend,label,'T',after['turn_count'],flush=True)
    return after


def exercise(backend):
    sid=json.loads((ROOT/backend/'source.json').read_text())['session_id'];url='/sessions/'+sid
    before=api.call('GET',url);view=api.call('GET',url+'/commands')
    selected=next(u for u in before['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')
    uid=next(u['id'] for u in view['units'] if u['name']==selected['name'])
    convert(backend,url,'split',[uid],'split');step(backend,url,'split')
    view=api.call('GET',url+'/commands');world=api.call('GET',url)['war_state']
    names={u['name'] for u in world['red_units'] if u.get('runtime_allocation')}
    ids=[u['id'] for u in view['units'] if u['name'] in names]
    convert(backend,url,'merge',ids,'merge');after=step(backend,url,'merge')
    checkpoint=ROOT/backend/'api/sessions'/(sid+'.json');full=json.loads(checkpoint.read_text())['session']
    from backend import session_store
    session_store.validate(full);assert len(full['formation_commits'])==2
    source=json.loads((ROOT/backend/'source.json').read_text());assert hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()==source['sha256']
    save(backend,'expected-cold.json',full);save(backend,'review.json',dict(passed=True,source_checkpoint_unchanged=True,
        session_id=sid,final_turn=after['turn_count'],actual_steps=2,conversion_commits=2,
        scope='Normal HTTP durable split/merge and real backend frames on prior damaged synthetic QA; not historical or UI acceptance'))


def cold(backend):
    before=json.loads((ROOT/backend/'expected-cold.json').read_text());sid=before['id']
    exported=api.call('GET','/sessions/'+sid+'/export')['session']
    assert exported==before
    save(backend,'cold-review.json',dict(passed=True,session_id=sid,entire_session_exact=True,
        source='normal export after fresh server restore',pid=api.call('GET','/health')['build']['pid']))
    print('PASS fresh-process full session restore',backend,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['serve','exercise','cold'])
    parser.add_argument('--backend',choices=['afsim','narrative'],required=True);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    configure(args.backend)
    if args.mode=='serve':seed(args.backend);api.serve()
    elif args.mode=='exercise':
        if not args.live:parser.error('Actual backend steps require --live')
        exercise(args.backend)
    else:cold(args.backend)


if __name__=='__main__':main()
