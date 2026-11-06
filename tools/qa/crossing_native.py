"""Actual native queue, carry and bank-route execution; explicit QA geometry."""
import argparse,copy,json,os,time
from pathlib import Path
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--approach-only',action='store_true');p.add_argument('--control-only',action='store_true');a=p.parse_args()
if not a.live:p.error('Native AFSIM requires --live')
r=Path('.cache/qa/crossing-control/native' if a.control_only else '.cache/qa/river-crossing/native')/str(time.time_ns());r.mkdir(parents=True)
for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):os.environ['GENTACTIX_'+key]=str(r.resolve()/suffix)
from backend import afsim_world,afsim_rules
from gentactix import missions,sim_clock
from verify_afsim_crossing import fixture
spec=fixture();original=missions.definition
results=[];completed=False
def native(label,w,orders,seconds=1800):
 prior=copy.deepcopy(w);scene=afsim_world.compile_scene(w,orders,seconds,native_rules=True)
 with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')):
  positions,e=afsim_world.run_scene({},scene)
  after=afsim_rules.apply_telemetry(e['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(w,positions,scene))
 after['current_time'],after['simulation_clock']=sim_clock.target(w,w['mission']['definition']['time_step']);missions.validate(after);assert w==prior
 after['afsim']={k:v for k,v in e.items() if k!='native_effects'}
 (r/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
 results.append({'label':label,'passed':True,'afsim':{k:v for k,v in e.items() if k!='native_effects'},'tasks':[{k:copy.deepcopy(u[k]) for k in ('name','lat','lng','crossing') if k in u} for _,u in missions.units(after)]})
 print(label,'native receipts decoded',flush=True);return after
try:
 with patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(spec) if i==spec['id'] else original(i)):
  if a.control_only:
   from gentactix import commands,crossings
   from backend import afsim_comparison
   world=missions.from_definition(spec);name=world['red_units'][0]['name']
   move={'unit':name,'action':'move','lat':27.303,'lng':107.4,'intent_id':'a'*32}
   first=native('bound-queue-a',world,[move]);task=first['red_units'][0]['crossing']
   assert task['intent_id']=='a'*32 and abs(task['served_work']-500)<.1 and task['status']=='queued'
   resumed=native('same-command-a-resumes',first,[move])
   assert resumed['red_units'][0]['crossing']['status']=='completed' and abs(resumed['red_units'][0]['crossing']['last_work']-100)<.1
   stopped=native('cancel-a-preserves-spent-work',first,[{'unit':name,'action':'hold','cancel_crossing':'a'*32}])
   assert stopped['red_units'][0]['crossing']['status']=='cancelled' and stopped['red_units'][0]['crossing']['served_work']==task['served_work']
   assert stopped['combined_arms']['bridge']['crossing_receipt']['used_work']==0
   retained=native('cancelled-stays-cancelled-without-new-command',stopped,[])
   assert retained['red_units'][0]['crossing']['status']=='cancelled' and retained['red_units'][0]['crossing']['last_work']==0
   replacement={**move,'intent_id':'b'*32}
   for label,prior,order in [('reissue-b-after-confirmed-cancel',stopped,replacement),('cancel-and-replace-b-same-turn',first,{**replacement,'cancel_crossing':'a'*32})]:
    result=native(label,prior,[order]);t=result['red_units'][0]['crossing']
    assert t['intent_id']=='b'*32 and t['status']=='queued' and abs(t['served_work']-500)<.1 and abs(t['last_work']-500)<.1
   request=[{k:v for k,v in move.items() if k!='intent_id'}];snapshot=copy.deepcopy(first)
   cf=afsim_comparison.compare({'war_state':first},{'before':world,'after':first,'time_step':'30分钟'},request)
   assert first==snapshot and cf['alternative']['red_units'][0]['crossing']==first['red_units'][0]['crossing'] and all(m['delta']==0 for m in cf['metrics'])
   results.append({'label':'identical-counterfactual-retains-host-intent','passed':True,'main_unchanged':True,'metrics':cf['metrics']})
   # 1687.5 s service leaves less than the native two-bank travel time.
   spec['initial_state']['combined_arms']['bridge']['crossing_model']['throughput_work_per_hour']=1280
   transit=native('actual-channel-transit',missions.from_definition(copy.deepcopy(spec)),[move]);t=transit['red_units'][0]['crossing']
   assert t['status']=='transit' and t['served_work']==600
   onward=native('channel-retask-b-without-repaying-service',transit,[replacement]);t=onward['red_units'][0]['crossing']
   assert t['intent_id']=='b'*32 and t['status']=='completed' and t['last_work']==0 and t['served_work']==600
   try:afsim_world.compile_scene(transit,[{**replacement,'lat':27.298}],1800,native_rules=True)
   except ValueError as e:assert '抵岸' in str(e)
   else:raise AssertionError('In-channel reversal incorrectly accepted')
   results.append({'label':'channel-reversal-rejected-before-execution','passed':True})
   spec.clear();spec.update(fixture());spec['combined_rules']['command_base_s']=1900
   spec['initial_state']['combined_arms']['rules_hash']=missions.digest(spec['combined_rules'])
   delayed=missions.from_definition(copy.deepcopy(spec));delayed['red_units'][0]['crossing']=copy.deepcopy(task)
   after=native('cancel-not-delivered-before-turn-end',delayed,[{'unit':name,'action':'hold','cancel_crossing':'a'*32}])
   assert after['red_units'][0]['crossing']['status']=='queued' and after['red_units'][0]['formation']['last_execution']['action']=='未交付'
   completed=True;print(f'PASS all {len(results)} native control cases',flush=True);raise SystemExit(0)
  if a.approach_only:
   spec['initial_state']['red_units'][0]['lat']=27.2983;spec['initial_state']['combined_arms']['bridge']['crossing_model']['throughput_work_per_hour']=4000
   approach=missions.from_definition(copy.deepcopy(spec));entered=native('approach-from-outside-bank',approach,[{'unit':approach['red_units'][0]['name'],'action':'move','lat':27.303,'lng':107.4}])
   assert entered['red_units'][0]['crossing']['served_work']>0 and entered['red_units'][0]['crossing']['status']=='completed'
   completed=True
   print('PASS approach from outside bank',flush=True)
   raise SystemExit(0)
  world=missions.from_definition(spec);actors=world['red_units'][:2]
  orders=[{'unit':u['name'],'action':'move','lat':27.303,'lng':107.4} for u in actors]
  first=native('queue-t1',world,orders)
  assert abs(first['red_units'][0]['crossing']['served_work']-500)<.1
  assert first['red_units'][0]['lat']<27.3 and first['red_units'][1]['lat']<27.3
  second=native('carry-t2',first,orders)
  assert second['red_units'][0]['lat']>27.301 and second['red_units'][0]['crossing']['status']=='completed'
  assert second['red_units'][1]['lat']<27.3 and second['red_units'][1]['crossing']['served_work']>0
  third=native('carry-t3',second,[orders[1]])
  assert third['red_units'][1]['lat']>27.301 and third['red_units'][1]['crossing']['status']=='completed'
  held=native('same-prior-hold',first,[])
  assert held['red_units'][0]['crossing']['served_work']==first['red_units'][0]['crossing']['served_work']
  assert held['red_units'][0]['crossing']['last_work']==0
  changed=native('changed-target-restarts',first,[{**orders[0],'lng':107.401}])
  assert changed['red_units'][0]['crossing']['served_work']<501 and changed['red_units'][0]['crossing']['status']=='queued'
  blocked=copy.deepcopy(world);blocked['combined_arms']['bridge']['progress']=0
  closed=native('closed-facility',blocked,orders)
  assert all(u['crossing']['served_work']==0 and u['lat']<27.3 for u in closed['red_units'][:2])
  from backend import afsim_comparison
  unchanged=copy.deepcopy(first)
  cf=afsim_comparison.compare({'war_state':first},{'before':world,'after':first,'time_step':'30分钟'},[])
  assert first==unchanged and not any(u.get('crossing') for u in cf['alternative']['red_units'])
  assert any(m['metric']=='红方当前任务已服务工作量' and m['delta']<0 for m in cf['metrics'])
  results.append({'label':'same-prior-counterfactual','passed':True,'main_unchanged':True,'metrics':cf['metrics']})
  print('same-prior-counterfactual PASS read-only native branch',flush=True)
  spec['initial_state']['red_units'][0]['equipment'][-1].update(committed=10,operational=10)
  spec['initial_state']['red_units'][0]['lat']=27.303;spec['initial_state']['supply_nodes'][0]['stock']=10
  supplied=missions.from_definition(copy.deepcopy(spec));resupply=[{'unit':supplied['red_units'][0]['name'],'action':'resupply'}]
  cargo=native('supply-shares-capacity',supplied,resupply)
  assert cargo['mission']['ledger'][0]['delivery']==5
  assert abs(cargo['combined_arms']['bridge']['crossing_receipt']['cargo_work']-500)<.001
  supplied['combined_arms']['bridge']['integrity']=0
  closed_cargo=native('supply-closed',supplied,resupply);assert closed_cargo['mission']['ledger'][0]['delivery']==0
  # Clock-scaled construction is tested from separately frozen QA initial inputs.
  spec.clear();spec.update(fixture());spec['initial_state']['combined_arms']['bridge'].update(progress=0,integrity=0)
  spec['initial_state']['red_units'][0]['equipment'][3].update(committed=6,operational=6)
  spec['initial_state']['red_units'][0]['formation']['materials']=20
  build=missions.from_definition(copy.deepcopy(spec));build_orders=[{'unit':build['red_units'][0]['name'],'action':'build_bridge'}]
  half=native('construction-30min',build,build_orders)
  assert half['combined_arms']['bridge']['progress']==30
  spec['time_step']='1小时';hour=native('construction-60min',missions.from_definition(copy.deepcopy(spec)),build_orders,3600)
  assert hour['combined_arms']['bridge']['progress']==60
  spec.clear();spec.update(fixture());site=spec['initial_state']['combined_arms']['bridge'];site['crossing_model']['throughput_work_per_hour']=4000
  site['crossing_model']['barrier']={'a':{'lat':27.29,'lng':107.39},'b':{'lat':27.31,'lng':107.41}}
  site['crossing_model']['banks']={'a':{'lat':27.299,'lng':107.401},'b':{'lat':27.301,'lng':107.399}}
  spec['initial_state']['red_units'][0].update(lat=27.299,lng=107.401)
  spec['combined_rules']['goal_profile']='crossing';spec['initial_state']['combined_arms']['rules_hash']=missions.digest(spec['combined_rules'])
  spec['objective']={'lat':27.302,'lng':107.398};spec['required_turns']=1
  rotated=missions.from_definition(copy.deepcopy(spec));rotated_orders=[{'unit':rotated['red_units'][0]['name'],'action':'move',**spec['objective']}]
  rotated_result=native('rotated-river-and-objective',rotated,rotated_orders)
  assert rotated_result['red_units'][0]['crossing']['status']=='completed' and rotated_result['mission']['status']=='completed' and rotated_result['mission']['winner']=='red'
  spec.clear();spec.update(fixture());spec['initial_state']['red_units'][0]['lat']=27.2983
  spec['initial_state']['combined_arms']['bridge']['crossing_model']['throughput_work_per_hour']=4000
  approach=missions.from_definition(copy.deepcopy(spec));entered=native('approach-from-outside-bank',approach,[{'unit':approach['red_units'][0]['name'],'action':'move','lat':27.303,'lng':107.4}])
  assert entered['red_units'][0]['crossing']['served_work']>0 and entered['red_units'][0]['crossing']['status']=='completed'
  completed=True;print('PASS all 13 native functional cases',flush=True)
finally:
 (r/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');(r.parent/'latest.json').write_text(json.dumps({'directory':str(r)})+'\n')
 (r/'acceptance.json').write_text(json.dumps({'passed':completed,'cases':len(results),'scope':'explicit QA geometry, not historical calibration'})+'\n')
 from backend import harness_engine
 harness_engine.close_harness()
