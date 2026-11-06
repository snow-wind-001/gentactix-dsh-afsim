"""Opt-in native multi-site acceptance; all geometry is declared QA input."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',action='store_true');p.add_argument('--config',type=Path,required=True)
    args=p.parse_args()
    if not args.native:p.error('--native required')
    root=Path('.cache/qa/crossing-network-native-2026-10-29')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG']=str(args.config.resolve())
    from backend import afsim_world,afsim_rules,runtime_bridge,harness_engine as h
    from backend.main import _native_tool_dispatch
    from gentactix import missions,sim_clock,crossing_network
    from verify_crossing_network import fixture
    runtime_bridge.register_dispatcher(_native_tool_dispatch)
    results=[];passed=False;definitions={}
    original=missions.definition

    def initial(kind):
        spec=fixture();spec['id']='QA-crossing-network-'+kind
        world=spec['initial_state'];sites=[world['combined_arms']['bridge']]+world['combined_arms']['bridge']['crossing_network']['sites']
        if kind in ('closed','build'):sites[1]['progress']=50
        if kind=='build':
            u=world['red_units'][1]
            u['formation'].update(role='engineer',materials=100)
            next(e for e in u['equipment'] if e['category']=='engineer').update(committed=10,operational=10)
        if kind=='cargo':
            for i,u in enumerate(world['red_units'][:2]):
                u.update(lat=27.303,lng=107.4+i*.01)
                u['logistics'].update(food=50,ammo=50)
                next(e for e in u['equipment'] if e['category']=='transport').update(committed=20,operational=20)
            # Symmetric depot makes the nearer respective site the shortest path.
            node=next(n for n in world['supply_nodes'] if n['team']=='red')
            node.update(lat=27.298,lng=107.405,stock=100)
        definitions[spec['id']]=spec
        return missions.from_definition(copy.deepcopy(spec))

    def execute(label,before,orders):
        frozen=copy.deepcopy(before)
        scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
        positions,evidence=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
        missions.validate(after);assert before==frozen
        assert len(positions)==len(missions.units(before))
        for _,u in missions.units(after):
            p=u['personnel'];assert p['current']+p['casualties']+p['noncombat_losses']==p['committed']
            for e in u['equipment']:assert e['operational']+e['damaged']+e['destroyed']==e['committed']
        row={'case':label,'native_source':evidence['source'],'artifact':evidence['artifact'],
             'sites':[{k:s.get(k) for k in ('id','progress','materials','used','crossing_receipt')} for s in crossing_network.sites(after)],
             'units':[{k:u.get(k) for k in ('name','lat','lng','crossing')} for u in after['red_units'][:2]]}
        (root/(label+'.json')).write_text(json.dumps({'before':before,'after':after,'result':row},ensure_ascii=False,indent=2)+'\n')
        results.append(row);print(label,row['sites'],flush=True)
        return after

    def moves(world):
        return [{'unit':u['name'],'action':'move','lat':27.303,'lng':u['lng'],'intent_id':str(i+1)*32}
                for i,u in enumerate(world['red_units'][:2])]

    try:
        with patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(definitions[i]) if i in definitions else original(i)), \
             patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')), \
             patch.object(h,'get_ai_response',side_effect=AssertionError('Controlled acceptance, no LLM')):
            base=initial('open');orders=moves(base)
            first=execute('two-sites-t1',base,orders)
            tasks=[u['crossing'] for u in first['red_units'][:2]]
            assert [t['site_id'] for t in tasks]==['west','east']
            assert tasks[0]['served_work']>450 and 250<tasks[1]['served_work']<=300
            second=execute('two-sites-t2',first,orders)
            assert second['red_units'][0]['crossing']['status']=='completed'
            assert second['red_units'][1]['crossing']['served_work']>tasks[1]['served_work']
            held=execute('hold-west',base,orders[1:])
            assert crossing_network.sites(held)[0]['crossing_receipt']['used_work']==0
            assert abs(held['red_units'][1]['crossing']['served_work']-tasks[1]['served_work'])<.001
            closed=initial('closed');out=execute('closed-east',closed,moves(closed))
            assert out['red_units'][1]['crossing']['served_work']==0
            assert out['red_units'][0]['crossing']['served_work']>450
            build=initial('build');out=execute('build-east',build,[{'unit':build['red_units'][1]['name'],'action':'build_bridge'}])
            assert crossing_network.sites(out)[1]['progress']>50
            assert crossing_network.sites(out)[0]['materials']==crossing_network.sites(build)[0]['materials']
            cargo=initial('cargo');out=execute('two-site-cargo',cargo,[{'unit':u['name'],'action':'resupply'} for u in cargo['red_units'][:2]])
            assert all(s['crossing_receipt']['cargo_work']>0 for s in crossing_network.sites(out))
            assert all(s['crossing_receipt']['used_work']==0 for s in crossing_network.sites(out))
            passed=True
    finally:
        h.close_harness()
        (root/'result.json').write_text(json.dumps({'passed':passed,'model_calls':0,'cases':results},ensure_ascii=False,indent=2)+'\n')
        print(root,flush=True)


if __name__=='__main__':main()
