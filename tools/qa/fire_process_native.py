"""Actual WSF check after expression extraction; no Python fire executor."""
import argparse
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--catalog',action='store_true',help='Also compare all thirteen previously executed local phases')
    args=p.parse_args()
    if not args.live:p.error('Use --live for actual native execution')
    root=Path('.cache/qa/fire-process/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from gentactix import historical_operations as ho,missions,sim_clock
    from backend import afsim_world,afsim_rules,harness_engine
    draft=json.loads(Path('.cache/qa/catalog-expansion/actual-builder-draft.json').read_text())
    before=ho.initial(draft['initial'],draft['parameters'])
    previous=json.loads(Path('.cache/qa/catalog-expansion/builder-followup/afsim-turn1.json').read_text())['war_state']
    red,blue=before['red_units'][0],before['blue_units'][0]
    orders=[{'unit':red['name'],'action':'fire','target':blue['name']},{'unit':blue['name'],'action':'fire','target':red['name']}]
    cases=[('generated-builder',before,previous,orders,'15分钟')]
    if args.catalog:
        old_root=Path('.cache/qa/catalog-expansion/live')
        manifest=json.loads((old_root/'result.json').read_text());assert manifest['passed']
        for row in manifest['profiles']:
            before=json.loads((old_root/(row['id']+'-initial.json')).read_text())['war_state']
            after=json.loads((old_root/(row['id']+'-turn1.json')).read_text())['war_state']
            cases.append((row['id'],before,after,after['afsim']['orders'],'30分钟'))
    result={'passed':False,'scope':'same frozen QA inputs, actual WSF, not historical calibration','cases':[]}
    try:
        for label,before,previous,orders,step in cases:
            print('START',label,flush=True)
            scene=afsim_world.compile_scene(before,orders,sim_clock.duration_seconds(step),native_rules=True)
            (root/(label+'.afsim')).write_text(scene['script'])
            with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
                positions,evidence=afsim_world.run_scene({},scene)
                after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                    afsim_world.apply_observations(before,positions,scene))
            after['current_time'],after['simulation_clock']=sim_clock.target(before,step);after['afsim']=evidence
            missions.validate(after)
            (root/(label+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
            old={u['name']:u for _,u in missions.units(previous)};rows=[]
            for _,u in missions.units(after):
                prior=old[u['name']]
                # API roster normalization adds carried_forward; compare all
                # numerical accounts and native provenance, not that UI flag.
                from gentactix.combat_effects import COUNT_FIELDS
                assert {k:u['personnel'].get(k) for k in COUNT_FIELDS}=={k:prior['personnel'].get(k) for k in COUNT_FIELDS},u['name']
                assert u['personnel']['calculation_source']==prior['personnel']['calculation_source']
                assert u['logistics']==prior['logistics'],u['name']
                for key in ('delay_s','fire_cycles'):
                    assert u['formation']['last_execution'][key]==prior['formation']['last_execution'][key],(u['name'],key)
                rows.append({'unit':u['name'],'casualties':u['personnel']['casualties'],
                    'cycles':u['formation']['last_execution']['fire_cycles'],'delay_s':u['formation']['last_execution']['delay_s'],
                    'active_fire_s':u['formation']['last_execution']['active_fire_s']})
            result['cases'].append({'label':label,'units':rows})
            (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print('PASS',label,[(u['casualties'],u['cycles']) for u in rows],flush=True)
        result['passed']=True
    finally:
        harness_engine.close_harness()
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        Path('.cache/qa/fire-process/native-latest.json').write_text(json.dumps({'directory':str(root),'passed':result['passed']}))


if __name__=='__main__':main()
