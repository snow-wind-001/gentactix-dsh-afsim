"""Actual AFSIM comparisons for phase handoff and declared LOS. QA inputs only."""
import argparse
import copy
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();root=args.out.resolve();root.mkdir(parents=True,exist_ok=True)
    for key,suffix in [('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import afsim_world,afsim_rules,harness_engine,runtime_bridge
    from backend.main import _native_tool_dispatch
    from gentactix import missions,sim_clock,historical_operations as ho,phase_continuity
    from tools.qa.historical_operational_fixture import inputs
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    evidence=[]
    def native(label,before,orders,seconds=1800):
        saved=copy.deepcopy(before);scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        positions,proof=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(proof['native_effects'],scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟')
        missions.validate(after);assert before==saved
        (root/(label+'.json')).write_text(json.dumps({'before':before,'after':after,'evidence':proof},ensure_ascii=False))
        evidence.append({'label':label,'returncode':proof['returncode']})
        return after
    try:
        snap,p=inputs();p['actors']['ww2.jp.seya_detachment']['position']['lat']=34.55628
        orders=[{'unit':'第31师','action':'fire','target':'濑谷支队'},
                {'unit':'濑谷支队','action':'move','lat':34.563,'lng':117.73917}]
        initial=ho.initial(snap,p)
        names=[u['name'] for _,u in missions.units(initial)]
        # Use exact names from the frozen identities rather than guessed aliases.
        orders[0].update(unit=initial['red_units'][0]['name'],target=initial['blue_units'][0]['name'])
        orders[1]['unit']=initial['blue_units'][0]['name']
        clear=native('clear-los',initial,orders)
        p['terrain_model']={'version':'local-terrain-1','assumption':'QA障碍，不是史实山脊',
            'barriers':[{'id':'qa-ridge','a':{'lat':34.558,'lng':117.73},'b':{'lat':34.558,'lng':117.75},
                         'blocks':['direct_fire'],'source':'QA几何测试'}],'roads':[]}
        blocked=native('blocked-los',ho.initial(snap,p),orders)
        a=clear['red_units'][0]['formation']['last_execution'];b=blocked['red_units'][0]['formation']['last_execution']
        assert b['fire_cycles']<a['fire_cycles'] and b['fire_stop_reason']==11,(a,b)
        stage=native('phase-end',blocked,[])
        assert stage['mission']['status']=='completed'
        target=copy.deepcopy(p);target['clock']['start']=stage['current_time']
        binding={'format':ho.FORMAT,'initial':snap,'parameters':target}
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(stage,binding)))
        for key in ('personnel','equipment','logistics'):
            assert child['blue_units'][0][key]==stage['blue_units'][0][key]
        assert child['combined_arms']['depots']==stage['combined_arms']['depots']
        continued=native('continued-turn',child,[])
        from tools.qa.campaign_fixture import inputs as campaign_inputs
        cs,cp=campaign_inputs();cw=ho.initial(cs,cp)
        cw=native('campaign-damage',cw,[{'unit':cw['red_units'][0]['name'],'action':'bombard','target':cw['blue_units'][0]['name']}])
        cw=native('campaign-end',cw,[])
        enemy=cw['blue_units'][0]['name'];integrity=cw['campaign']['actors'][enemy]['fortification_integrity']
        assert integrity<100
        cp['clock']['start']=cw['current_time']
        for row in cp['campaign']['arrivals'].values():row['not_before']=cw['current_time'].replace(' ','T')
        cd=phase_continuity.definition(phase_continuity.bind(cw,{'format':ho.FORMAT,'initial':cs,'parameters':cp}))
        cc=missions.from_definition(cd)
        assert cc['campaign']['actors'][enemy]['fortification_integrity']==integrity
        cc=native('campaign-continued',cc,[])
        assert cc['campaign']['actors'][enemy]['fortification_integrity']==integrity
        result={'passed':True,'native_runs':evidence,'clear_fire_cycles':a['fire_cycles'],
            'blocked_fire_cycles':b['fire_cycles'],'blocked_reason':b['fire_stop_reason'],
            'phase_losses_preserved':True,'continued_turn':continued['mission']['turn'],
            'fortification_integrity_carried':integrity,
            'scope':'QA calculation parameters over historical identities; not historical terrain or casualty calibration'}
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
    finally:harness_engine.close_harness()


if __name__=='__main__':main()
