"""Real operational-process checks; QA inputs are not historical strengths."""
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
    root=Path('.cache/qa/cheqiao-complete/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
            ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from gentactix import historical_operations as ho,missions,sim_clock
    from backend import afsim_world,afsim_rules,harness_engine
    from tools.qa.campaign_fixture import inputs
    result={'passed':False,'scope':'native process QA; not complete Cheqiao acceptance','cases':[]}
    def run(label,before,orders):
        original=copy.deepcopy(before);scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
        (root/(label+'.afsim')).write_text(scene['script'])
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
        missions.validate(after);assert before==original
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
        item={'label':label,'turn':after['mission']['turn'],'objective':after['campaign']['objective'],
            'actors':after['campaign']['actors'],'personnel':{u['name']:u['personnel'] for _,u in missions.units(after)}}
        result['cases'].append(item);(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('PASS',label,flush=True);return after
    try:
        s,p=inputs();initial=ho.initial(s,p)
        first=run('waiting-half-hour',initial,[])
        assert not first['campaign']['actors'][first['blue_units'][-1]['name']]['active']
        assert first['mission']['status']=='active'
        arrived=run('arrival-at-boundary',first,[])
        assert arrived['campaign']['actors'][arrived['blue_units'][-1]['name']]['active']
        s,p=inputs();p['actors']['ww2.jp.seya_detachment']['logistics']['ammo']=0
        capture_initial=ho.initial(s,p);red=capture_initial['red_units'][0];blue=capture_initial['blue_units'][0]
        captured=run('actual-capture',capture_initial,[{'unit':red['name'],'action':'capture','target':blue['name']}])
        unit=captured['blue_units'][0]
        assert unit['personnel']['current']==0
        assert unit['personnel']['captured']==blue['personnel']['current']
        assert unit['personnel']['killed']==unit['personnel']['wounded']==0
        assert not captured['engagements']
        held=run('same-initial-no-capture',capture_initial,[])
        assert held['blue_units'][0]['personnel']['current']==blue['personnel']['current']
        s,p=inputs();fort_initial=ho.initial(s,p);red=fort_initial['red_units'][0];blue=fort_initial['blue_units'][0]
        order={'unit':red['name'],'action':'bombard','target':blue['name']}
        hit=run('fort-bombardment',fort_initial,[order]);name=blue['name']
        assert hit['campaign']['actors'][name]['fortification_integrity']<100
        assert hit['red_units'][0]['formation']['last_execution']['shots']>0
        damaged=hit['campaign']['actors'][name]['fortification_integrity']
        carried=run('fort-carry-forward',hit,[])
        assert carried['campaign']['actors'][name]['fortification_integrity']==damaged
        fortified=run('field-fortification',fort_initial,[{'unit':red['name'],'action':'fortify'}])
        name=red['name'];base=fortified['campaign']['actors'][name]['base_entrenchment']
        assert base>fort_initial['red_units'][0]['formation']['entrenchment']
        continued=run('field-fortification-persisted',fortified,[])
        assert continued['campaign']['actors'][name]['base_entrenchment']==base
        assert continued['red_units'][0]['formation']['entrenchment']==fortified['red_units'][0]['formation']['entrenchment']
        result['passed']=True;(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        Path('.cache/qa/cheqiao-complete/native-latest.json').write_text(json.dumps({'directory':str(root),'passed':True})+'\n')
        print('PASS all',len(result['cases']),flush=True)
    finally:
        harness_engine.close_harness()


if __name__=='__main__':main()
