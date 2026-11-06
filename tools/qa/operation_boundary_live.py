"""Isolated normal API: actual boundary exit, timed sustainment and return."""
import argparse
import copy
import json
import os
from pathlib import Path
import uuid
from tools.qa import force_task_execution_live as workflow

ROOT=Path('.cache/qa/operation-boundary-2026-11-02')
PORT=19136
workflow.PORT=PORT
call=workflow.call


def save(name,value):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def serve():
    folder=(ROOT/'http').resolve();folder.mkdir(parents=True,exist_ok=True)
    for name,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                        ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+name]=str(folder/suffix)
    from backend import main,harness_engine
    import uvicorn
    try:uvicorn.run(main.app,host='127.0.0.1',port=PORT,log_level='warning')
    finally:harness_engine.close_harness()


def revision(base):
    v=call('GET',base+'/commands')
    return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'])


def queue(base,orders):
    return call('PUT',base+'/commands',{**revision(base),'control_team':'red','director':True,
        'no_fire':False,'intent':'边界及连续账软件QA；参数未历史标定','orders':orders})


def unit(snap):
    return next(u for u in snap['war_state']['red_units'] if u['historical_unit_id']=='ww2.cn.division159')


def row(snap):
    return next(r for r in snap['war_state']['unit_participation']['actors'].values() if r['name']==unit(snap)['name'])


def create(engine):
    if (ROOT/engine/'case.json').exists():raise ValueError('QA case already exists; preserve it and use the explicit resume operation')
    from tools.qa.operation_boundary_fixture import inputs
    from verify_support_dynamics import config
    source,p=inputs();p['clock']['time_step']='6小时';p['support_dynamics']={**config(),'food_work_per_hour':.2}
    for actor in p['actors'].values():actor['personnel']=10000;actor['equipment']['transport']=20
    for support in p['support'].values():support['stock']=0
    created=call('POST','/sessions',dict(scenario='作战区边界QA；所有兵额/通路均为计算假设',
        battle=source['definition']['battle'],time_step='6小时',product_mode='historical',simulation_mode='open',
        execution_backend=engine,agent_mode='native',persist_roles=True,historical_parameters=p,historical_initial_version='1.2.0'))
    base='/sessions/'+created['session_id'];initial=call('POST',base+'/init')
    view=call('GET',base+'/commands');red=next(u for u in view['units'] if u['name']==unit(initial)['name']);blue=next(u for u in view['units'] if u['team']=='blue')
    case=dict(session_id=created['session_id'],engine=engine,unit_id=red['id'],blue_id=blue['id'],
        route=p['operation_boundary']['routes'][0],initial=initial)
    save(engine+'/case.json',case)
    return case


def orders(case,kind=None,combat=False):
    base='/sessions/'+case['session_id'];view=call('GET',base+'/commands')
    values=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=200) for u in view['units']]
    if combat:
        for a,b in ((case['unit_id'],case['blue_id']),(case['blue_id'],case['unit_id'])):
            item=next(o for o in values if o['unit_id']==a);item.clear();item.update(unit_id=a,action='fire',target_id=b,duration='next')
    if kind:
        item=next(o for o in values if o['unit_id']==case['unit_id']);item.clear()
        item.update(unit_id=case['unit_id'],action='move',duration='until_arrived',participation=kind,
            destination=case['route']['outside' if kind=='withdraw' else 'inside'])
    queue(base,values)


def advance(case,label):
    base='/sessions/'+case['session_id'];snap=call('POST',base+'/next',{**revision(base),'batch_id':uuid.uuid4().hex})
    save(case['engine']+'/turn-'+str(snap['turn_count'])+'.json',snap)
    if case['engine']=='afsim':
        assert snap['afsim']['returncode']==0 and snap['afsim']['model_skipped']
    print('PASS',case['engine'],label,'T',snap['turn_count'],row(snap)['status'],flush=True)
    return snap


def personnel_account(member):
    p=member['personnel'];values={k:p[k] for k in ('committed','current','casualties','noncombat_losses')}
    values.update({k:p.get(k,0) for k in ('killed','wounded','missing','captured')})
    values['unclassified_casualties']=p.get('unclassified_casualties',p['casualties']-sum(values[k] for k in ('killed','wounded','missing','captured')))
    return values


def run(engine,resume=False):
    if resume:
        case=json.loads((ROOT/engine/'case.json').read_text());damaged=json.loads((ROOT/engine/'turn-1.json').read_text())
        off=call('GET','/sessions/'+case['session_id'])
        assert off['turn_count']==2 and row(off)['status']=='offmap','Explicit QA resume supports only the saved exit checkpoint'
        print('Resume existing',engine,case['session_id'],'at committedT2; no new world or model replay',flush=True)
    else:
        case=create(engine);orders(case,combat=True);damaged=advance(case,'actual combat')
        assert unit(damaged)['personnel']['casualties']>0
        orders(case,'withdraw');off=advance(case,'physical exit')
        while row(off)['status']!='offmap':off=advance(case,'continued physical exit')
    assert personnel_account(unit(off))==personnel_account(unit(damaged))
    assert unit(off)['equipment']==unit(damaged)['equipment']
    orders(case);six=advance(case,'outside6hours')
    assert row(six)['status']=='offmap' and unit(six)['logistics']['food']<unit(off)['logistics']['food']
    for i in range(8):latest=advance(case,'outside2days-'+str(i+1))
    assert row(latest)['status']=='offmap'
    assert personnel_account(unit(latest))==personnel_account(unit(damaged))
    assert unit(latest)['equipment']==unit(damaged)['equipment']
    assert abs(unit(latest)['logistics']['food']-unit(six)['logistics']['food']+9.6)<1e-6
    save(engine+'/before-return.json',latest)
    orders(case,'reenter');back=advance(case,'physical return')
    while row(back)['status']!='deployed':back=advance(case,'continued physical return')
    assert personnel_account(unit(back))==personnel_account(unit(damaged)) and unit(back)['equipment']==unit(damaged)['equipment']
    assert set(back['war_state']['unit_participation']['actors'])==set(case['initial']['war_state']['unit_participation']['actors'])
    save(engine+'/result.json',dict(passed=True,session_id=case['session_id'],turns=back['turn_count'],
        outside_hours=54,elapsed_seconds=back['war_state']['simulation_clock']['elapsed_seconds'],
        damage=unit(damaged)['personnel'],outside_food=unit(latest)['logistics']['food'],final_food=unit(back)['logistics']['food'],
        full_history_accepted=False,actual_native=engine=='afsim',actual_model=engine=='narrative'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serve',action='store_true');parser.add_argument('--run-native',action='store_true');parser.add_argument('--run-model',action='store_true');parser.add_argument('--resume-model',action='store_true');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if args.serve:serve()
    elif args.run_native and args.live:run('afsim')
    elif args.run_model and args.live:run('narrative')
    elif args.resume_model and args.live:run('narrative',resume=True)
    else:parser.error('Use --serve or --run-native --live')
