"""Normal API interleavings, checkpointed before an explicit cold resume."""
import argparse
import copy
import json
from pathlib import Path
import time
import uuid

from tools.qa import force_task_execution_live as api
from tools.qa.boundary_lifecycle_fixture import inputs

ROOT = Path('.cache/qa/boundary-lifecycle-2026-11-02')
api.ROOT = ROOT
api.PORT = 19140
call = api.call


def save(path, value):
    p = ROOT/path; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def route(case):
    return case['parameters']['operation_boundary']['routes'][0]


def selected(snapshot):
    return next(u for u in snapshot['war_state']['red_units'] if u['historical_unit_id']=='ww2.cn.division159')


def participation(snapshot):
    from gentactix import unit_participation
    return unit_participation.unit_view(snapshot['war_state'], selected(snapshot), 'red')


def revisions(base):
    v = call('GET',base+'/commands')
    return dict(expected_turn=v['turn'], revision=v['revision'], world_version=v['world_version'])


def queue(case, kind=None, *, combat=False):
    base='/sessions/'+case['session_id'];v=call('GET',base+'/commands')
    orders=[]
    for u in v['units']:
        if u['id']==case['unit_id']:
            if kind:
                orders.append(dict(unit_id=u['id'],action='move',duration='until_arrived',participation=kind,
                    destination=route(case)['outside' if kind=='withdraw' else 'inside']))
            # Otherwise the original task owns this unit; offmap it is blocked.
        elif combat and u['id']==case['blue_id']:
            orders.append(dict(unit_id=u['id'],action='fire',target_id=case['unit_id'],duration='next'))
        else:
            orders.append(dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=100))
    return call('PUT',base+'/commands',{**revisions(base), 'orders':orders,
        'control_team':'red','director':True,'no_fire':False,
        'intent':'单世界阶段／途中取消／场外保障／恢复原任务的软件QA，所有数值和地形未历史标定'})


def cancel_move(case):
    base='/sessions/'+case['session_id'];v=call('GET',base+'/commands')
    order=next(o for o in v['orders'] if o['unit_id']==case['unit_id'] and o['action']=='move')
    return call('DELETE',base+'/commands/'+order['id'],revisions(base))


def advance(case, label):
    base='/sessions/'+case['session_id'];started=time.monotonic()
    after=call('POST',base+'/next',{**revisions(base),'batch_id':uuid.uuid4().hex})
    save(case['engine']+'/turn-'+str(after['turn_count'])+'.json',after)
    trace=call('GET',base+'/traces/'+str(after['turn_count']))['record']
    save(case['engine']+'/trace-'+str(after['turn_count'])+'.json',trace)
    assert after['war_state']['simulation_clock']['elapsed_seconds']==after['turn_count']*900
    assert len(after['war_state']['unit_participation']['actors'])==6
    assert after['war_state']['mission']['definition_hash']==case['initial']['war_state']['mission']['definition_hash']
    if case['engine']=='afsim':assert after['afsim']['returncode']==0 and after['afsim']['model_skipped']
    else:assert after['war_state']['dsh_execution']['effects_source']=='dsh_model_estimate' and not after['war_state'].get('afsim')
    print('PASS',case['engine'],label,'T'+str(after['turn_count']),participation(after)['status'],
          'phase'+str(after['war_state']['campaign_lifecycle']['phase_index']+1),round(time.monotonic()-started,2),'s',flush=True)
    return after


def members(case):
    value=call('GET','/sessions/'+case['session_id']+'/force-organization/tasks?kind=members&task_id='+case['task_id'])
    return next(r for r in value['rows'] if r['unit_id']==case['unit_id'])


def create(engine):
    if (ROOT/engine/'case.json').exists():raise ValueError('Preserve existing case; use explicit resume after checkpoint')
    from verify_support_dynamics import config
    from verify_force_task_execution import execution
    source,p=inputs();p['support_dynamics']={**config(),'food_work_per_hour':.2}
    for actor in p['actors'].values():actor['personnel']=10000
    for support in p['support'].values():support['stock']=0
    created=call('POST','/sessions',dict(scenario='同世界跨阶段边界QA：估计配置，不是完整历史',
        battle=source['definition']['battle'],time_step='15分钟',product_mode='historical',simulation_mode='open',
        execution_backend=engine,agent_mode='native',persist_roles=True,historical_parameters=p,historical_initial_version='1.2.0'))
    base='/sessions/'+created['session_id'];initial=call('POST',base+'/init');v=call('GET',base+'/commands')
    uid=next(u['id'] for u in v['units'] if u['name']==selected(initial)['name'])
    bid=next(u['id'] for u in v['units'] if u['team']=='blue')
    org=call('GET',base+'/force-organization')
    detached=call('POST',base+'/force-organization/detach',dict(
        expected_turn=org['turn'],revision=org['command_revision'],world_version=org['world_version'],organization_revision=org['revision'],
        unit_ids=[uid],label='QA连续阶段原任务群',assumption='软件测试临时指挥，不是史实改隶'))
    gid=next(g['id'] for g in detached['groups'] if g['label']=='QA连续阶段原任务群')
    config=execution('QA原任务跨阶段保留',finish=dict(kind='turn',end_turn=100,minimum_executions=20))
    org=call('GET',base+'/force-organization')
    value=dict(expected_turn=org['turn'],revision=org['command_revision'],world_version=org['world_version'],
        organization_revision=org['revision'],group_id=gid,task=dict(kind='defend'),execution=config)
    preview=call('POST',base+'/force-organization/task-preview',value)
    call('POST',base+'/force-organization/tasks',{**value,'preview_hash':preview['preview_hash']})
    tasks=call('GET',base+'/force-organization/tasks')
    case=dict(session_id=created['session_id'],engine=engine,unit_id=uid,blue_id=bid,task_id=tasks['rows'][-1]['id'],
        group_id=gid,parameters=p,initial=call('GET',base))
    save(engine+'/case.json',case);return case


def same_damage(snapshot, damaged):
    def account(u):
        p=u['personnel'];counts={k:p.get(k,0) for k in ('killed','wounded','missing','captured')}
        return {**{k:p[k] for k in ('committed','current','casualties','noncombat_losses')},**counts,
                'unclassified':p.get('unclassified_casualties',p['casualties']-sum(counts.values()))}
    assert account(selected(snapshot))==account(selected(damaged))
    assert selected(snapshot)['equipment']==selected(damaged)['equipment']


def run(engine, resume=False, resume_partial=False):
    if resume:
        case=json.loads((ROOT/engine/'case.json').read_text());checkpoint=json.loads((ROOT/engine/'checkpoint.json').read_text())
        damaged=json.loads((ROOT/engine/'turn-1.json').read_text());base='/sessions/'+case['session_id']
        current=call('GET',base)
        assert current['war_state']==checkpoint['war_state'] and current['history']==checkpoint['history']
        assert participation(current)['status']=='offmap' and members(case)['executions']==0
        save(engine+'/cold-restored.json',current)
        print('Resuming existing',engine,case['session_id'],'at saved T'+str(current['turn_count']),flush=True)
        queue(case,'reenter');back=advance(case,'partial return')
        assert participation(back)['status']=='returning'
        assert not participation(back)['controls_objectives']
        while participation(back)['status']!='deployed':back=advance(case,'continued return')
        same_damage(back,damaged)
        assert members(case)['executions']==0
        # No replacement order: original task resumes through existing planner.
        final=advance(case,'original task resumed')
        assert members(case)['executions']==1
        same_damage(final,damaged)
        assert final['war_state']['campaign_lifecycle']['phase_index']==2
        assert final['war_state']['mission']['status']=='active'
        save(engine+'/result.json',dict(passed=True,session_id=case['session_id'],engine=engine,
            final_turn=final['turn_count'],actual_model=engine=='narrative',actual_native=engine=='afsim',
            original_task_executions=1,cold_restore_exact=True,source_entities=6,
            current=selected(final)['personnel'],resources=selected(final)['logistics'],
            scope='Interleaved same-world stages, actual combat, cancel, exit, cold wait, partial return and original task; uncalibrated QA'))
        return
    if resume_partial:
        case=json.loads((ROOT/engine/'case.json').read_text());saved=json.loads((ROOT/engine/'turn-1.json').read_text())
        damaged=call('GET','/sessions/'+case['session_id'])
        assert damaged['turn_count']==1 and damaged['war_state']==saved['war_state'] and damaged['history']==saved['history']
        print('Explicit resume of committed T1 partial exit; no repeated physics/model call',flush=True)
    else:
        case=create(engine);queue(case,'withdraw',combat=True)
        damaged=advance(case,'combat during partial exit')
    assert participation(damaged)['status']=='withdrawing'
    assert participation(damaged)['pending']
    assert selected(damaged)['personnel']['casualties']>0
    assert damaged['war_state']['campaign_lifecycle']['phase_index']==1
    cancel_move(case);queue(case)
    cancelled=advance(case,'cancel unit order after stage change')
    assert participation(cancelled)['status']=='deployed' and not participation(cancelled)['pending']
    assert all(selected(cancelled)[k]==selected(damaged)[k] for k in ('lat','lng'))
    same_damage(cancelled,damaged)
    queue(case,'withdraw');off=advance(case,'exit in stage three')
    while participation(off)['status']!='offmap':off=advance(case,'continued exit')
    assert off['war_state']['campaign_lifecycle']['phase_index']==2
    queue(case);waited=advance(case,'outside wait with original task blocked')
    assert participation(waited)['status']=='offmap' and members(case)['executions']==0
    same_damage(waited,damaged)
    assert selected(waited)['logistics']['food']<selected(off)['logistics']['food']
    save(engine+'/checkpoint.json',waited)
    save(engine+'/checkpoint-review.json',dict(passed=True,session_id=case['session_id'],turn=waited['turn_count'],
        stop='Explicit committed outside checkpoint; resume only after cold restore',full_cycle_passed=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['serve','afsim','narrative'])
    resume=parser.add_mutually_exclusive_group();resume.add_argument('--resume',action='store_true');resume.add_argument('--resume-partial',action='store_true')
    parser.add_argument('--name',default='')
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if args.name:
        if not args.name.replace('-','').isalnum():parser.error('Name must be alphanumeric with hyphens')
        ROOT=ROOT/args.name
    if args.mode=='serve':api.ROOT=ROOT;api.serve()
    elif args.live:run(args.mode,args.resume,args.resume_partial)
    else:parser.error('Use --live for actual API/model/physics calls')
