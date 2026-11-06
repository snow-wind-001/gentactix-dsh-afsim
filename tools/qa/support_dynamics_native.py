"""Real WSF food/deprivation metamorphic checks with no LLM or Python executor."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',action='store_true');parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if not args.native:parser.error('--native is required')
    root=Path('.cache/qa/support-dynamics-native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from verify_support_dynamics import config
    from tools.qa.historical_operational_fixture import inputs
    from gentactix import historical_operations as ho,missions,sim_clock
    from backend import afsim_world,afsim_rules,afsim_state,runtime_bridge,harness_engine as h,afsim_sustainment
    from backend.main import _native_tool_dispatch
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    results={'passed':False,'cases':[],'scope':'Explicit QA sensitivity parameters; not historical/physiological calibration'}

    def seed(food=0,old=False):
        s,p=inputs()
        if not old:p['support_dynamics']=config()
        p['goal']['deadline_turn']=8
        for actor in p['actors'].values():
            actor['logistics']['food']=food;actor['formation']['fatigue']=0;actor['ground_control_radius_km']=0
        for node in p['support'].values():node['stock']=0
        return ho.initial(s,p)

    def run(name,before,seconds):
        frozen=copy.deepcopy(before);scene=afsim_world.compile_scene(before,[],seconds,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')),patch.object(h,'get_ai_response',side_effect=AssertionError('No LLM')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,str(seconds//60)+'分钟')
        after['afsim']=evidence;missions.validate(after)
        observation=afsim_state.observation({'id':'time-support-qa','war_state':after,'time_step':str(seconds//60)+'分钟','turn_count':after['mission']['turn']},{'detail':True})
        checks={'source_unchanged':before==frozen,'native_success':evidence['returncode']==0}
        if not name.startswith('legacy'):
            checks['dsh_observes_receipts']=all(next(x for x in observation['units'] if x['name']==u['name'])['sustainment']==u['sustainment'] for _,u in missions.units(after))
            try:afsim_sustainment.parse('',scene['native_model'],scene)
            except ValueError:checks['missing_receipt_rejected']=True
            else:checks['missing_receipt_rejected']=False
        (root/(name+'.json')).write_text(json.dumps({'before':before,'after':after},ensure_ascii=False,indent=2))
        results['cases'].append({'name':name,'checks':checks,'native':evidence})
        print(json.dumps({'case':name,'checks':checks}),flush=True)
        return after

    try:
        full=run('one-hour',seed(),3600)
        half=run('half-hour',seed(),1800);split=run('two-half-hours',half,1800)
        threshold=seed()
        for _,u in missions.units(threshold):u['sustainment']['shortage_hours']=47.75
        extended=run('threshold-one-hour',threshold,3600)
        partial=run('threshold-half-hour',threshold,1800);extended_split=run('threshold-two-half-hours',partial,1800)
        fraction=run('fractional-food',seed(.5),900)
        fed=seed(50)
        for _,u in missions.units(fed):u['sustainment']['shortage_hours']=3
        recovery=run('fed-recovery',fed,1800)
        mixed=seed(1)
        for _,u in missions.units(mixed):u['sustainment']['shortage_hours']=49
        mixed_full=run('mixed-hour',mixed,3600)
        mixed_first=run('mixed-quarter',mixed,900);mixed_split=run('mixed-three-quarters',mixed_first,2700)
        legacy=run('legacy-empty-food',seed(old=True),1800)
        a=full['red_units'][0];b=split['red_units'][0];c=extended['red_units'][0];d=extended_split['red_units'][0]
        results['checks']={'shortage_not_immediate_casualties':a['personnel']['noncombat_losses']==0,
            'equal_elapsed_time_equal_debt':a['sustainment']['shortage_hours']==b['sustainment']['shortage_hours']==1,
            'equal_elapsed_time_equal_fatigue':a['formation']['fatigue']==b['formation']['fatigue']==2,
            'threshold_split_loss_invariant':c['personnel']['noncombat_losses']==d['personnel']['noncombat_losses'],
            'threshold_split_carry_invariant':abs(c['sustainment']['noncombat_remainder']-d['sustainment']['noncombat_remainder'])<1e-6,
            'fractional_food_shortage':fraction['red_units'][0]['sustainment']['shortage_hours']==.125,
            'fed_recovers_debt':recovery['red_units'][0]['sustainment']['shortage_hours']==2.5,
            'mixed_feeding_split_invariant':all(mixed_full['red_units'][0]['sustainment'][k]==mixed_split['red_units'][0]['sustainment'][k] for k in ('shortage_hours','noncombat_remainder')),
            'old_rules_preserved':legacy['red_units'][0]['personnel']['noncombat_losses']==2 and 'sustainment' not in legacy['red_units'][0]}
        results['passed']=all(results['checks'].values()) and all(all(r['checks'].values()) for r in results['cases'])
    finally:
        (root/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        print(str(root/'result.json'),flush=True)
    if not results['passed']:raise AssertionError(results.get('checks'))


if __name__=='__main__':main()
