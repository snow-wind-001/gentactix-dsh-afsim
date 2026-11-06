"""Existing Native unit Agents before/after a formal damaged split, normal HTTP."""
import argparse
import copy
import json
from pathlib import Path
import uuid

from . import formation_commit_live as previous
from . import force_task_execution_live as api

ROOT=previous.ROOT/'afsim/unit-agents'


def save(name,value):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('Preserve existing evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def checkpoint(sid):
    path=previous.ROOT/'afsim/api/sessions'/(sid+'.json')
    return json.loads(path.read_text())['session']


def advance(sid,agents,label):
    url='/sessions/'+sid;view=api.call('GET',url+'/commands');before=checkpoint(sid)
    api.call('PUT',url+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units'] if u['available'] and u['id'] not in agents],
        control_team='red',director=True,no_fire=True,unit_agents=agents,
        intent='原生单位会话生命周期软件QA：本轮请明确hold待命，不机动、不开火；保留既有人员装备损伤。'))
    view=api.call('GET',url+'/commands')
    after=api.call('POST',url+'/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        batch_id=uuid.uuid4().hex,instruction='指定单位由自己的Native Agent决策，按本轮软件QA意图明确hold待命；其余单位已人工覆盖。不是历史重现。'))
    full=checkpoint(sid);rows=full['trajectory'][-1]['decisions']
    native=[r for r in rows if r.get('source')=='native_unit_agent']
    assert {r['unit_id'] for r in native}==set(agents)
    assert all(r['action']=='hold' for r in native),native
    assert full['turn_count']==before['turn_count']+1
    old={u['name']:u for team in ('red','blue') for u in before['war_state'][team+'_units']}
    for team in ('red','blue'):
        for unit in full['war_state'][team+'_units']:
            assert unit['personnel']==old[unit['name']]['personnel']
    save(label+'.json',dict(before=before,after=full,decisions=native,engine_meta=after['engine_meta']))
    print('PASS actual Native unit Agents',label,'turn',full['turn_count'],'agents',len(agents),flush=True)
    return full


def run():
    sid=json.loads((previous.ROOT/'afsim/source.json').read_text())['session_id'];url='/sessions/'+sid
    before=api.call('GET',url);view=api.call('GET',url+'/commands')
    parent=next(u for u in before['war_state']['red_units'] if u.get('source_historical_unit_id')=='ww2.cn.division159')
    identity=next(u['id'] for u in view['units'] if u['name']==parent['name'])
    parent_run=advance(sid,[identity],'parent');parent_binding=copy.deepcopy(parent_run['command_state']['agent_sessions'][identity])
    previous.convert('afsim',url,'split',[identity],'agent-split')
    split=checkpoint(sid);mapping=split['command_state']['formation_handoffs'][-1]['command_map'];children=mapping[identity]
    assert set(split['command_state']['unit_agents'])==set(children)
    assert split['command_state']['agent_sessions'][identity]==parent_binding
    assert all(i not in split['command_state']['agent_sessions'] for i in children)
    after=advance(sid,children,'children');bindings=after['command_state']['agent_sessions']
    assert bindings[identity]==parent_binding
    ids=[bindings[i]['session_id'] for i in children]
    assert len(set(ids))==2 and parent_binding['session_id'] not in ids
    assert all('parent_session_id' not in bindings[i] for i in children)
    save('expected-cold.json',after)
    save('review.json',dict(passed=True,session_id=sid,parent_unit=identity,child_units=children,parent_binding=parent_binding,
        child_bindings={i:bindings[i] for i in children},actual_unit_decisions=3,parent_binding_preserved=True,
        distinct_fresh_Native_sessions=True,source='normal unit_agents API and existing AgentRegistry',
        scope='Actual one-parent/two-child lifecycle over damaged synthetic state; not UI, phase, branch or full-history acceptance'))


def cold(resume=False):
    expected=json.loads((ROOT/'expected-cold.json').read_text());sid=expected['id']
    actual=api.call('GET','/sessions/'+sid+'/export')['session'];assert actual==expected
    save('cold-review.json',dict(passed=True,entire_session_exact=True,pid=api.call('GET','/health')['build']['pid']))
    if resume:
        review=json.loads((ROOT/'review.json').read_text());after=advance(sid,review['child_units'],'resumed')
        assert all(after['command_state']['agent_sessions'][i]['session_id']==expected['command_state']['agent_sessions'][i]['session_id'] for i in review['child_units'])
        save('resume-review.json',dict(passed=True,same_Native_sessions=True,actual_unit_decisions=2,session_id=sid))
    print('PASS Native unit Agent full cold restore'+(' and actual resume' if resume else ''),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['run','cold','resume'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args();previous.configure('afsim')
    if args.mode in ('run','resume') and not args.live:parser.error('Actual model decisions require --live')
    if args.mode=='run':run()
    else:cold(resume=args.mode=='resume')


if __name__=='__main__':main()
