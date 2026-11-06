"""Exercise typed schedules in actual WSF; these are software QA inputs."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for real native execution')
    root=Path('.cache/qa/cheqiao-complete/schedule-native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
            ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from verify_cheqiao_campaign import CheqiaoCampaignTests
    from gentactix import historical_operations as ho,missions,sim_clock,campaign
    from backend import afsim_world,afsim_rules,harness_engine
    result={'passed':False,'scope':'typed schedule native QA; not historical reconstruction','cases':[]}
    def run(label,before,orders):
        original=copy.deepcopy(before);scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat fallback')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
        missions.validate(after);assert before==original
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2))
        result['cases'].append({'label':label,'native':{k:evidence[k] for k in ('returncode','status','artifact','entity_count')},
            'schedule':campaign.observation(after)['actors'][-1]})
        return after
    try:
        s,p,i=CheqiaoCampaignTests().constrained_inputs();start=ho.initial(s,p);name=start['blue_units'][-1]['name']
        waiting=run('entry-wait',start,[])
        assert not waiting['campaign']['actors'][name]['active']
        entry=run('entry-release',waiting,[])
        assert entry['campaign']['actors'][name]['active']
        assert (entry['blue_units'][-1]['lat'],entry['blue_units'][-1]['lng'])==(start['blue_units'][-1]['lat'],start['blue_units'][-1]['lng'])
        target=copy.deepcopy(p['actors'][i]['position']);p['actors'][i]['position']['lat']+=.01
        p['campaign']['arrivals'][i].update(event_kind='departure',not_before='1938-03-31T00:00')
        before=ho.initial(s,p);order={'unit':name,'action':'move',**target}
        moved=run('departure-march',before,[order])
        assert missions.distance(moved['blue_units'][-1],target)<missions.distance(before['blue_units'][-1],target)
        assert campaign.observation(moved)['actors'][-1]['event_kind']=='departure'
        result['passed']=True
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({'passed':True,'cases':len(result['cases']),'directory':str(root)}))
    finally:harness_engine.close_harness()


if __name__=='__main__':main()
