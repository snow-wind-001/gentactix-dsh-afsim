"""Real AFSIM: blocked route, actual clearing move, recovery and starvation death."""
import argparse
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--root',type=Path,required=True);args=p.parse_args()
    if not args.live:p.error('--live required')
    root=args.root;root.mkdir(exist_ok=False)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import afsim_world,afsim_rules,harness_engine
    from gentactix import missions,historical_operations as ho,sim_clock
    from verify_supply_geometry import sample,holds
    result=dict(passed=False,actual_afsim=True,live_model_calls=False,cases=[],historical_calibration=False)
    def run(label,before,orders,*,reverse_compilation=False,seconds=3600):
        original=copy.deepcopy(before)
        # Only enumerate the same actors in reverse while compiling. No state,
        # identity, command or physical rule changes in this order-invariance test.
        units=missions.units
        if reverse_compilation:
            with patch.object(missions,'units',side_effect=lambda w:list(reversed(units(w)))):
                scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        else:scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physical fallback')):
            positions,evidence=afsim_world.run_scene({},scene)
            telemetry=evidence.pop('native_effects')
            after=afsim_rules.apply_telemetry(telemetry,scene['native_model'],scene,afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,before['mission']['definition']['time_step'])
        missions.evaluate(after);missions.validate(after);assert before==original
        (root/(label+'.json')).write_text(json.dumps(dict(before=before,after=after,native=evidence),ensure_ascii=False,indent=2)+'\n')
        result['cases'].append(dict(label=label,returncode=evidence['returncode']))
        print('PASS',label,flush=True);return after
    try:
        source,params=sample(parameters_only=True)
        params['goal'].update(required_turns=10,deadline_turn=30,termination_mode='objectives')
        params['goal']['objective']={'lat':params['area']['center']['lat']+.02,'lng':params['area']['center']['lng']}
        world=ho.initial(source,params);blocked=run('blocked-first-hour',world,holds(world))
        red=blocked['red_units'][0];assert next(r for r in blocked['mission']['ledger'] if r['unit']==red['name'])['food_received']==0
        enemy=next(u for u in blocked['blue_units'] if u['historical_unit_id']=='ww2.jp.seya_detachment')
        node=next(n for n in blocked['supply_nodes'] if n['id']==red['supply_node_id']);axis='lng' if abs(red['lat']-node['lat'])>abs(red['lng']-node['lng']) else 'lat'
        point={k:enemy[k] for k in ['lat','lng']};point[axis]+=.006 if axis=='lng' else .004
        orders=holds(blocked);next(o for o in orders if o['unit']==enemy['name']).update(action='move',**point)
        cleared=run('actual-blocker-clearing-move',blocked,orders)
        recovered=run('supply-after-clearing',cleared,holds(cleared))
        assert next(r for r in recovered['mission']['ledger'] if r['unit']==red['name'])['food_received']>0
        source,params=sample(blocked=False,parameters_only=True)
        params['actors']['ww2.cn.division31']['personnel']=1
        params['support_dynamics'].update(incapacity_after_hours=1,incapacity_fraction_per_hour=.1)
        world=ho.initial(source,params);unit=world['red_units'][0];unit['sustainment'].update(shortage_hours=2,noncombat_remainder=.95)
        dead=run('intra-step-noncombat-death',world,holds(world))
        unit=dead['red_units'][0];assert unit['personnel']['current']==0
        assert next(r for r in dead['mission']['ledger'] if r['unit']==unit['name'])['food_received']==0
        projections=[]
        for reverse in (False,True):
            source,params=sample(parameters_only=True)
            params['actors']['ww2.jp.seya_detachment']['personnel']=1
            params['support_dynamics'].update(incapacity_after_hours=1,incapacity_fraction_per_hour=.1)
            world=ho.initial(source,params)
            enemy=next(u for u in world['blue_units'] if u['historical_unit_id']=='ww2.jp.seya_detachment')
            enemy['sustainment'].update(shortage_hours=2,noncombat_remainder=.95)
            cleared=run('incapacitated-blocker-'+('reversed' if reverse else 'normal'),world,holds(world),reverse_compilation=reverse)
            enemy=next(u for u in cleared['blue_units'] if u['historical_unit_id']=='ww2.jp.seya_detachment')
            assert enemy['personnel']['current']==0
            assert next(r for r in cleared['mission']['ledger'] if r['unit']==cleared['red_units'][0]['name'])['food_received']>0
            projections.append({u['historical_unit_id']:dict(personnel=u['personnel'],food=u['logistics']['food'],
                nutrition=u['sustainment']['last_receipt']) for _,u in missions.units(cleared)})
        assert projections[0]==projections[1],'Dead control must not depend on compilation roster order'
        result['incapacitated_control_order_independent']=True
        from gentactix import fire_process
        for step in ('15分钟','1小时','6小时'):
            source,params=sample(blocked=False,parameters_only=True)
            params['actors']['ww2.cn.division31']['formation']['suppression']=65
            params['clock']['time_step']=step;seconds=sim_clock.duration_seconds(step)
            world=ho.initial(source,params);quiet=run('quiet-suppression-'+str(seconds)+'s',world,holds(world),seconds=seconds)
            expected=fire_process.quiet_suppression_after(world,world['red_units'][0],seconds)
            assert quiet['red_units'][0]['formation']['suppression']==expected
        result['quiet_suppression_reference_matches_native']=True
        result['passed']=True
    except Exception as exc:
        result['error']=str(exc);raise
    finally:
        harness_engine.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
