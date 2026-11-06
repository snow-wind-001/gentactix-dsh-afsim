"""Isolated same-frame report validation over actual persistent task backends.

Reuses the normal HTTP task QA. No API mocks, output repair or alternate model.
"""
import argparse
import copy
import json
from pathlib import Path

from tools.qa import force_task_execution_live as workflow
from gentactix import reporting

ROOT=Path('.cache/qa/campaign-report-alignment-2026-10-31')
workflow.ROOT=ROOT
workflow.PORT=19115


def inspect_run(engine,case_name=None):
    folder=ROOT/(engine if case_name is None else engine+'-'+case_name)
    summary=json.loads((folder/'result.json').read_text())
    previous=json.loads((folder/'initial.json').read_text())['initial']['war_state']
    observations=[]
    for turn in range(1,summary['turn']+1):
        after=json.loads((folder/f'after-{turn}.json').read_text())
        trace=json.loads((folder/f'trace-{turn}.json').read_text())['record']
        audit=trace['guards']['report'];world=after['war_state']
        raw=reporting.inspect(audit['original_text'],world,previous,turn=turn)
        published=reporting.inspect(after['history'][0],world,previous,turn=turn)
        assert not published,published
        assert after['history'][0].startswith(f'【T+{turn} | {world["current_time"]}】')
        assert '第161师万家岭投入部' in after['history'][0]
        assert all(u['supply']==min(u['logistics']['food'],u['logistics']['ammo']) for team in ('red','blue') for u in world[team+'_units'])
        if turn==2:
            assert world['campaign_plan']['nodes']['south']['status']=='completed'
            assert '南侧方向控制：当前条件成立；目标条件满足' in after['history'][0]
        observations.append(dict(turn=turn,source_kind='actual_model' if engine=='narrative' else 'actual_afsim',
            audit_status=audit['status'],raw_issues=raw,published_issues=published,
            actual_model_meta=after.get('engine_meta'),world_hash=workflow.digest(world)))
        previous=world
    result=dict(passed=True,session_id=summary['session_id'],observations=observations,
        raw_known_patterns_clear=all(not o['raw_issues'] for o in observations),
        published_known_patterns_clear=True,
        scope='Six-identity software QA; known pattern screening is not general semantic or historical validation.')
    (folder/'alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('PASS published same-frame report alignment',engine,'raw known-pattern issues:',sum(len(o['raw_issues']) for o in observations),flush=True)


def fresh(case_name='final-first'):
    folder=ROOT/('narrative-'+case_name);folder.mkdir(parents=True,exist_ok=True)
    if (folder/'result.json').exists():raise SystemExit('Preserve existing real evidence; do not repeat this case')
    case=workflow.create('报告最终源码首轮 '+case_name,'narrative');base='/sessions/'+case['session_id']
    (folder/'initial.json').write_text(json.dumps(case,ensure_ascii=False,indent=2))
    view=workflow.call('GET',base+'/commands')
    workflow.call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='所有单位本轮原地待命。过程报告按实际回合，不代宿主宣布目标结论；没有弹药耗用仅可按实际收支描述。',
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]))
    result=dict(passed=False,session_id=case['session_id'],engine='narrative',actual_model=True,actual_afsim=False)
    try:
        import time
        started=time.monotonic();after=workflow.advance(base)
        (folder/'after-1.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
        (folder/'trace-1.json').write_text(json.dumps(workflow.call('GET',base+'/traces/1'),ensure_ascii=False,indent=2))
        assert after['turn_count']==1 and after['war_state']['mission']['status']=='active'
        assert after['war_state']['dsh_execution'] and not after['war_state'].get('afsim')
        assert all(r['ammo_spent']==0 for r in after['war_state']['mission']['ledger'])
        result.update(passed=True,turn=1,seconds=round(time.monotonic()-started,3),world_hash=workflow.digest(after['war_state']))
    finally:(folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    inspect_run('narrative',case_name)


def replay():
    source=Path('.cache/qa/force-task-execution-2026-10-31/narrative')
    after=json.loads((source/'after-2.json').read_text());previous=json.loads((source/'after-1.json').read_text())['war_state']
    raw=json.loads((source/'trace-2.json').read_text())['record']['guards']['report']['original_text']
    before=copy.deepcopy(after['war_state'])
    text,audit=reporting.render(raw,after['war_state'],previous,turn=2)
    assert {'narrative_turn','goal_verdict'}<={i['code'] for i in audit['issues']}
    assert '首轮执行' not in text and '待后续回合观察确认' not in text
    assert after['war_state']==before
    (ROOT/'original-failure-replay.json').write_text(json.dumps(dict(passed=True,
        source_session_id=after['session_id'],new_model_run=False,world_unchanged=True,audit=audit,published=text),ensure_ascii=False,indent=2))
    print('PASS saved actual failure replay; no new model call, physical world unchanged')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['serve','native','dsh','fresh','replay','cold']);parser.add_argument('--live',action='store_true');parser.add_argument('--name',default='final-first')
    args=parser.parse_args();ROOT.mkdir(parents=True,exist_ok=True)
    if args.mode=='serve':workflow.serve()
    elif args.mode=='replay':replay()
    elif args.mode=='fresh':
        if not args.live:parser.error('Actual model execution requires --live')
        fresh(args.name)
    elif args.mode in ('native','dsh'):
        if not args.live:parser.error('Actual backend execution requires --live')
        engine='afsim' if args.mode=='native' else 'narrative'
        workflow.run(engine);inspect_run(engine)
    else:
        cases=[]
        expected=json.loads((ROOT/'cold-expected.json').read_text()) if (ROOT/'cold-expected.json').exists() else {}
        for path in sorted(ROOT.glob('*/result.json')):
            row=json.loads(path.read_text());snapshot=workflow.call('GET','/sessions/'+row['session_id'])
            assert workflow.digest(snapshot['war_state'])==row['world_hash']
            assert snapshot['turn_count']==row['turn'] and not workflow.call('GET','/sessions/'+row['session_id']+'/progress')['active']
            if expected:
                assert workflow.digest(snapshot['history'])==expected[row['session_id']]['history_hash']
                assert workflow.digest(workflow.call('GET','/sessions/'+row['session_id']+'/force-organization/tasks'))==expected[row['session_id']]['tasks_hash']
            cases.append(dict(session_id=row['session_id'],engine=row['engine'],world_unchanged=True,turn=row['turn']))
        (ROOT/'cold.json').write_text(json.dumps(dict(passed=True,cases=cases,exact_history_and_tasks=bool(expected)),ensure_ascii=False,indent=2))
        print('PASS cold-restored backend worlds',len(cases))
