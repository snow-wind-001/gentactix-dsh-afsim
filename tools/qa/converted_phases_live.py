"""Opt-in normal HTTP: actual damage, three conversions/phases, tasks and victory.

Bootstrap parameters are fixed software QA inputs, NOT AI-generated or historical
deployments. All subsequent decisions/effects use real SDK/AFSIM services.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid

from . import force_task_execution_live as api
from .boundary_lifecycle_fixture import inputs

ROOT=Path('.cache/qa/converted-phases-2026-11-02')
api.ROOT=ROOT;api.PORT=19210
PERSONNEL_RATIONS=False


def save(name,value):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise ValueError('Preserve existing evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def export(sid):return api.call('GET','/sessions/'+sid+'/export')['session']


def rev(base):
    v=api.call('GET',base+'/commands')
    return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'])


def parameters(*,personnel_rations=False):
    """Fixed, explicitly estimated integration inputs, never a model response."""
    source,p=inputs()
    for u in p['actors'].values():u['personnel']=10000
    for support in p['support'].values():support['stock']=0
    if personnel_rations:
        from verify_personnel_rations import config
        from verify_split_supply import config as split_config
        p.update(support_dynamics=config(),supply_distribution=split_config())
        p['rules']['ton_per_supply_unit']=.25
        for u in p['actors'].values():u['logistics']['food']=20
    return source,p


def serve():
    folder=(ROOT/'api').resolve()
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    if not (ROOT/'base-drafts.json').exists():
        from backend import scenario_builder
        from .campaign_plan_fixture import NOTE
        source,p=parameters(personnel_rations=PERSONNEL_RATIONS)
        drafts={}
        for engine in ('afsim','narrative'):
            print('Loading fixed QA configuration',engine,flush=True)
            d=scenario_builder.stage_historical(source,p,construction=dict(source='dsh_native_skill',
                qa_fixed_input=True,explanation=NOTE+' 固定测试输入，经既有staging校验，不是本次AI生成配置'),execution_backend=engine)
            drafts[engine]=dict(id=d['id'],battle=source['definition']['battle'],parameters=p)
        save('base-drafts.json',drafts)
    api.serve()


def add_task(case,group,label,kind='defend',point=None,finish=None):
    from verify_force_task_execution import execution
    base='/sessions/'+case['session_id'];turn=api.call('GET',base)['turn_count']
    task=dict(kind=kind,**({'destination':point} if point else {}))
    config=execution(label,start=turn+1,finish=finish or dict(kind='arrived'))
    request=dict(**api.revision(base),group_id=group,task=task,execution=config)
    p=api.call('POST',base+'/force-organization/task-preview',request)
    api.call('POST',base+'/force-organization/tasks',{**request,'preview_hash':p['preview_hash']})
    return next(reversed(export(case['session_id'])['command_state']['task_plans']))


def queue(case,*,combat=False,goal_phase=False):
    base='/sessions/'+case['session_id'];v=api.call('GET',base+'/commands')
    excluded=set(case['members'])|{case['native_unit']}
    if goal_phase:excluded.add(case['south_unit'])
    orders=[]
    for row in v['units']:
        if row['id'] in excluded or not row['available']:continue
        orders.append(dict(unit_id=row['id'],action='fire',target_id=case['members'][0],duration='next')
            if combat and row['id']==case['attacker'] else dict(unit_id=row['id'],action='hold',duration='next'))
    api.call('PUT',base+'/commands',dict(**rev(base),orders=orders,control_team='red',director=True,no_fire=not combat,
        unit_agents=[case['native_unit']],intent='连续阶段软件QA。独立单位Agent本轮明确hold，不机动不射击。'
        '其余动作按已确认人工命令和已登记持续任务执行；保留全部既有人员装备损伤，不能补满或额外交战。'))


def validate_personnel_turn(before,after):
    from gentactix import missions,support_dynamics as sd
    cfg=sd.configuration(after);assert cfg['version']=='personnel-rations-1'
    prior={u['name']:u for _,u in missions.units(before)}
    ledger={r['unit']:r for r in after['mission']['ledger']}
    actions={o['unit']:o['action'] for o in after['mission']['last_orders']}
    for _,u in missions.units(after):
        row=ledger[u['name']];a=prior[u['name']]
        assert row['food_received']==0
        expected=a['personnel']['current']*.75/24*.25/125
        if actions[u['name']]=='move':expected*=cfg['move_factor']
        assert abs(u['sustainment']['last_receipt']['demand']-expected)<1e-6
        assert abs(sd.food_mass(cfg,a)-sd.food_mass(cfg,u)-row['food_spent']*125)<1e-6


def advance(case,label):
    base='/sessions/'+case['session_id'];before=export(case['session_id']);started=time.monotonic()
    result=api.call('POST',base+'/next',dict(**rev(base),batch_id=uuid.uuid4().hex,
        instruction='连续阶段软件QA：独立单位Agent明确hold；所有已确认动作与持续任务优先，阶段、目标和任务完成由宿主判断。'
        '非交战轮不能新增战斗损失；旧损伤保留。分队资源工作量按各自根账尺度，不能按整编重复扣费。'))
    after=export(case['session_id']);turn=after['turn_count'];w=after['war_state']
    assert turn==before['turn_count']+1 and w['simulation_clock']['elapsed_seconds']==turn*900
    assert w['mission']['definition_hash']==case['definition_hash']
    decisions=[d for d in after['trajectory'][-1]['decisions'] if d.get('source')=='native_unit_agent']
    assert len(decisions)==1 and decisions[0]['unit_id']==case['native_unit'] and decisions[0]['action']=='hold'
    if case['engine']=='afsim':assert w['afsim']['returncode']==0 and w['afsim']['effects_source']=='afsim-native-teaching-1'
    else:assert w['dsh_execution']['effects_source']=='dsh_model_estimate' and not w.get('afsim')
    if turn>1:
        old={u['name']:u for t in ('red','blue') for u in before['war_state'][t+'_units']}
        for t in ('red','blue'):
            for u in w[t+'_units']:assert u['personnel']==old[u['name']]['personnel']
    if PERSONNEL_RATIONS:
        validate_personnel_turn(before['war_state'],w)
    save(case['engine']+'/turn-'+str(turn)+'.json',dict(before=before,after=after,engine_meta=result['engine_meta'],label=label,decisions=decisions))
    print('PASS actual',case['engine'],label,'T'+str(turn),'phase'+str(w['campaign_lifecycle']['phase_index']+1),round(time.monotonic()-started,2),'s',flush=True)
    return after


def convert(case,kind,label):
    base='/sessions/'+case['session_id'];before=export(case['session_id']);v=api.call('GET',base+'/commands')
    request=dict(**rev(base),kind=kind,unit_ids=case['members'],organization_revision=api.call('GET',base+'/force-organization')['revision'],
        assumption='固定教学参数的运行中重组软件验证，非历史编组命令')
    if kind=='split':
        entry=next(r for r in v['units'] if r['id']==case['members'][0]);u=next(u for u in before['war_state']['red_units'] if u['name']==entry['name']);n=u['personnel']['committed']
        request['allocations']=[dict(id='a',label='连续左',committed=n//2),dict(id='b',label='连续右',committed=n-n//2)]
    preview=api.call('POST',base+'/force-organization/conversion-preview',request)
    request.update(view_version=preview['view_version'],commit_id=uuid.uuid4().hex)
    result=api.call('POST',base+'/force-organization/conversion-commit',request)['conversion_result']
    after=export(case['session_id'])
    assert after['war_state']['campaign_lifecycle']==before['war_state']['campaign_lifecycle']
    assert after['war_state']['simulation_clock']==before['war_state']['simulation_clock']
    assert after['history']==before['history'] and after['trajectory']==before['trajectory']
    if PERSONNEL_RATIONS:
        from gentactix import missions,support_dynamics as sd
        cfg=sd.configuration(after['war_state'])
        totals=lambda world:(sum(u['personnel']['current'] for _,u in missions.units(world)),
            sum(u['personnel']['casualties'] for _,u in missions.units(world)),
            sum(sd.food_mass(cfg,u) for _,u in missions.units(world)))
        a,b=totals(before['war_state']),totals(after['war_state'])
        assert a[:2]==b[:2] and abs(a[2]-b[2])<1e-6
    case['members']=list(dict.fromkeys(i for values in result['current_command_map'].values() for i in values))
    save(case['engine']+'/'+label+'.json',dict(before=before,after=after,request=request,result=result))
    return request


def start(engine):
    if (ROOT/engine/'initial.json').exists():raise ValueError('Existing prefix evidence; recover it instead of creating another battle')
    source=json.loads((ROOT/'base-drafts.json').read_text())[engine]
    draft=api.call('POST','/scenarios/from-historical',dict(base_draft_id=source['id'],execution_backend=engine))['draft']
    created=api.call('POST','/sessions',dict(scenario='分合兵跨三阶段、持续任务与目标结算QA；不是完整历史战役',battle=source['battle'],product_mode='synthetic',
        scenario_draft_id=draft['id'],synthetic_configuration=draft['configuration'],execution_backend=engine,simulation_mode='open',time_step='15分钟',agent_mode='native',persist_roles=True))
    sid=created['session_id'];base='/sessions/'+sid;initial=api.call('POST',base+'/init');view=api.call('GET',base+'/commands')
    names={u['name']:u.get('source_historical_unit_id') for t in ('red','blue') for u in initial['war_state'][t+'_units']}
    by_source={names[u['name']]:u['id'] for u in view['units']}
    root=by_source['ww2.cn.division159'];south=by_source['ww2.cn.division51'];attacker=next(u['id'] for u in view['units'] if u['team']=='blue')
    native=next(u['id'] for u in view['units'] if u['id'] not in (root,south,attacker))
    case=dict(engine=engine,session_id=sid,members=[root],south_unit=south,attacker=attacker,native_unit=native,definition_hash=initial['war_state']['mission']['definition_hash'])
    # Enable director before temporary task organization is assigned.
    queue(case)
    org=api.call('POST',base+'/force-organization/detach',dict(**api.revision(base),unit_ids=[root],label='跨阶段原任务群',assumption='软件指挥验证，非历史改隶'))
    case['group']=next(g['id'] for g in org['groups'] if g['label']=='跨阶段原任务群')
    case['task']=add_task(case,case['group'],'四轮连续防御',finish=dict(kind='turn',end_turn=4,minimum_executions=4))
    save(engine+'/prefix-case.json',case)
    save(engine+'/initial.json',initial);queue(case,combat=True);damaged=advance(case,'actual damage and first phase transition')
    assert sum(u['personnel']['casualties'] for u in damaged['war_state']['red_units'])>0
    assert damaged['war_state']['campaign_lifecycle']['phase_index']==1
    continue_start(case)


def recover_start(engine):
    case=json.loads((ROOT/engine/'prefix-case.json').read_text());after=export(case['session_id'])
    assert 1<=after['turn_count']<=3
    trace=next(t for t in after['trajectory'] if t['turn']==1);assert all(r['finish_reason']=='completed' for r in trace['runs'])
    if PERSONNEL_RATIONS:validate_personnel_turn(trace['before'],trace['after'])
    save(engine+'/recovered-prefix-review-t'+str(after['turn_count'])+'.json',dict(passed=True,session_id=case['session_id'],turn=after['turn_count'],
        source='existing_committed_world_and_public_trajectory',physical_turn_repeated=False))
    continue_start(case)


def continue_start(case):
    engine=case['engine'];sid=case['session_id'];base='/sessions/'+sid
    def existing_or_convert(kind,label):
        path=ROOT/engine/(label+'.json')
        if path.exists():
            saved=json.loads(path.read_text());result=saved['result']
            case['members']=list(dict.fromkeys(i for values in result['current_command_map'].values() for i in values))
            return saved['request']
        return convert(case,kind,label)
    first=existing_or_convert('split','split-phase2')
    if export(sid)['turn_count']==1:queue(case);advance(case,'split task execution')
    existing_or_convert('merge','merge-phase2')
    if export(sid)['turn_count']==2:queue(case);advance(case,'second phase completion')
    a=export(sid)
    assert a['war_state']['campaign_lifecycle']['phase_index']==2
    existing_or_convert('split','split-phase3')
    prior=export(sid);blob=(ROOT/'api/sessions'/(sid+'.json')).read_bytes()
    replay=api.call('POST',base+'/force-organization/conversion-commit',first)['conversion_result']
    assert replay['replayed'] and list(replay['current_command_map'].values())==[case['members']]
    assert export(sid)==prior and (ROOT/'api/sessions'/(sid+'.json')).read_bytes()==blob
    save(engine+'/replay.json',replay);save(engine+'/case.json',case);save(engine+'/expected-cold.json',export(sid))
    print('CHECKPOINT',engine,sid,'T3,three conversions; explicit cold resume required',flush=True)


def resume(engine):
    case=json.loads((ROOT/engine/'case.json').read_text());sid=case['session_id'];base='/sessions/'+sid
    expected=json.loads((ROOT/engine/'expected-cold.json').read_text());assert export(sid)==expected
    save(engine+'/cold-review.json',dict(passed=True,entire_session_exact=True,pid=api.call('GET','/health')['build']['pid']))
    queue(case);after=advance(case,'original task completes after cold recovery')
    task=after['command_state']['task_plans'][case['task']]['execution']
    assert task['status']=='completed' and all(s['executions']==4 for s in task['member_states'].values())
    org=api.call('POST',base+'/force-organization/detach',dict(**api.revision(base),unit_ids=[case['south_unit']],label='阶段三南向任务群',assumption='软件双方向目标，非历史改隶'))
    south=next(g['id'] for g in org['groups'] if g['label']=='阶段三南向任务群')
    points={n['id']:n['condition'].get('region',{}).get('center') for n in after['war_state']['mission']['definition']['campaign_plan']['nodes']}
    north_task=add_task(case,case['group'],'阶段三北向机动',kind='advance',point=points['north'])
    south_task=add_task(case,south,'阶段三南向机动',kind='advance',point=points['south'])
    for _ in range(8):
        queue(case,goal_phase=True);after=advance(case,'two-axis program goals')
        if after['war_state']['mission']['status']=='completed':break
    assert after['war_state']['mission']['winner']=='red'
    assert after['war_state']['campaign_lifecycle']['status']=='completed'
    assert all(p['status']=='completed' for p in after['war_state']['campaign_lifecycle']['phases'].values())
    original_binding=expected['command_state']['agent_sessions'][case['native_unit']]['session_id']
    assert after['command_state']['agent_sessions'][case['native_unit']]['session_id']==original_binding
    save(engine+'/expected-final-cold.json',after)
    save(engine+'/result.json',dict(passed=True,session_id=sid,turns=after['turn_count'],three_phases_completed=True,formal_conversions=3,
        original_defend_task_completed=True,continuing_sdk_session=True,goal_winner='red',north_task=north_task,south_task=south_task,
        scope='Fixed estimated QA parameters, actual SDK/backend and program goals; NOT historical deployment/effect calibration'))
    print('PASS COMPLETE',engine,'T'+str(after['turn_count']),'all3phases,3conversions,2axes,originaltask4deliveries',flush=True)


def main():
    global ROOT,PERSONNEL_RATIONS
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['serve','start','recover-start','resume']);p.add_argument('--backend',choices=['afsim','narrative']);p.add_argument('--live',action='store_true')
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--port',type=int,default=19210)
    p.add_argument('--personnel-rations',action='store_true');a=p.parse_args()
    if not 18000<=a.port<=19999:p.error('Use an isolated QA port')
    ROOT=a.root;api.ROOT=ROOT;api.PORT=a.port;PERSONNEL_RATIONS=a.personnel_rations
    if a.mode=='serve':serve();return
    if not a.live or not a.backend:p.error('Actual model/backend execution requires --live and --backend')
    if a.mode=='start':start(a.backend)
    elif a.mode=='recover-start':recover_start(a.backend)
    else:resume(a.backend)


if __name__=='__main__':main()
