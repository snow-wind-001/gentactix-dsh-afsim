"""Real AFSIM test: a three-level command tree moves unique leaves only."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Pass --live for real AFSIM')
    root=Path('.cache/qa/force-hierarchy-2026-10-31/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),
                       ('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from gentactix import historical_operations as ho,force_organization as f,commands,missions,sim_clock
    from backend import afsim_world,afsim_rules,harness_engine
    from tools.qa.large_formation_fixture import inputs
    snapshot,p=inputs();world=ho.initial(snapshot,p)
    s=dict(id='hierarchy-native-qa',war_state=world,time_step='30分钟',turn_count=0,
        role_epoch=0,product_mode='historical',simulation_mode='open',execution_backend='afsim')
    result={'passed':False,'scope':'79 sourced identities, numerical QA; no historical reconstruction'}
    try:
        ids=[i for i,(e,_) in commands.resolve_units(s).items() if e['team']=='red'][:12]
        s['force_organization']=f.detach(s,ids,'方向总指挥','QA保留12个执行叶子')
        top=s['force_organization']['groups'][0]['id']
        s['force_organization']=f.detach(s,ids[:6],'突击群','QA下级任务群',parent_id=top)
        child=next(g['id'] for g in f.state(s)['groups'] if g['label']=='突击群')
        s['force_organization']=f.detach(s,ids[:3],'先遣群','QA三级任务群',parent_id=child)
        s['command_state']=f.queue(s,top,dict(action='move',duration='until_arrived',
            destination={'lat':30.61,'lng':114.31}))
        orders=[commands.step_order(s,o) for o in commands.state(s)['orders']]
        assert len(orders)==12 and len({o['unit'] for o in orders})==12
        before=copy.deepcopy(s);t0=time.monotonic()
        scene=afsim_world.compile_scene(world,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Native engine required')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(world,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(world,'30分钟')
        (root/'before-after.json').write_text(json.dumps({'before':world,'after':after},ensure_ascii=False))
        missions.validate(after);assert s==before
        selected={o['unit'] for o in orders};moved=[]
        old={u['name']:u for _,u in missions.units(world)}
        for _,u in missions.units(after):
            distance=missions.distance(old[u['name']],u)
            if u['name'] in selected:
                assert .001<distance<=missions.move_budget(world,old[u['name']])+1e-5
                moved.append(u['name'])
            else:assert distance<.001
            for key in ('committed','current','casualties','noncombat_losses'):
                assert u['personnel'][key]==old[u['name']]['personnel'][key],(u['name'],key)
        s['war_state']=after;s['turn_count']=1;f.validate(s)
        assert len(f.member_ids(s,top))==12 and len(f.member_ids(s,child))==6
        (root/'world.json').write_text(json.dumps(after,ensure_ascii=False))
        result.update(passed=True,units=79,selected=12,moved=len(moved),unselected_held=67,
            command_levels=3,seconds=round(time.monotonic()-t0,3),engine=evidence)
        print('PASS 3-level HQ dispatched 12 unique native moves; 67 stayed; personnel unchanged',flush=True)
    finally:
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        harness_engine.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
