"""Actual native completion-policy comparisons, using explicit QA assumptions."""
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
    for key,suffix in [('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import afsim_world,afsim_rules,harness_engine,runtime_bridge
    from backend.main import _native_tool_dispatch
    from gentactix import missions,sim_clock,historical_operations as ho
    from tools.qa.historical_operational_fixture import inputs
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    evidence=[]
    def run(label,before):
        original=copy.deepcopy(before)
        scene=afsim_world.compile_scene(before,[],1800,native_rules=True)
        positions,proof=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(proof['native_effects'],scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟')
        missions.validate(after);assert before==original
        (root/(label+'.json')).write_text(json.dumps({'before':before,'after':after,'proof':proof},ensure_ascii=False))
        evidence.append({'label':label,'returncode':proof['returncode'],'turn':after['mission']['turn'],'status':after['mission']['status']})
        return after
    def world(mode='objectives',profile='assault',required=2):
        s,p=inputs();p['goal'].update(termination_mode=mode,profile=profile,required_turns=required,deadline_turn=1,radius_km=2)
        p['rules']['goal_profile']=profile
        return ho.initial(s,p)
    try:
        active=world()
        for i in range(3):
            active=run('open-unmet-'+str(i+1),active)
            assert active['mission']['status']=='active'
        old=run('limited-expires',world('deadline',required=1))
        assert old['mission']['status']=='completed' and old['mission']['winner']=='blue'
        success=world()
        # Move the opposing QA initial positions outside the objective circle,
        # preserving their identities, counts and existence in the same scene.
        s,p=inputs();p['goal'].update(termination_mode='objectives',profile='assault',required_turns=2,deadline_turn=1,radius_km=2)
        p['rules']['goal_profile']='assault'
        for identity,row in p['actors'].items():
            if identity.startswith('ww2.jp.'):row['position']['lat']+=.1
        success=ho.initial(s,p)
        success=run('control-first',success);assert success['mission']['status']=='active'
        success=run('control-second',success);assert success['mission']['winner']=='red'
        delay=world(profile='delay',required=3)
        for i in range(3):
            delay=run('delay-'+str(i+1),delay)
            assert delay['mission']['status']==('completed' if i==2 else 'active')
        from tools.qa.campaign_fixture import inputs as campaign_inputs
        s,p=campaign_inputs();p['goal'].update(termination_mode='objectives',deadline_turn=1,required_turns=2,radius_km=2)
        campaign=ho.initial(s,p)
        for i in range(2):
            campaign=run('joint-unmet-'+str(i+1),campaign)
            assert campaign['mission']['status']=='active'
        result={'passed':True,'llm_calls':0,'native_runs':evidence,'scope':'completion mechanics over QA parameters; not historical combat calibration'}
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
    finally:harness_engine.close_harness()


if __name__=='__main__':main()
