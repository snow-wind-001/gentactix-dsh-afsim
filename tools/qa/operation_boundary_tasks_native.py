"""Actual Native exit/wait/return with original task and fresh-process recovery."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Actual local Native execution requires --live')
root=Path('.cache/qa/operation-boundary-2026-11-02/original-task');root.mkdir(parents=True,exist_ok=True)
for key,suffix in [('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
from tools.qa.operation_boundary_fixture import inputs
from verify_force_task_execution import execution,register
from gentactix import historical_operations as ho,missions,commands,force_organization as forces,unit_participation as up,sim_clock
from backend import afsim_world,afsim_rules,harness_engine


def step(s,label):
    prepared=commands.prepare(s);orders=[r['order'] for r in prepared['manual']];covered={o['unit'] for o in orders}
    orders += [dict(unit=u['name'],action='hold') for _,u in missions.units(s['war_state']) if u['name'] not in covered]
    before=s['war_state'];scene=afsim_world.compile_scene(before,orders,21600,native_rules=True)
    with patch.object(missions,'advance',side_effect=AssertionError('No Python physical fallback')):
        positions,evidence=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(before,positions,scene))
    after['current_time'],after['simulation_clock']=sim_clock.target(before,'6小时');up.advance(before,after,orders,21600,source='afsim_native');missions.evaluate(after);missions.validate(after)
    state,_=commands.finish(s,prepared,after,executed=orders)
    result={**copy.deepcopy(s),'war_state':after,'command_state':state,'turn_count':s['turn_count']+1};commands.validate_saved(result)
    (root/(label+'-session.json')).write_text(json.dumps(result,ensure_ascii=False))
    (root/(label+'-native.json')).write_text(json.dumps(evidence,ensure_ascii=False))
    print('PASS',label,result['turn_count'],flush=True);return result


def directive(s,uid,kind,point):
    s['command_state']=commands.replace_queue(s,[dict(unit_id=uid,action='move',duration='until_arrived',participation=kind,destination=point)],control_team='red',director=True,no_fire=False,intent='QA临时出入，原任务保留')


try:
    if args.resume:
        saved=json.loads((root/'wait-session.json').read_text());meta=json.loads((root/'case.json').read_text());uid,task=meta['unit_id'],meta['task_id']
        commands.validate_saved(saved);assert saved['turn_count']==3
        directive(saved,uid,'reenter',meta['route']['inside']);back=step(saved,'return');final=step(back,'resumed-original-task')
        runtime=final['command_state']['task_plans'][task]['execution'];assert runtime['member_states'][uid]['executions']==2
        member=commands.resolve_units(final)[uid][1];assert up.unit_view(final['war_state'],member)['status']=='deployed'
        original=json.loads((root/'original-task-session.json').read_text());assert member['personnel']==commands.resolve_units(original)[uid][1]['personnel']
        result=dict(passed=True,actual_native_turns=5,original_task_executions=2,fresh_process_resume=True,
            source_entities=6,scope='Explicit QA: original task pauses outside and resumes after actual return; no full historical acceptance')
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result),flush=True)
    else:
        source,p=inputs();p['clock']['time_step']='6小时';w=ho.initial(source,p)
        s=dict(id='native-boundary-original-task',war_state=w,time_step='6小时',turn_count=0,role_epoch=0,product_mode='historical',simulation_mode='open',execution_backend='afsim')
        uid=next(i for i,(_,u) in commands.resolve_units(s).items() if u['historical_unit_id']=='ww2.cn.division159')
        s['force_organization']=forces.detach(s,[uid],'边界原任务群','临时QA配属')
        group=s['force_organization']['groups'][-1]['id'];task=register(s,group,None,execution('边界原任务',finish=dict(kind='turn',end_turn=100,minimum_executions=20)),kind='defend')
        s=step(s,'original-task');assert s['command_state']['task_plans'][task]['execution']['member_states'][uid]['executions']==1
        route=p['operation_boundary']['routes'][0];directive(s,uid,'withdraw',route['outside']);s=step(s,'exit');s=step(s,'wait')
        assert up.unit_view(s['war_state'],commands.resolve_units(s)[uid][1])['status']=='offmap'
        runtime=s['command_state']['task_plans'][task]['execution'];assert runtime['member_states'][uid]['executions']==1
        assert runtime['member_states'][uid]['status']=='blocked'
        (root/'case.json').write_text(json.dumps(dict(unit_id=uid,task_id=task,route=route)))
        harness_engine.close_harness()
        subprocess.run([sys.executable,__file__,'--live','--resume'],check=True,env=os.environ.copy())
finally:harness_engine.close_harness()
