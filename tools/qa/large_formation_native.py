"""Actual AFSIM scale and task-group checks; all numerics are QA assumptions."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Use --live for actual AFSIM')
root=Path('.cache/qa/large-formation-2026-10-31/native')/str(time.time_ns());root.mkdir(parents=True)
for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                   ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):
    os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
from gentactix import historical_operations as ho,force_organization as f,commands,missions,sim_clock
from backend import afsim_world,afsim_rules
from tools.qa.large_formation_fixture import inputs

results=[]
def execute(label,before,orders):
    start=time.monotonic();frozen=copy.deepcopy(before)
    scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
    with patch.object(missions,'advance',side_effect=AssertionError('Native engine required')):
        positions,evidence=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
            afsim_world.apply_observations(before,positions,scene))
    after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');after['afsim']=evidence
    missions.validate(after);assert frozen==before
    assert len(after['red_units'])==70 and len(after['blue_units'])==9
    assert len(after['mission']['ledger'])>=79
    (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False))
    results.append({'case':label,'seconds':round(time.monotonic()-start,3),'units':79,'passed':True})
    print(results[-1],flush=True);return after

try:
    snapshot,p=inputs();initial=ho.initial(snapshot,p)
    held=execute('all-79-hold',initial,[])
    assert sum(u['personnel']['casualties'] for _,u in missions.units(held))==0
    fire=[]
    for side in ('red','blue'):
        other='blue' if side=='red' else 'red'
        for actor,target in zip(initial[side+'_units'][:4],initial[other+'_units'][:4]):
            fire.append({'unit':actor['name'],'action':'fire','target':target['name']})
    fought=execute('eight-formations-mutual-fire',initial,fire)
    for side in ('red','blue'):assert sum(u['personnel']['casualties'] for u in fought[side+'_units'])>0
    s=dict(id='c'*12,turn_count=1,role_epoch=0,simulation_mode='open',product_mode='historical',
        execution_backend='afsim',time_step='30分钟',war_state=fought)
    ids=[i for i,(e,u) in commands.resolve_units(s).items() if e['team']=='red'][:12]
    s['force_organization']=f.detach(s,ids,'QA北翼兵团','选择12个既有具名下级，未增加兵力')
    group=s['force_organization']['groups'][0]['id']
    s['command_state']=f.queue(s,group,{'action':'move','duration':'until_arrived','destination':{'lat':30.596,'lng':114.31}})
    orders=[commands.step_order(s,o) for o in commands.state(s)['orders']]
    moved=execute('12-subordinates-group-march',fought,orders)
    assert any(missions.distance(a,b)>.001 for a,b in zip(fought['red_units'][:12],moved['red_units'][:12]))
    for a,b in zip(fought['red_units'][12:],moved['red_units'][12:]):assert missions.distance(a,b)<.001
    s['war_state']=moved;s['turn_count']=2;f.validate(s)
    ledger_before={u['name']:copy.deepcopy(u['personnel']) for _,u in missions.units(moved)}
    s['force_organization']=f.detach(s,ids[:6],'QA分遣群','从现有12下级中分出6个，不切割或复制士兵')
    s['force_organization']=f.merge(s,[g['id'] for g in s['force_organization']['groups']],
        'QA复编群','统一指挥而不改建制、位置或资源')
    assert {u['name']:u['personnel'] for _,u in missions.units(s['war_state'])}==ledger_before
    group=s['force_organization']['groups'][0]['id'];s['command_state']=f.queue(s,group,{'action':'hold','duration':'next'})
    restored=execute('regrouped-hold-keeps-casualties',moved,[commands.step_order(s,o) for o in commands.state(s)['orders']])
    for _,u in missions.units(restored):assert u['personnel']['casualties']==ledger_before[u['name']]['casualties']
    (root/'result.json').write_text(json.dumps({'passed':True,'checks':results,'scope':'79 sourced identities; numerical QA assumptions, no historical calibration'},indent=2))
finally:
    print('Evidence:',root,flush=True)
