"""Actual AFSIM differential paths for four sourced armies with explicit QA loads."""
import argparse
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--root',type=Path,default=Path('.cache/qa/transfer-window-2026-11-03/native'))
    args=parser.parse_args()
    if not args.live:parser.error('--live required for actual WSF execution')
    root=args.root
    if root.exists():raise SystemExit('Preserve existing native evidence')
    root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from backend import afsim_world, afsim_rules, harness_engine
    from gentactix import historical_operations as ho, missions, sim_clock, commands
    from tools.qa.transfer_campaign_fixture import campaign_inputs, NOTE
    initial=ho.initial(*campaign_inputs());results=[]
    def run(label,before,moving):
        previous=copy.deepcopy(before)
        plan=before['mission']['definition']['campaign_plan']
        targets={n['unit_ids'][0]:n['condition']['region']['center'] for n in plan['nodes'] if n['condition']['kind']=='reach'}
        session=dict(id='012345abcdef',war_state=before,turn_count=before['mission']['turn'],time_step='30分钟',simulation_mode='open',execution_backend='afsim')
        cs=commands.state(session);by_name={r['name']:r['id'] for r in cs['registry']}
        orders=[commands.step_order(session,dict(unit_id=by_name[u['name']],action='move',duration='until_arrived',
            destination=targets[u['historical_unit_id']]),cs) if u['historical_unit_id'] in moving
            else dict(unit=u['name'],action='hold') for u in before['red_units']]
        scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
        assert len(scene['entities'])==4
        (root/(label+'.afsim')).write_text(scene['script'])
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physics fallback')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
        # Same host scoring stage as backend.afsim_turns; physical effects above
        # are entirely native and must precede the existing goal evaluator.
        missions.evaluate(after)
        missions.validate(after)
        assert before==previous and after['historical_initial']==before['historical_initial']
        assert after['blue_units']==[] and not after['engagements']
        assert len(after['red_units'])==4 and sum(u['personnel']['current'] for u in after['red_units'])==12000
        assert not any(u['personnel']['casualties'] for u in after['red_units'])
        assert after['campaign_plan']['outcomes']['blue'] is False and after['campaign_plan']['side_progress']['blue']==0
        row=dict(label=label,turn=after['mission']['turn'],status=after['mission']['status'],winner=after['mission']['winner'],
            completed_nodes=[i for i,n in after['campaign_plan']['nodes'].items() if n['status']=='completed'],
            distances_km={u['historical_unit_id']:missions.distance(u,old) for u,old in zip(after['red_units'],before['red_units'])})
        results.append(row)
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
        print(label,row['status'],row['completed_nodes'],flush=True)
        return after
    result=dict(passed=False,actual_afsim=True,actual_model=False,scope=NOTE,cases=results)
    try:
        held=run('same-initial-hold',initial,set())
        assert held['mission']['status']=='active'
        assert all(missions.distance(u,v)<.001 for u,v in zip(held['red_units'],initial['red_units']))
        first=initial['red_units'][0]['historical_unit_id']
        one=run('same-initial-one-axis',initial,{first})
        assert one['mission']['status']=='active' and missions.distance(one['red_units'][0],initial['red_units'][0])>.1
        assert all(missions.distance(u,v)<.001 for u,v in zip(one['red_units'][1:],initial['red_units'][1:]))
        world=copy.deepcopy(initial);identities={u['historical_unit_id'] for u in world['red_units']}
        for n in range(1,9):
            world=run('all-axes-'+str(n),world,identities)
            if world['mission']['status']=='completed':break
        assert world['mission']['winner']=='red'
        assert world['campaign_plan']['side_progress']['red']==2
        assert len(world['campaign_plan']['nodes'])==6
        result['passed']=True
    finally:
        harness_engine.close_harness()
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
