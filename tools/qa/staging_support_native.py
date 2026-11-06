"""Real native contrasts for allowed waiting-stage support and command delay."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--native',action='store_true')
    p.add_argument('--config',type=Path,required=True);args=p.parse_args()
    if not args.native:p.error('--native required')
    root=Path('.cache/qa/staging-support-native-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from tools.qa.campaign_fixture import inputs
    from backend import afsim_world,afsim_rules,afsim_state,afsim_comparison,harness_engine as h,runtime_bridge
    from backend.main import _native_tool_dispatch
    from gentactix import historical_operations as ho,missions,sim_clock,campaign
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    result={'passed':False,'cases':[],'scope':'QA waiting-stage orders; no historical outcomes or LLM planning'}
    try:
        cases=[(action,delay,False) for action,delay in [('recon',0),('recon',4000),('restore_comms',0),('restore_comms',4000),('resupply',0),('resupply',4000),('hold',0)]]
        cases += [('resupply',0,True),('resupply',4000,True)]
        for action,delay,motorized in cases:
            s,p=inputs();p['rules'].update(command_base_s=delay,command_signal_s=0,command_distance_s_per_km=0,motorized=False)
            for a in p['actors'].values():
                a['ground_control_radius_km']=0
                a['formation'].update(motorized=False,signal=40,intel_confidence=30)
            identity='ww2.jp.sakamoto_detachment';a=p['actors'][identity]
            a['equipment']['transport']=20;a['logistics'].update(food=30,ammo=30)
            p['support']['blue'].update(position=copy.deepcopy(a['position']),stock=1000)
            if motorized:
                a['formation'].update(motorized=True,fuel_liters=0)
                p['support']['blue']['position']['lat']+=.005
            before=ho.initial(s,p);frozen=copy.deepcopy(before);unit=next(u for u in before['blue_units'] if u['historical_unit_id']==identity)
            order={'unit':unit['name'],'action':action};campaign.check_order(before,order)
            scene=afsim_world.compile_scene(before,[order],1800,native_rules=True)
            with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')),patch.object(h,'get_ai_response',side_effect=AssertionError('No LLM')):
                positions,evidence=afsim_world.run_scene({},scene)
                after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,afsim_world.apply_observations(before,positions,scene))
            after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence;missions.validate(after)
            current=next(u for u in after['blue_units'] if u['name']==unit['name'])
            execution=current['formation']['last_execution'];ledger=next(r for r in after['mission']['ledger'] if r['unit']==unit['name'])
            checks={'input_unchanged':before==frozen,'still_waiting':not after['campaign']['actors'][unit['name']]['active'],
                'no_early_movement':(current['lat'],current['lng'])==(unit['lat'],unit['lng']),
                'delivery_respects_delay':execution['command_done']==int(delay<1800),
                'command_revision_recorded':evidence['command_control_revision']==2}
            if action=='resupply':
                checks['resupply_bonus_requires_delivery']=abs(ledger['delivery']-(8 if delay<1800 else 0 if motorized else 2))<.001
                checks['special_cargo_requires_delivery']=all((execution['received_'+k]>0) if delay<1800 else execution['received_'+k]==0 for k in ('spares','materials'))
                if motorized:checks['fuel_support_respects_delay']=(execution['received_fuel_liters']>0) if delay<1800 else after['combined_arms']['depots']['blue']['fuel_liters']==before['combined_arms']['depots']['blue']['fuel_liters']
            if action=='restore_comms':checks['signal_respects_delay']=current['formation']['signal']==(65 if delay<1800 else 40)
            if action=='recon':checks['recon_respects_delay']=(current['formation']['intel_confidence']>80) if delay<1800 else current['formation']['intel_confidence']<=30
            session={'id':'staging-qa','war_state':after,'turn_count':1,'time_step':'30分钟','execution_backend':'afsim'}
            observation=afsim_state.observation(session,{'detail':True,'limit':16})
            observed=next(u for u in observation['units'] if u['name']==unit['name'])
            checks['dsh_observes_waiting_support']=observed['arrival']['status']=='staging' and observed['formation']['last_execution']['command_done']==execution['command_done']
            row={'case':f'{action}-{delay}'+('-motorized' if motorized else ''),'checks':checks,'execution':execution,'ledger':ledger,'native':evidence}
            result['cases'].append(row);(root/(row['case']+'.json')).write_text(json.dumps({'before':before,'after':after},ensure_ascii=False,indent=2))
            print(json.dumps({'case':row['case'],'checks':checks},ensure_ascii=False),flush=True)
        baseline=json.loads((root/'hold-0.json').read_text())
        session={'war_state':copy.deepcopy(baseline['after']),'time_step':'30分钟'}
        saved=copy.deepcopy(session)
        name=next(u['name'] for u in baseline['before']['blue_units'] if u['historical_unit_id']==identity)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')),patch.object(h,'get_ai_response',side_effect=AssertionError('No LLM')):
            counterfactual=afsim_comparison.compare(session,{**baseline,'time_step':'30分钟'},[{'unit':name,'action':'resupply'}])
        row=next(r for r in counterfactual['alternative']['mission']['ledger'] if r['unit']==name)
        result['counterfactual_checks']={'same_revision':counterfactual['external_execution']['command_control_revision']==2,
            'resupply_changes_delivery':row['delivery']==8 and next(r for r in baseline['after']['mission']['ledger'] if r['unit']==name)['delivery']==2,
            'read_only':session==saved}
        (root/'counterfactual.json').write_text(json.dumps(counterfactual,ensure_ascii=False,indent=2))
        result['passed']=all(all(r['checks'].values()) for r in result['cases']) and all(result['counterfactual_checks'].values())
    finally:
        h.close_harness();(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(root,flush=True)
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
