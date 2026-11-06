"""Normal isolated API / Native DSH timed supply; fixed QA inputs, no executor."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid

from . import force_task_execution_live as api

ROOT=Path('.cache/qa/personnel-continuity-2026-11-03')


def save(name,value):
    p=ROOT/'dsh-supply'/name;p.parent.mkdir(exist_ok=True)
    if p.exists():raise ValueError('Preserve evidence: '+str(p))
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def stage():
    assert not (ROOT/'dsh-supply/stage.json').exists()
    folder=(ROOT/'api').resolve()
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(folder/suffix)
    from backend import scenario_builder
    from verify_supply_geometry import sample
    source,p=sample(parameters_only=True)
    p['goal'].update(required_turns=10,deadline_turn=30,termination_mode='objectives')
    p['goal']['objective']={'lat':p['area']['center']['lat']+.02,'lng':p['area']['center']['lng']}
    draft=scenario_builder.stage_historical(source,p,construction=dict(source='dsh_native_skill',qa_fixed_input=True,
        explanation='Explicit fixed software QA inputs for timed delivery/control. Not model-generated or historical deployment/rations.'),execution_backend='narrative')
    save('stage.json',dict(draft_id=draft['id'],battle=source['definition']['battle'],parameters=p))
    print('PASS staged fixed QA parameters via existing closed validator; NO model call',flush=True)


def run(*,quiet=False):
    stage=json.loads((ROOT/'dsh-supply/stage.json').read_text())
    assert not (ROOT/'dsh-supply/case.json').exists()
    parent=stage['draft_id']
    if quiet:
        parameters=copy.deepcopy(stage['parameters'])
        parameters['actors']['ww2.cn.division31']['formation']['suppression']=65
        revised=api.call('POST','/historical-scenarios/validate',dict(parent_draft_id=parent,parameters=parameters,
            required_models=['personnel-rations-1','scheduled-supply-1'],execution_backend='narrative'))
        save('validated-stage.json',revised);parent=revised['id']
    draft=api.call('POST','/scenarios/from-historical',dict(base_draft_id=parent,execution_backend='narrative'))['draft']
    created=api.call('POST','/sessions',dict(scenario='定时补给断供、实际撤离控制区与恢复QA；固定估计参数，非历史过程',battle=stage['battle'],
        product_mode='synthetic',scenario_draft_id=draft['id'],synthetic_configuration=draft['configuration'],
        execution_backend='narrative',simulation_mode='open',time_step='1小时',agent_mode='native',persist_roles=True))
    sid=created['session_id'];base='/sessions/'+sid
    api.call('POST',base+'/init');save('case.json',dict(session_id=sid,api='http://127.0.0.1:'+str(api.PORT)))
    result=dict(passed=False,session_id=sid,actual_native_dsh=True,fixed_qa_parameters=True,historical_calibration=False,quiet_suppression=quiet,turns=[])
    try:
        for turn in range(1,4):
            before=api.call('GET',base+'/export')['session'];w=before['war_state'];v=api.call('GET',base+'/commands')
            orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in v['units'] if u['available']]
            if turn==2:
                enemy=next(u for u in w['blue_units'] if u.get('source_historical_unit_id',u.get('historical_unit_id'))=='ww2.jp.seya_detachment')
                red=w['red_units'][0];node=next(n for n in w['supply_nodes'] if n['id']==red['supply_node_id'])
                axis='lng' if abs(red['lat']-node['lat'])>abs(red['lng']-node['lng']) else 'lat'
                point={k:enemy[k] for k in ('lat','lng')};point[axis]+=.006 if axis=='lng' else .004
                identity=next(u['id'] for u in v['units'] if u['name']==enemy['name'])
                next(o for o in orders if o['unit_id']==identity).update(action='move',destination=point)
            elif turn==3:
                identity=next(u['id'] for u in v['units'] if u['name']==w['red_units'][0]['name'])
                next(o for o in orders if o['unit_id']==identity)['action']='resupply'
            api.call('PUT',base+'/commands',dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],
                orders=orders,control_team='red',director=True,no_fire=True,unit_agents=[],
                intent='按确认命令与固定周期服务推演；先结算间隔耗粮，再核对本时点实际控制区。无交战，不补满人员。'
                '通道被敌军切断不得到货；通道恢复且有库存载重时执行已启用的补给服务，不虚构车队或道路。'))
            current=api.call('GET',base+'/commands');start=time.monotonic()
            response=api.call('POST',base+'/next',dict(expected_turn=current['turn'],revision=current['revision'],world_version=current['world_version'],
                batch_id=uuid.uuid4().hex,instruction='独立DSH定时补给QA。严格提交逐时点supply_schedule_ledger、总保障与资源账，先耗用后到货，实际执行确认命令；没有战斗损失。'))
            after=api.call('GET',base+'/export')['session'];save('turn-'+str(turn)+'.json',dict(before=before,after=after,engine_meta=response['engine_meta']))
            assert after['turn_count']==turn and after['war_state']['simulation_clock']['elapsed_seconds']==turn*3600
            assert after['war_state']['dsh_execution']['effects_source']=='dsh_model_estimate' and not after['war_state'].get('afsim')
            red=after['war_state']['red_units'][0];receipt=next(r for r in after['war_state']['mission']['ledger'] if r['unit']==red['name'])
            if quiet:
                from gentactix import fire_process
                assert red['formation']['suppression']==fire_process.quiet_suppression_after(w,w['red_units'][0],3600)
            if turn==1:assert receipt['food_received']==0
            if turn==3:assert receipt['food_received']>0
            for team in ('red','blue'):
                old={u['name']:u for u in w[team+'_units']}
                for u in after['war_state'][team+'_units']:
                    assert u['personnel']['current']==old[u['name']]['personnel']['current']
                    row=next(r for r in after['war_state']['mission']['ledger'] if r['unit']==u['name'])
                    assert abs(u['logistics']['food']-old[u['name']]['logistics']['food']-row['food_received']+row['food_spent'])<1e-6
            result['turns'].append(dict(turn=turn,red_food_received=receipt['food_received'],seconds=round(time.monotonic()-start,3)))
            print('PASS actual Native DSH supply T'+str(turn),result['turns'][-1],flush=True)
        result['passed']=True
    except Exception as exc:
        result['error']=str(exc);raise
    finally:save('result.json',result)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['stage','run']);p.add_argument('--live',action='store_true');p.add_argument('--quiet',action='store_true');args=p.parse_args()
    if not args.live:p.error('--live required')
    api.ROOT=ROOT;api.PORT=19368
    if args.mode=='stage':stage()
    else:run(quiet=args.quiet)


if __name__=='__main__':main()
