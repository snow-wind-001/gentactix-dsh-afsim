"""Actual native one-sided transfers; no response fixtures or Python executor."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for actual WSF execution')
    root=Path('.cache/qa/noncontact/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
            ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from backend import afsim_world,afsim_rules,harness_engine
    from gentactix import historical_operations as ho,missions,sim_clock,ferries
    from tools.qa.noncontact_fixture import CASES,inputs
    result={'passed':False,'cases':[],'scope':'10-person QA loads on sourced identities; not full historical formations'}
    def run(label,before,orders):
        prior=copy.deepcopy(before);scene=afsim_world.compile_scene(before,orders,60,native_rules=True)
        assert len(scene['entities'])==1 and {u['team'] for u in scene['entities'].values()}=={'red'}
        (root/(label+'.afsim')).write_text(scene['script'])
        with patch.object(missions,'advance',side_effect=AssertionError('No Python execution')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'1分钟');after['afsim']=evidence
        missions.validate(after);assert before==prior
        assert after['blue_units']==[] and not after['engagements']
        assert {n['team'] for n in after['supply_nodes']}=={'red'}
        assert after['red_units'][0]['personnel']['current']==10 and after['red_units'][0]['personnel']['casualties']==0
        assert after['historical_initial']==before['historical_initial']
        boat=ferries.state(after)['boats'][0]
        item={'label':label,'turn':after['mission']['turn'],'status':after['mission']['status'],
              'boat_phase':boat['phase'],'trips':boat['trips'],'passenger':boat['passenger'],
              'crossing':after['red_units'][0].get('crossing'),'position':{k:after['red_units'][0][k] for k in ('lat','lng')}}
        result['cases'].append(item)
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(label,after['mission']['status'],boat['phase'],boat['trips'],flush=True)
        return after
    try:
        for identity in CASES:
            initial=ho.initial(*inputs(identity));world=copy.deepcopy(initial)
            target=world['combined_arms']['bridge']['crossing_model']['banks']['b']
            orders=[{'unit':world['red_units'][0]['name'],'action':'move',**target}]
            for turn in range(1,5):
                world=run(identity+'-move-'+str(turn),world,orders)
                if world['mission']['status']=='completed':break
            assert world['mission']['winner']=='red'
            assert world['red_units'][0]['crossing']['status']=='completed'
            assert ferries.state(world)['boats'][0]['trips']==1
            held=run(identity+'-same-initial-hold',initial,[])
            assert held['mission']['status']=='active'
            assert missions.distance(held['red_units'][0],initial['red_units'][0])<.001
            assert ferries.state(held)['boats'][0]['trips']==0
            snapshot,params=inputs(identity);params['goal']['deadline_turn']=1
            expired=run(identity+'-deadline-hold',ho.initial(snapshot,params),[])
            assert expired['mission']['status']=='completed' and expired['mission']['winner'] is None
        result['passed']=True
    finally:
        harness_engine.close_harness()
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        Path('.cache/qa/noncontact/native-latest.json').write_text(json.dumps({'directory':str(root),'passed':result['passed']})+'\n')


if __name__=='__main__':main()
