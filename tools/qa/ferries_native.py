"""Opt-in actual native boat movement with cross-round passengers."""
import argparse
import copy
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

p=argparse.ArgumentParser();p.add_argument('--live',action='store_true')
if not p.parse_args().live:p.error('Use --live for actual SDK/WSF execution')
root=Path('.cache/qa/ferry-model/native')/str(time.time_ns());root.mkdir(parents=True)
for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
    ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):
    os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
from backend import afsim_world,afsim_rules,harness_engine
from gentactix import missions,sim_clock,historical_operations as ho,ferries
from verify_ferries import ferry_inputs

checks=[];passed=False
def execute(label,before,orders):
    frozen=copy.deepcopy(before);scene=afsim_world.compile_scene(before,orders,60,native_rules=True)
    (root/(label+'.afsim')).write_text(scene['script'])
    with patch.object(missions,'advance',side_effect=AssertionError('Python turn executor forbidden')):
        positions,evidence=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
    after['current_time'],after['simulation_clock']=sim_clock.target(before,'1分钟');after['afsim']=evidence
    missions.validate(after);assert before==frozen
    (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
    print(label,[(b['phase'],b['lat'],b['passenger'],b['trips']) for b in ferries.state(after)['boats']],flush=True)
    return after

try:
    before=ho.initial(*ferry_inputs());name=before['red_units'][1]['name'];main=before['red_units'][0]
    order=[{'unit':name,'action':'move','lat':27.3151,'lng':107.402}]
    world=execute('outbound-t1',before,order)
    boat=ferries.state(world)['boats'][0]
    assert boat['phase']=='outbound' and boat['manifest_personnel']==5 and boat['passenger']==name
    assert missions.distance(world['red_units'][1],boat)<.002 and world['red_units'][1]['lat']>27.3145
    assert missions.distance(world['red_units'][0],main)<.001
    assert world['red_units'][1]['crossing']['status']=='transit'
    checks.append('actual boat boards only five, main stays ashore, passenger follows surface mover')
    held_aboard=execute('hold-aboard-t2',world,[])
    assert ferries.state(held_aboard)['boats'][0]['phase']=='outbound'
    assert held_aboard['red_units'][1]['lat']>world['red_units'][1]['lat']
    checks.append('hold aboard does not stop the physical boat or walk off midstream')
    world=execute('outbound-t2',world,order)
    assert ferries.state(world)['boats'][0]['phase']=='outbound'
    checks.append('same boat and manifest resume across rounds')
    world=execute('land-and-return-t3',world,order)
    boat=ferries.state(world)['boats'][0]
    assert boat['phase']=='returning' and boat['passenger'] is None and boat['trips']==1
    assert world['red_units'][1]['crossing']['status']=='completed'
    assert missions.distance(world['red_units'][1],{'lat':27.3151,'lng':107.402})<.002
    checks.append('landing requires actual boat arrival and unloading; return is empty')
    for turn in (4,5,6):world=execute('empty-return-t'+str(turn),world,[])
    boat=ferries.state(world)['boats'][0]
    assert boat['phase']=='idle' and boat['bank']=='a' and boat['trips']==1
    assert missions.distance(boat,{'lat':27.3145,'lng':107.402})<.001
    assert all(u['personnel']['current']==u['personnel']['committed'] for _,u in missions.units(world))
    checks.append('empty boat returns and personnel are conserved without fake crew')
    held=execute('same-initial-hold',before,[])
    assert ferries.state(held)['boats'][0]['phase']=='idle' and missions.distance(held['red_units'][1],before['red_units'][1])<.001
    assert missions.distance(ferries.state(held)['boats'][0],ferries.state(before)['boats'][0])<.001
    checks.append('hold versus crossing decision changes actual movement')
    snapshot,params=ferry_inputs();params['facility']['crossing_model']['ferry']['boats'][0]['initial_bank']='b'
    wrong=ho.initial(snapshot,params)
    for turn in (1,2,3):wrong=execute('empty-reposition-t'+str(turn),wrong,order)
    assert ferries.state(wrong)['boats'][0]['phase']=='outbound'
    assert ferries.state(wrong)['boats'][0]['passenger']==name
    checks.append('an empty boat on the opposite bank actually repositions before boarding')
    snapshot,params=ferry_inputs();second=copy.deepcopy(params['facility']['crossing_model']['ferry']['boats'][0]);second['id']='raft2'
    params['facility']['crossing_model']['ferry']['boats'].append(second)
    fleet=execute('two-boats-one-passenger',ho.initial(snapshot,params),order)
    assert sum(b['manifest_personnel'] for b in ferries.state(fleet)['boats'])==5
    assert len([b for b in ferries.state(fleet)['boats'] if b['passenger']==name])==1
    checks.append('two boats cannot reserve or duplicate the same passenger')
    snapshot,params=ferry_inputs();params['facility']['crossing_model']['ferry']['boats'][0]['load_seconds']=180
    loading=execute('loading-before-cancel',ho.initial(snapshot,params),[{**order[0],'intent_id':'1'*32}])
    assert ferries.state(loading)['boats'][0]['phase']=='loading'
    cancelled=execute('cancel-loading',loading,[{'unit':name,'action':'hold','cancel_crossing':'1'*32}])
    assert ferries.state(cancelled)['boats'][0]['phase']=='idle'
    assert cancelled['red_units'][1]['crossing']['status']=='cancelled'
    assert cancelled['red_units'][1]['crossing']['served_work']==0
    checks.append('confirmed cancellation releases a loading reservation without phantom delivery')
    passed=True
finally:
    (root/'acceptance.json').write_text(json.dumps({'passed':passed,'checks':checks},ensure_ascii=False,indent=2)+'\n')
    (root.parent/'latest.json').write_text(json.dumps({'directory':str(root)})+'\n')
    harness_engine.close_harness()
