"""Actual AFSIM checks for new sourced local phases; no model or historical calibration."""
import argparse,copy,json,os,time
from pathlib import Path
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Native AFSIM needs --live')
r=Path('.cache/qa/xiangjiang/native')/str(time.time_ns());r.mkdir(parents=True)
for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):os.environ['GENTACTIX_'+key]=str(r.resolve()/suffix)
from backend import afsim_world,afsim_rules
from gentactix import missions,historical_operations as ho,sim_clock,combined_arms
from tools.qa.xiangjiang_fixture import inputs
results=[]
def native(w,orders):
 scene=afsim_world.compile_scene(w,orders,1800,native_rules=True)
 with patch.object(missions,'advance',side_effect=AssertionError('No Python combat')):
  positions,evidence=afsim_world.run_scene({},scene);observed=afsim_world.apply_observations(w,positions,scene)
  after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,observed)
 after['current_time'],after['simulation_clock']=sim_clock.target(w,'30分钟');missions.validate(after)
 return after,{k:v for k,v in evidence.items() if k!='native_effects'}
try:
 for phase in ('xinxu_nov28','guanghuapu_nov30_morning'):
  snapshot,params=inputs(phase);world=ho.initial(snapshot,params);before=copy.deepcopy(world);orders=[]
  for team,u in missions.units(world):
   target=min((v for t,v in missions.units(world) if t!=team),key=lambda e:missions.distance(u,e))
   orders.append({'unit':u['name'],'action':'bombard' if 'bombard' in combined_arms.actions(world,u,team) else 'fire','target':target['name']})
  after,actual=native(world,orders);held,alternative=native(world,[o for o in orders if o['unit'] in {u['name'] for u in world['blue_units']}])
  idle,idle_evidence=native(world,[])
  assert world==before and after['historical_initial']==snapshot and actual['entity_count']==len(orders)
  assert all(u['personnel']['committed']==u['personnel']['current']+u['personnel']['casualties']+u['personnel']['noncombat_losses']
   and u['personnel']['casualties']==sum(u['personnel'].get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
   and all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']) for _,u in missions.units(after))
  assert sum(u['personnel']['casualties'] for u in held['blue_units'])==0
  assert all(u['personnel']['casualties']==0 for _,u in missions.units(idle))
  assert all(u['formation']['last_execution']['fire_cycles']>0 for _,u in missions.units(after))
  row={'phase':phase,'passed':True,'historical_fit_verified':False,'actor_count':actual['entity_count'],
   'totals':{t:sum(u['personnel']['casualties'] for u in after[t+'_units']) for t in ('red','blue')},
   'checks':['native source IDs and exact entities','actual declared firing cycles','personnel and equipment conservation','red hold intervention gives no blue combat loss','all hold gives no combat loss','source initial unchanged'],
   'evidence':actual,'alternative_evidence':alternative,'idle_evidence':idle_evidence}
  results.append(row);(r/(phase+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n');print(phase,'PASS',row['totals'],flush=True)
finally:
 (r/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');(r.parent/'latest.json').write_text(json.dumps({'directory':str(r)})+'\n')
