"""Isolated full22 public-window workflows; numerical priors are not historical facts."""
import argparse
import copy
import json
from pathlib import Path
import uuid
from urllib.parse import urlencode

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/wjl22-continuous-2026-11-02')
api.ROOT=ROOT
api.PORT=19217


def save(name,value):
    path=ROOT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('Preserve prior evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def all_tasks(sid):
    rows=[];args={};pages=[]
    while True:
        page=api.call('GET','/sessions/'+sid+'/force-organization/tasks?'+urlencode(args))
        rows.extend(page['rows']);pages.append(page)
        if not page['next_args']:break
        args=page['next_args']
    return dict(rows=rows,pages=pages)


def lifecycle():
    from verify_scenario_assembly import CampaignLifecycleAssemblyTests
    fixture=CampaignLifecycleAssemblyTests()
    fixture.setUp()
    try:return copy.deepcopy(fixture.lifecycle)
    finally:fixture.doCleanups()


def configure(sid):
    """Normal command/group/task APIs, no direct world writes or numerical refits."""
    from verify_force_task_execution import execution
    base='/sessions/'+sid
    initial=api.call('GET',base)
    assert initial['turn_count']==0
    view=api.call('GET',base+'/commands')
    world=initial['war_state']
    names={u['name']:u['historical_unit_id'] for t in ('red','blue') for u in world[t+'_units']}
    ids={names[u['name']]:u['id'] for u in view['units']}
    assert len(ids)==22
    nodes={n['id']:n for n in world['mission']['definition']['campaign_plan']['nodes']}
    inner=nodes['red_inner']['condition']['region']['center']
    outer=nodes['red_block']['condition']['region']['center']
    exit_point=nodes['blue_exit']['condition']['region']['center']
    agents=[ids[i] for i in ('ww2.cn.division90','ww2.jp.suzuki_detachment')]
    cs=api.call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],
        world_version=view['world_version'],orders=[],unit_agents=agents,control_team='red',director=True,no_fire=False,
        intent='完整22单位开放会战验收；数值与部署是显式估计，不是历史已标定。'
            '第90师独立判断东侧攻击，尽快接近内圈目标，合法射程内可炮击/射击；铃木支队独立判断增援，'
            '向外线阻援点及内圈推进，在合法距离内攻击拦截部队。两单位不得闲置于后方；其余方向由持续任务执行。'
            '不得虚构装备或恢复损耗，按当前权威观察做出一项动作。'))
    # All remaining20 actors have purposeful persistent tasks. The two independent
    # frontline DSH sessions remain unoverridden, not spare units ordered to hold.
    definitions=[
        ('北侧攻击',['ww2.cn.division159','ww2.cn.division160','ww2.cn.division161.wjl_part'],'assault',inner),
        ('南侧攻击',['ww2.cn.division51','ww2.cn.division58'],'assault',inner),
        ('东侧配合',['ww2.cn.division139','ww2.cn.division141','ww2.cn.division187'],'assault',inner),
        ('西侧机动',['ww2.cn.division142.wjl_part'],'assault',inner),
        ('外线阻援',['ww2.cn.division60','ww2.cn.division_new13','ww2.cn.division_new15','ww2.cn.division91','ww2.cn.division_reserve6'],'assault',outer),
        ('炮兵支援',['ww2.cn.artillery2.battalion3','ww2.cn.artillery1.company6'],'uniform',None),
        ('被围主力突围',['ww2.jp.division106'],'withdraw',exit_point),
        ('内线掩护',['ww2.jp.regiment149'],'assault',inner),
        ('外线接应',['ww2.jp.uga_detachment','ww2.jp.saeda_detachment'],'assault',outer)]
    tasks=[]
    for label,hids,kind,point in definitions:
        response=api.call('POST',base+'/force-organization/detach',dict(**api.revision(base),
            unit_ids=[ids[i] for i in hids],label=label,assumption='软件验收临时任务群，不是史实改隶或实有兵力。'))
        group=next(g['id'] for g in response['groups'] if g['label']==label)
        task=dict(kind=kind,**({'destination':point} if point else {}))
        if kind=='assault':
            target=('ww2.cn.division159' if label=='内线掩护' else
                    'ww2.cn.division_new13' if label=='外线接应' else
                    'ww2.jp.uga_detachment' if label=='外线阻援' else 'ww2.jp.division106')
            task['target_id']=ids[target]
        if label=='炮兵支援':task['order']=dict(action='bombard',target_id=ids['ww2.jp.division106'],duration='next')
        elif kind=='defend':task=dict(kind='uniform',order=dict(action='fortify',duration='next'))
        value=dict(**api.revision(base),group_id=group,task=task,
            execution=execution(label,finish=dict(kind='turn',end_turn=30,minimum_executions=1)))
        preview=api.call('POST',base+'/force-organization/task-preview',value)
        api.call('POST',base+'/force-organization/tasks',{**value,'preview_hash':preview['preview_hash']})
        tasks.append(dict(label=label,group=group,kind=kind,actors=hids))
    case=dict(session_id=sid,agents=agents,ids=ids,tasks=tasks,
        initial_world_hash=api.digest(world),scope='Full22 explicit priors with bilateral goals, real independent frontline sessions and persistent tasks; not historical calibration')
    save(sid+'/configured.json',case)
    save(sid+'/before.json',api.call('GET',base+'/export')['session'])
    return case


def prepare():
    built=json.loads((ROOT/'build-response.json').read_text())['body']
    afsim=json.loads((ROOT/'builder-result.json').read_text())['session_id']
    configure(afsim)
    validated=api.call('POST','/historical-scenarios/validate',dict(parameters=built['parameters'],
        parent_draft_id=built['id'],execution_backend='narrative'))
    save('dsh-validation.json',validated)
    assert validated['parameters']==built['parameters']
    created=api.call('POST','/sessions',dict(scenario='万家岭完整22单位连续会战DSH验收；数值和部署为估计。',
        battle=built['initial']['definition']['battle'],time_step='1小时',product_mode='historical',simulation_mode='open',
        execution_backend='narrative',agent_mode='native',historical_parameters=validated['parameters'],
        historical_initial_version='1.4.0',scenario_draft_id=validated['id']))
    sid=created['session_id'];api.call('POST','/sessions/'+sid+'/init')
    configure(sid)
    cases=dict(afsim=afsim,narrative=sid)
    save('cases.json',cases)
    print('Configured full22 real two-backend cases',json.dumps(cases),flush=True)


def record(sid):
    base='/sessions/'+sid
    full=api.call('GET',base+'/export')['session'];world=full['war_state'];turn=full['turn_count']
    before=json.loads((ROOT/sid/('before.json' if turn==1 else 'after-'+str(turn-1)+'.json')).read_text())
    prior=before['war_state']
    actors=lambda w:{u['historical_unit_id']:u for t in ('red','blue') for u in w[t+'_units']}
    old=actors(prior);new=actors(world)
    assert len(new)==22 and new.keys()==old.keys()
    assert world['mission']['definition']==prior['mission']['definition']
    assert world['simulation_clock']['elapsed_seconds']-prior['simulation_clock']['elapsed_seconds']==3600
    for identity,u in new.items():
        p=u['personnel'];p0=old[identity]['personnel']
        assert p['committed']==p0['committed']==p['current']+p['casualties']+p['noncombat_losses']
        assert p['casualties']>=p0['casualties'] and p['noncombat_losses']>=p0['noncombat_losses']
        for e,e0 in zip(u['equipment'],old[identity]['equipment']):
            assert e['committed']==e0['committed']==e['operational']+e['damaged']+e['destroyed']
            assert e['destroyed']>=e0['destroyed']
    decisions=full['trajectory'][-1]['decisions']
    native=[r for r in decisions if r.get('source')=='native_unit_agent']
    configured=json.loads((ROOT/sid/'configured.json').read_text())
    assert {r['unit_id'] for r in native}==set(configured['agents'])
    if turn>1:
        for identity in configured['agents']:
            assert full['command_state']['agent_sessions'][identity]['session_id']==before['command_state']['agent_sessions'][identity]['session_id']
    tasks=all_tasks(sid)
    row=dict(turn=turn,time=world['current_time'],mission_status=world['mission']['status'],winner=world['mission'].get('winner'),
        phase_index=world['campaign_lifecycle']['phase_index'],phase_status=world['campaign_lifecycle']['status'],
        goals={i:s['status'] for i,s in world['campaign_plan']['nodes'].items()},
        losses={t:sum(u['personnel']['casualties'] for u in world[t+'_units']) for t in ('red','blue')},
        food={t:round(sum(u['logistics']['food'] for u in world[t+'_units']),4) for t in ('red','blue')},
        ammo={t:round(sum(u['logistics']['ammo'] for u in world[t+'_units']),4) for t in ('red','blue')},
        actions={action:sum(d.get('action')==action for d in decisions) for action in sorted({d.get('action','unknown') for d in decisions})},
        native_decisions=native,task_states={r['label']:r['status'] for r in tasks['rows']},
        moved=[i for i in new if any(new[i][k]!=old[i][k] for k in ('lat','lng'))],
        world_hash=api.digest(world),scope='Physical continuity and program goals under explicit priors, not historical effect calibration')
    save(sid+'/after-'+str(turn)+'.json',full)
    save(sid+'/tasks-'+str(turn)+'.json',tasks)
    save(sid+'/audit-'+str(turn)+'.json',row)
    print(json.dumps({k:v for k,v in row.items() if k not in ('native_decisions','scope','world_hash')},ensure_ascii=False),flush=True)
    return row


def branches():
    source=json.loads((ROOT/'cases.json').read_text())['afsim'];base='/sessions/'+source
    original=api.call('GET',base+'/export')['session']
    assert original['turn_count']==0
    cases={}
    for variant in ('breakout','hold'):
        view=api.call('GET',base+'/commands')
        branch=api.call('POST',base+'/commands/open-branch',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version']))
        sid=branch['session_id'];child='/sessions/'+sid
        assert branch['war_state']==original['war_state']
        tasks=all_tasks(sid)
        for row in tasks['rows']:
            if row['status'] not in ('completed','cancelled','failed'):
                api.call('POST',child+'/force-organization/cancel-task',dict(**api.revision(child),task_id=row['id']))
        full=api.call('GET',child+'/export')['session']
        assert full['war_state']==original['war_state']
        save(sid+'/branch-before.json',full)
        cases[variant]=sid
    assert api.call('GET',base+'/export')['session']==original
    save('branches.json',dict(source=source,source_hash=api.digest(original['war_state']),cases=cases,
        intervention='Only106division move-to-exit versus hold. All other orders identical at each common turn; standing tasks cancelled through normal API in BOTH branches, source untouched.'))
    print(json.dumps(cases),flush=True)


def complete_task_review():
    cases=json.loads((ROOT/'cases.json').read_text())
    source=cases['afsim']
    review_path=source+'/tasks-1-complete-pagination.json'
    if not (ROOT/review_path).exists():save(review_path,all_tasks(source))
    info=json.loads((ROOT/'branches.json').read_text())
    rows={}
    for variant,sid in info['cases'].items():
        before=api.call('GET','/sessions/'+sid+'/export')['session']
        assert before['turn_count']==0
        tasks=all_tasks(sid)
        for row in tasks['rows']:
            if row['status'] not in ('completed','cancelled','failed'):
                api.call('POST','/sessions/'+sid+'/force-organization/cancel-task',
                    dict(**api.revision('/sessions/'+sid),task_id=row['id']))
        full=api.call('GET','/sessions/'+sid+'/export')['session']
        assert full['war_state']==before['war_state']
        tasks=all_tasks(sid)
        assert len(tasks['rows'])==9 and all(r['status']=='cancelled' for r in tasks['rows'])
        save(sid+'/branch-before-all-tasks.json',full)
        rows[variant]=dict(tasks=9,cancelled=9,world_hash=api.digest(full['war_state']))
    save('complete-task-pagination-review.json',dict(passed=True,branches=rows,
        initial_audit='Original tasks-1/audit-1 preserved with only first8 rows. New complete two-page review covers9; branch correction done before any physical turn.'))


def branch_orders(sid):
    info=json.loads((ROOT/'branches.json').read_text())
    variant=next(k for k,v in info['cases'].items() if v==sid)
    source=json.loads((ROOT/info['source']/'configured.json').read_text())
    view=api.call('GET','/sessions/'+sid+'/commands')
    full=api.call('GET','/sessions/'+sid+'/export')['session'];w=full['war_state']
    plan={n['id']:n for n in w['mission']['definition']['campaign_plan']['nodes']}
    inner=plan['red_inner']['condition']['region']['center'];outer=plan['red_block']['condition']['region']['center']
    exit_point=plan['blue_exit']['condition']['region']['center'];ids=source['ids']
    orders=[]
    for task in source['tasks']:
        for identity in task['actors']:
            point=outer if task['label'] in ('外线阻援','外线接应') else inner
            if task['label']=='炮兵支援':order=dict(action='bombard',target_id=ids['ww2.jp.division106'])
            elif identity=='ww2.jp.division106':
                order=dict(action='move',destination=exit_point,duration='until_arrived') if variant=='breakout' else dict(action='hold')
            else:order=dict(action='move',destination=point,duration='until_arrived')
            orders.append({'unit_id':ids[identity],'duration':'next',**order})
    for identity in ('ww2.cn.division90','ww2.jp.suzuki_detachment'):
        orders.append(dict(unit_id=ids[identity],action='move',duration='until_arrived',destination=inner if identity.startswith('ww2.cn') else outer))
    assert len(orders)==22
    # This preserves identical intended artillery orders only while legal in BOTH
    # physical branches; if unavailable, make the same explicit hold intervention.
    from gentactix import missions
    radius=w['mission']['definition']['combined_rules']['artillery_range_m']/1000
    other=next(v for v in info['cases'].values() if v!=sid)
    worlds=[w,api.call('GET','/sessions/'+other)['war_state']]
    for order in orders:
        if order['action']!='bombard':continue
        identity=next(i for i,v in ids.items() if v==order['unit_id'])
        for world in worlds:
            actors={u['historical_unit_id']:u for _,u in missions.units(world)}
            if missions.distance(actors[identity],actors['ww2.jp.division106'])>radius:
                order.clear();order.update(unit_id=ids[identity],action='hold',duration='next');break
    result=api.call('PUT','/sessions/'+sid+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='实际执行受控决策比较；除106师团突围/保持外其他命令相同，估计初态不等于历史真值。',unit_agents=[],orders=orders))
    save(sid+'/orders-'+str(full['turn_count']+1)+'.json',dict(variant=variant,orders=orders,receipt_revision=result['revision']))
    print('Controlled orders',sid,'turn',full['turn_count']+1,variant,flush=True)


def covering_withdrawal():
    """An explicit operator decision, retaining casualties and cancelled task history."""
    from verify_force_task_execution import execution
    cases=json.loads((ROOT/'cases.json').read_text())
    changes={}
    for engine,sid in cases.items():
        base='/sessions/'+sid
        full=api.call('GET',base+'/export')['session']
        assert full['turn_count']==1
        tasks=all_tasks(sid)['rows']
        prior=next(r for r in tasks if r['label']=='内线掩护')
        api.call('POST',base+'/force-organization/cancel-task',dict(**api.revision(base),task_id=prior['id']))
        point=next(n for n in full['war_state']['mission']['definition']['campaign_plan']['nodes'] if n['id']=='blue_exit')['condition']['region']['center']
        task=dict(kind='withdraw',destination=point)
        value=dict(**api.revision(base),group_id=prior['group_id'],task=task,
            execution=execution('内线掩护后撤',start=2,finish=dict(kind='turn',end_turn=30,minimum_executions=1)))
        preview=api.call('POST',base+'/force-organization/task-preview',value)
        api.call('POST',base+'/force-organization/tasks',{**value,'preview_hash':preview['preview_hash']})
        assert api.call('GET',base)['war_state']==full['war_state']
        changes[engine]=dict(session_id=sid,cancelled_task=prior['id'],group_id=prior['group_id'],
            destination=point,decision='第一小时完成内线掩护后撤，保存独立投入部，非史实命令。红方仍须实际控制地域与保持兵力，未改目标、资源或时钟。')
    save('covering-withdrawal-decision.json',dict(changes=changes,source='explicit operator command through existing task APIs; not automatic historical injection'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('serve','lifecycle','configure','prepare','record','branches','branch-orders','complete-task-review','covering-withdrawal'))
    parser.add_argument('--sid')
    args=parser.parse_args()
    if args.mode=='serve':api.serve()
    elif args.mode=='lifecycle':save('lifecycle.json',lifecycle())
    elif args.mode=='prepare':prepare()
    elif args.mode=='record':record(args.sid)
    elif args.mode=='branches':branches()
    elif args.mode=='branch-orders':branch_orders(args.sid)
    elif args.mode=='complete-task-review':complete_task_review()
    elif args.mode=='covering-withdrawal':covering_withdrawal()
    else:print(json.dumps(configure(args.sid),ensure_ascii=False))
