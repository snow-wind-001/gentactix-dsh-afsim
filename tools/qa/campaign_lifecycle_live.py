"""Isolated normal HTTP lifecycle QA; actual engines require --live."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from tools.qa import force_task_execution_live as workflow

ROOT=Path('.cache/qa/campaign-lifecycle-2026-10-31')
workflow.ROOT=ROOT;workflow.PORT=19116
call=workflow.call


def create(engine):
    from tools.qa.campaign_lifecycle_fixture import inputs,NOTE
    folder=ROOT/engine;folder.mkdir(parents=True,exist_ok=True);path=folder/'case.json'
    if path.exists():return json.loads(path.read_text())
    source,p=inputs()
    created=call('POST','/sessions',dict(scenario='单世界十阶段验收 '+engine+'；'+NOTE,
        battle=source['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
        execution_backend=engine,agent_mode='native',historical_parameters=p,historical_initial_version='1.2.0'))
    sid=created['session_id'];base='/sessions/'+sid;initial=call('POST',base+'/init')
    view=call('GET',base+'/commands');assigned=next(u['id'] for u in view['units'] if u['name']=='第159师')
    call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='所有单位明确待命；仅验收阶段、时钟与持续账，不预设战斗损失。',
        orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=30) for u in view['units'] if u['id']!=assigned]))
    group=call('POST',base+'/force-organization/detach',dict(**workflow.revision(base),unit_ids=[assigned],label='跨十阶段群',assumption=NOTE))['groups'][-1]['id']
    from verify_force_task_execution import execution
    value=dict(**workflow.revision(base),group_id=group,task=dict(kind='defend'),
        execution=execution('跨十阶段保持',finish=dict(kind='turn',end_turn=12,minimum_executions=12)))
    preview=call('POST',base+'/force-organization/task-preview',value)
    call('POST',base+'/force-organization/tasks',{**value,'preview_hash':preview['preview_hash']})
    task=call('GET',base+'/force-organization/tasks')['rows'][0]['id']
    case=dict(session_id=sid,engine=engine,task_id=task,assigned_id=assigned,initial=call('GET',base),
        registry=call('GET',base+'/commands')['units'],organization=call('GET',base+'/force-organization')['groups'])
    path.write_text(json.dumps(case,ensure_ascii=False,indent=2));print('Created actual',engine,sid,flush=True)
    return case


def check(case,snapshot):
    from gentactix import missions
    base='/sessions/'+case['session_id'];world=snapshot['war_state'];turn=snapshot['turn_count']
    original=case['initial']['war_state'];life=world['campaign_lifecycle']
    assert world['mission']['definition_hash']==original['mission']['definition_hash']
    assert world['mission']['definition']==original['mission']['definition']
    assert world['simulation_clock']['elapsed_seconds']==turn*1800
    index=[0,1,2,3,3,3,4,5,6,7,8,9,9][turn]
    assert life['phase_index']==index
    before={(team,u['name']):u for team,u in missions.units(original)}
    for team,u in missions.units(world):
        assert abs(u['logistics']['food']-(80-turn*2))<1e-6 and u['logistics']['ammo']==80
        assert all(u['personnel'][k]==before[(team,u['name'])]['personnel'][k] for k in ('current','committed','casualties','noncombat_losses'))
    assert call('GET',base+'/force-organization')['groups']==case['organization']
    if turn<12:assert world['mission']['status']=='active'
    else:assert life['status']=='completed' and world['mission']['winner']=='red'
    task=call('GET',base+'/force-organization/tasks')['rows'][0]
    member=call('GET',base+'/force-organization/tasks?kind=members&task_id='+case['task_id'])['rows'][0]
    assert member['executions']==turn
    if turn==12:assert task['status']=='completed'
    return dict(turn=turn,phase=index+1,lifecycle_status=life['status'],food=world['red_units'][0]['logistics']['food'],
        task_executions=member['executions'],definition_bytes=len(json.dumps(world['mission']['definition'])),
        world_bytes=len(json.dumps(world)),engine_meta=snapshot.get('engine_meta'))


def capture(case,snapshot):
    folder=ROOT/case['engine'];turn=snapshot['turn_count'];row=check(case,snapshot)
    (folder/f'after-{turn}.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
    trace=call('GET','/sessions/'+case['session_id']+'/traces/'+str(turn))
    assert trace['record']['campaign_lifecycle']['phase_after']==row['phase']
    (folder/f'trace-{turn}.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
    return row


def run(engine):
    case=create(engine);folder=ROOT/engine;base='/sessions/'+case['session_id'];snap=call('GET',base);samples=[]
    result_path=folder/'result.json'
    prior=json.loads(result_path.read_text()) if result_path.exists() else None
    if prior and prior.get('passed'):
        assert snap['turn_count']==12;check(case,snap);print('Retained completed actual case; no new round executed',flush=True);return
    if prior:(folder/f'attempt-result-{time.time_ns()}.json').write_text(json.dumps(prior,ensure_ascii=False,indent=2))
    prior_samples={r['turn']:r for r in (prior or {}).get('samples',[])}
    for turn in range(1,snap['turn_count']+1):
        path=folder/f'after-{turn}.json'
        if path.exists():samples.append(copy.deepcopy(prior_samples.get(turn,dict(turn=turn,retained=True))))
    result=dict(passed=False,session_id=case['session_id'],engine=engine,samples=samples,actual_model=engine=='narrative',actual_afsim=engine=='afsim')
    if snap['turn_count']:result['resumed_from_turn']=snap['turn_count']
    try:
        while snap['turn_count']<12:
            assert not call('GET',base+'/progress')['active']
            print('Actual',engine,'round',snap['turn_count']+1,flush=True);start=time.monotonic();snap=workflow.advance(base)
            row=capture(case,snap);row['seconds']=round(time.monotonic()-start,3);samples.append(row)
            print('PASS',engine,row['turn'],'phase',row['phase'],'food',row['food'],'seconds',row['seconds'],flush=True)
            if snap['turn_count']==4:
                (folder/'gap-export.json').write_text(json.dumps(call('GET',base+'/export'),ensure_ascii=False,indent=2))
        result.update(passed=True,turn=12,world_hash=workflow.digest(snap['war_state']))
    finally:(folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))


def interventions():
    from tools.qa.campaign_lifecycle_fixture import inputs,NOTE
    if (ROOT/'interventions.json').exists():raise SystemExit('Preserve existing intervention evidence')
    folder=ROOT/'interventions';folder.mkdir(parents=True,exist_ok=True);rows=[]
    source,p=inputs();p['campaign_lifecycle']['finish_policy']='goal_outcomes'
    for move in (False,True):
        row=call('POST','/sessions',dict(scenario='单世界阶段提前结算对照 '+str(move)+'；'+NOTE,battle=source['definition']['battle'],
            time_step='30分钟',product_mode='historical',simulation_mode='open',execution_backend='afsim',agent_mode='native',
            historical_parameters=p,historical_initial_version='1.2.0'))
        base='/sessions/'+row['session_id'];before=call('POST',base+'/init');view=call('GET',base+'/commands')
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]
        if move:
            blue=next(u['id'] for u in view['units'] if u['team']=='blue')
            next(o for o in orders if o['unit_id']==blue).update(action='move',destination=p['campaign_plan']['nodes'][-1]['condition']['region']['center'])
        call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
            control_team='red',director=True,no_fire=False,intent='同前态只改变蓝方是否向出口机动，其他单位待命。',orders=orders))
        after=workflow.advance(base);w=after['war_state']
        (folder/('move.json' if move else 'hold.json')).write_text(json.dumps(dict(before=before,after=after,orders=orders),ensure_ascii=False,indent=2))
        assert w['afsim']['model_skipped'] and w['simulation_clock']['elapsed_seconds']==1800
        if move:assert w['mission']['winner']=='blue' and w['campaign_lifecycle']['status']=='interrupted'
        else:assert w['mission']['status']=='active' and w['campaign_lifecycle']['status']=='active'
        rows.append(dict(move=move,session_id=row['session_id'],definition_hash=before['war_state']['mission']['definition_hash'],
            initial_hash=before['war_state']['mission']['initial_hash'],world_hash=workflow.digest(w),turn=1,
            winner=w['mission']['winner'],status=w['mission']['status'],lifecycle_status=w['campaign_lifecycle']['status']))
    assert rows[0]['definition_hash']==rows[1]['definition_hash'] and rows[0]['initial_hash']==rows[1]['initial_hash']
    (ROOT/'interventions.json').write_text(json.dumps(dict(passed=True,actual_afsim=True,model_calls=False,cases=rows),ensure_ascii=False,indent=2))
    print('PASS actual native decision contrast: hold stays active, move allows blue early success without fabricating later stages',flush=True)


def message_probe():
    from tools.qa.campaign_lifecycle_fixture import inputs,NOTE
    path=ROOT/'message-probe.json'
    if path.exists():raise SystemExit('Retain existing final-message probe')
    source,p=inputs();created=call('POST','/sessions',dict(scenario='单世界阶段采样说明复核；'+NOTE,
        battle=source['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
        execution_backend='afsim',agent_mode='native',historical_parameters=p,historical_initial_version='1.2.0'))
    base='/sessions/'+created['session_id'];call('POST',base+'/init');view=call('GET',base+'/commands')
    call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='阶段采样说明验证，全部单位明确待命。',
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]))
    after=workflow.advance(base);w=after['war_state']
    assert w['campaign_lifecycle']['phase_index']==1 and w['campaign_lifecycle']['last_sample_phase']==0
    assert w['campaign_plan']['nodes']['milestone2']['status']=='waiting_phase'
    assert w['campaign_plan']['nodes']['milestone2']['reason']=='本轮物理观察尚未轮到该阶段；激活后的新回合才评分'
    path.write_text(json.dumps(dict(passed=True,session_id=created['session_id'],turn=1,world_hash=workflow.digest(w),after=after),ensure_ascii=False,indent=2))
    print('PASS actual final-source native stage-activation/observation distinction')


def cold_checkpoint(verify=False):
    """Compare normal exports before/after an actual isolated server restart."""
    expected_path=ROOT/'final-cold-expected.json'
    entries=[json.loads((ROOT/name/'result.json').read_text()) for name in ('afsim','narrative')]
    entries+=json.loads((ROOT/'interventions.json').read_text())['cases']
    entries.append(json.loads((ROOT/'message-probe.json').read_text()))
    assert len(entries)==5 and len({r['session_id'] for r in entries})==5
    saved={}
    for row in entries:
        sid=row['session_id'];base='/sessions/'+sid
        assert not call('GET',base+'/progress')['active'], 'Do not restart an active operation'
        snapshot=call('GET',base);export=call('GET',base+'/export')
        assert snapshot['turn_count']==row['turn'] and workflow.digest(snapshot['war_state'])==row['world_hash']
        saved[sid]=dict(turn=snapshot['turn_count'],world_hash=workflow.digest(snapshot['war_state']),
            history_hash=workflow.digest(snapshot['history']),tasks_hash=workflow.digest(call('GET',base+'/force-organization/tasks')),
            failure_count=len(export.get('failed_operations',[])))
    if verify:
        assert saved==json.loads(expected_path.read_text()), 'Cold restore changed world, history, tasks or failure metadata'
        (ROOT/'final-cold.json').write_text(json.dumps(dict(passed=True,cases=saved),ensure_ascii=False,indent=2))
        print('PASS actual cold restoration of all five isolated cases; failed-operation metadata retained')
    else:
        if expected_path.exists():raise SystemExit('Preserve existing pre-restart evidence')
        expected_path.write_text(json.dumps(saved,ensure_ascii=False,indent=2))
        print('Saved five idle case checkpoints; a normal server restart is required before cold verification')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['serve','setup-ui','native','dsh','capture-ui','interventions','message-probe','prepare-cold','cold']);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    if args.mode=='serve':workflow.serve()
    elif args.mode=='setup-ui':create('afsim')
    elif args.mode=='interventions':
        if not args.live:parser.error('Actual native contrasts require --live')
        interventions()
    elif args.mode=='message-probe':
        if not args.live:parser.error('Actual native validation requires --live')
        message_probe()
    elif args.mode in ('native','dsh'):
        if not args.live:parser.error('Actual execution requires --live')
        run('afsim' if args.mode=='native' else 'narrative')
    elif args.mode=='capture-ui':
        case=create('afsim');snapshot=call('GET','/sessions/'+case['session_id']);capture(case,snapshot)
        if snapshot['turn_count']==4:
            (ROOT/'afsim/gap-export.json').write_text(json.dumps(call('GET','/sessions/'+case['session_id']+'/export'),ensure_ascii=False,indent=2))
            print('Captured actual gap checkpoint; browser resumes toward round 12')
        else:
            assert snapshot['turn_count']==12
            (ROOT/'afsim/result.json').write_text(json.dumps(dict(passed=True,session_id=case['session_id'],engine='afsim',turn=12,
                world_hash=workflow.digest(snapshot['war_state']),actual_afsim=True,actual_model=False,driven_by_browser=True),ensure_ascii=False,indent=2))
    else:cold_checkpoint(verify=args.mode=='cold')
