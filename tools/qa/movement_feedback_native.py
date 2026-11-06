"""Actual isolated AFSIM motion receipts; no LLM or Python effect execution."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--case',choices=('ground','crossing','delayed-crossing','ferry','motor-ferry','network','all'),default='all')
    args=parser.parse_args()
    if not args.live:parser.error('--live required for actual native process')
    root=args.out
    if (root/'result.json').exists():parser.error('Preserve existing results')
    root.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import afsim_world,afsim_rules,harness_engine as h
    from gentactix import commands,missions,movement_feedback as mf,historical_operations as ho,sim_clock
    from verify_movement_feedback import world,CONFIG
    from unittest.mock import patch
    result=dict(passed=False,actual_afsim=True,actual_model=False,cases=[],
        scope='Versioned computational movement/fatigue/transport constraints, not historical strengths or terrain calibration')
    def save():(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def run(label,before,orders):
        seconds=sim_clock.duration_seconds(before['mission']['definition']['time_step'])
        scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        assert scene['motion_revision']==11
        (root/(label+'-scene.afsim')).write_text(scene['script'])
        (root/(label+'-before.json')).write_text(json.dumps(before,ensure_ascii=False,indent=2))
        began=time.monotonic();positions,evidence=afsim_world.run_scene({},scene)
        (root/(label+'-native.json')).write_text(json.dumps(dict(positions=positions,evidence=evidence),ensure_ascii=False,indent=2))
        after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,before['mission']['definition']['time_step'])
        missions.evaluate(after);missions.validate(after)
        receipt=after['combined_arms']['movement_feedback']
        row=dict(label=label,seconds=round(time.monotonic()-began,3),actors=len(missions.units(after)),
            movement=receipt,evidence=evidence,
            units=[dict(unit=u['name'],lat=u['lat'],lng=u['lng'],fatigue=u['formation']['fatigue'],
                fuel=u['formation']['fuel_liters'],crossing=u.get('crossing')) for _,u in missions.units(after)])
        result['cases'].append(row)
        (root/(label+'-before.json')).write_text(json.dumps(before,ensure_ascii=False,indent=2))
        (root/(label+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2))
        save();print('PASS NATIVE',label,'actors',row['actors'],'seconds',row['seconds'],flush=True)
        return after
    def orders(w,name,target):
        return [dict(unit=u['name'],action='move',**target) if u['name']==name else dict(unit=u['name'],action='hold') for _,u in missions.units(w)]
    try:
        if args.case in ('all','ground'):
            w=world();u=w['red_units'][0];target=dict(lat=u['lat']+.05,lng=u['lng'])
            step=commands.towards(u,target,mf.command_budget(w,u,target))
            run('ground-fatigue',w,orders(w,u['name'],step))
            w=world();u=w['red_units'][0];u['formation']['fuel_liters']=1
            step=commands.towards(u,target,mf.command_budget(w,u,target))
            run('fuel-one-liter',w,orders(w,u['name'],step))
            from tools.qa.historical_operational_fixture import inputs
            snapshot,parameters=inputs();parameters['movement_feedback']=copy.deepcopy(CONFIG)
            u0=next(iter(parameters['actors'].values()));p=u0['position']
            parameters['terrain_model']=dict(version='local-terrain-1',assumption='QA直线道路，不是已核历史路线。',barriers=[],
                roads=[dict(id='qa-road',a=dict(lat=p['lat']-.05,lng=p['lng']),b=dict(lat=p['lat']+.05,lng=p['lng']),
                    width_m=50,speed_factor=2,source='QA道路加速先验')])
            w=ho.initial(snapshot,parameters);u=w['red_units'][0];target=dict(lat=u['lat']+.05,lng=u['lng'])
            step=commands.towards(u,target,mf.command_budget(w,u,target))
            run('road-bonus',w,orders(w,u['name'],step))
        for case in ('crossing','delayed-crossing','network'):
            if args.case not in ('all',case):continue
            from verify_afsim_crossing import fixture as crossing_fixture
            from verify_crossing_network import fixture as network_fixture
            spec=network_fixture() if case=='network' else crossing_fixture()
            if case=='delayed-crossing':
                spec['combined_rules']['command_base_s']=2.5
                spec['initial_state']['red_units'][0]['formation']['fatigue']=10
                spec['initial_state']['combined_arms']['rules_hash']=missions.digest(spec['combined_rules'])
            spec['movement_feedback']=copy.deepcopy(CONFIG);original=missions.definition
            with patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(spec) if i==spec['id'] else original(i)):
                w=missions.from_definition(spec);u=w['red_units'][0]
                target=dict(lat=u['lat']+.004,lng=u['lng']) if case=='network' else dict(lat=27.303,lng=107.4)
                w=run(case+'-queue',w,orders(w,u['name'],target))
                for continuation in range(2,5):
                    current=next(v for _,v in missions.units(w) if v['name']==u['name'])
                    if current.get('crossing',{}).get('status')=='completed':break
                    w=run(case+'-continuation-'+str(continuation),w,orders(w,u['name'],target))
                assert next(v for _,v in missions.units(w) if v['name']==u['name']).get('crossing',{}).get('status')=='completed',case+' full route not completed'
        if args.case in ('all','ferry','motor-ferry'):
            from verify_ferries import ferry_inputs
            snapshot,p=ferry_inputs();p['movement_feedback']=copy.deepcopy(CONFIG)
            p['rules'].update(command_base_s=0,command_signal_s=0,command_distance_s_per_km=0)
            if args.case=='motor-ferry':
                from verify_movement_feedback import motor_ferry_world
                w=motor_ferry_world()
            else:w=ho.initial(snapshot,p)
            u=next(u for _,u in missions.units(w) if u.get('calculation_unit_id') and u['personnel']['committed']==5)
            bank=w['combined_arms']['bridge']['crossing_model']['banks']['b']
            for i in range(1,13):
                if w['mission']['status']=='completed':break
                current=next(v for _,v in missions.units(w) if v['name']==u['name'])
                from gentactix import ferries
                budget=mf.command_budget(w,current,bank)
                target=ferries.step_target(w,current,bank,budget)
                if target is None:target=commands.towards(current,bank,budget)
                w=run('ferry-'+str(i),w,orders(w,u['name'],target))
                if next(v for _,v in missions.units(w) if v['name']==u['name']).get('crossing',{}).get('status')=='completed':break
            result['ferry_landed']=next(v for _,v in missions.units(w) if v['name']==u['name']).get('crossing',{}).get('status')=='completed'
            assert result['ferry_landed'],'Full boat arrival not yet achieved'
        result['passed']=True;save()
    except Exception as exc:
        result['error']=str(exc);save();raise
    finally:h.close_harness()


if __name__=='__main__':main()
