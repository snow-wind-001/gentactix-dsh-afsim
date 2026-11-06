"""Opt-in normal HTTP branches over copies of actually damaged QA games."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import uuid

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/branch-identity-2026-11-02')
SOURCE=Path('.cache/qa/formation-commit-2026-11-02')


def save(mode,name,value):
    p=ROOT/mode/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('Preserve existing evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def configure(mode):api.ROOT=ROOT/mode;api.PORT=19208 if mode=='afsim' else 19209


def seed(mode):
    sid=json.loads((SOURCE/mode/'source.json').read_text())['session_id']
    original=SOURCE/mode/'api/sessions'/(sid+'.json');target=ROOT/mode/'api/sessions'/original.name
    if not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(original.read_bytes())
        save(mode,'source.json',dict(path=str(original),sha256=hashlib.sha256(original.read_bytes()).hexdigest(),session_id=sid))
    return sid


def export(sid):return api.call('GET','/sessions/'+sid+'/export')['session']


def branch(sid):
    v=api.call('GET','/sessions/'+sid+'/commands')
    result=api.call('POST','/sessions/'+sid+'/commands/open-branch',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version']))
    return result['session_id']


def step(mode,sid,agent,point,label):
    base='/sessions/'+sid;before=export(sid);v=api.call('GET',base+'/commands')
    intent=('明确move到'+json.dumps(point,ensure_ascii=False)+'，duration=until_arrived；目标很近，本轮应实际发生移动。'
        if point else '本轮明确hold，不机动。')
    api.call('PUT',base+'/commands',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],
        control_team='red',director=True,no_fire=True,unit_agents=[agent],
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in v['units'] if u['available'] and u['id']!=agent],
        intent='分支软件验收：独立单位Agent'+intent+'其他单位人工待命。保留既有损伤；并非历史战果标定。'))
    v=api.call('GET',base+'/commands')
    result=api.call('POST',base+'/next',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],batch_id=uuid.uuid4().hex,
        instruction='执行已确认命令；独立单位Agent遵循全局意图。'+intent))
    after=export(sid);decisions=[d for d in after['trajectory'][-1]['decisions'] if d.get('source')=='native_unit_agent']
    assert len(decisions)==1 and decisions[0]['unit_id']==agent
    assert decisions[0]['action']==('move' if point else 'hold'),decisions
    assert after['turn_count']==before['turn_count']+1
    assert after['formation_commits']==before['formation_commits']
    assert after['command_state']['formation_handoffs']==before['command_state']['formation_handoffs']
    old={u['name']:u for t in ('red','blue') for u in before['war_state'][t+'_units']}
    for t in ('red','blue'):
        for u in after['war_state'][t+'_units']:
            assert u['personnel']==old[u['name']]['personnel']
    receipt=next(r for r in after['command_state']['receipts'] if r['turn']==after['turn_count'] and r['unit_id']==agent)
    if point:assert receipt['before_position']!=receipt['after_position'],receipt
    save(mode,label+'.json',dict(before=before,after=after,decision=decisions[0],receipt=receipt,engine_meta=result['engine_meta']))
    print('PASS actual',mode,label,'turn',after['turn_count'],'action',decisions[0]['action'],flush=True)
    return after


def run(mode):
    sid=seed(mode);source=export(sid);source_file=(ROOT/mode/'api/sessions'/(sid+'.json')).read_bytes()
    child=branch(sid);b=export(child)
    assert b['war_state']==source['war_state'] and b['formation_commits']==source['formation_commits']
    assert b['command_state']['agent_sessions']=={} and b['command_state']['batches']=={}
    assert export(sid)==source and (ROOT/mode/'api/sessions'/(sid+'.json')).read_bytes()==source_file
    v=api.call('GET','/sessions/'+child+'/commands')
    unit=next(u for u in b['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')
    agent=next(r['id'] for r in v['units'] if r['name']==unit['name'])
    point=dict(lat=unit['lat'],lng=unit['lng']+.0005)
    after=step(mode,child,agent,point,'move')
    binding=after['command_state']['agent_sessions'][agent]
    assert binding['session_id'].startswith(f'gentactix-unit-{child}-e{b["role_epoch"]}-{agent}-')
    assert binding['session_id'] not in {v['session_id'] for v in source['command_state'].get('agent_sessions',{}).values()}
    assert 'parent_session_id' not in binding
    save(mode,'expected-cold.json',after)
    save(mode,'case.json',dict(passed=True,source_session=sid,session_id=child,agent=agent,binding=binding,
        source_world_preserved=True,source_checkpoint_preserved=True,actual_move=True,
        scope='Native branch decision and actual backend movement on synthetic damaged state; not full historical acceptance'))


def cold(mode,resume=False):
    case=json.loads((ROOT/mode/'case.json').read_text());sid=case['session_id']
    expected=json.loads((ROOT/mode/'expected-cold.json').read_text());assert export(sid)==expected
    save(mode,'cold-review.json',dict(passed=True,entire_session_exact=True,pid=api.call('GET','/health')['build']['pid']))
    if resume:
        after=step(mode,sid,case['agent'],None,'resumed')
        assert after['command_state']['agent_sessions'][case['agent']]['session_id']==case['binding']['session_id']
        save(mode,'resume-review.json',dict(passed=True,same_native_session=True,turn=after['turn_count']))
    print('PASS cold',mode,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','run','cold','resume'])
    p.add_argument('--backend',choices=['afsim','narrative'],required=True);p.add_argument('--live',action='store_true');a=p.parse_args()
    configure(a.backend)
    if a.mode in ('run','resume') and not a.live:p.error('Actual model calls require --live')
    if a.mode=='serve':seed(a.backend);api.serve()
    elif a.mode=='run':run(a.backend)
    else:cold(a.backend,a.mode=='resume')


if __name__=='__main__':main()
