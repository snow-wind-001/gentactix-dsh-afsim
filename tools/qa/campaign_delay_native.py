"""Opt-in actual34identity goal contrasts; explicit QA parameters, no LLM."""
import argparse,copy,json,os,time
from pathlib import Path
from unittest.mock import patch
parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Actual Native checks require --live')
out=Path('.cache/qa/scenario-resume-2026-11-01/defensive-delay-native')/str(time.time_ns());out.mkdir(parents=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str((out/suffix).resolve())
from tools.qa.jizhong_assembly_fixture import inputs,NOTE
from gentactix import missions,historical_operations as ho,sim_clock
from backend import afsim_world,afsim_rules,harness_engine
checks=[]
try:
 for case,expected in [('survive',True),('enemy_exit',False),('friendly_pending',False),('enemy_pending',True)]:
  source,p=inputs();p['goal'].update(profile='delay',required_survivors=2,required_turns=1,exit={'lat':38.7,'lng':115.6})
  p['rules'].update(goal_profile='delay',required_survivors=2);p['campaign']['objective_policy']='defensive-delay-1'
  owners={u['id']:u['team'] for u in source['definition']['units']};red=[i for i in p['actors'] if owners[i]=='red'];blue=[i for i in p['actors'] if owners[i]=='blue']
  if case in ('enemy_exit','enemy_pending'):p['actors'][blue[0]]['position']=copy.deepcopy(p['goal']['exit'])
  if case=='enemy_pending':p['campaign']['arrivals'][blue[0]]['not_before']='1942-05-02T00:00:00'
  if case=='friendly_pending':
   for identity in red[1:]:p['campaign']['arrivals'][identity]['not_before']='1942-05-02T00:00:00'
  before=ho.initial(source,p);orders=[{'unit':u['name'],'action':'hold'} for _,u in missions.units(before)]
  scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
  with patch.object(missions,'advance',side_effect=AssertionError('No Python physical fallback')):
   positions,evidence=afsim_world.run_scene({},scene)
   after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(before,positions,scene))
  after['current_time'],after['simulation_clock']=sim_clock.target(before,'30分钟');missions.validate(after)
  actual=after['mission']['metrics']['condition']
  if actual!=expected:raise AssertionError((case,actual,expected))
  if after['historical_initial']!=source or len(list(missions.units(after)))!=34:raise AssertionError('Source/roster changed')
  (out/(case+'-world.json')).write_text(json.dumps(after,ensure_ascii=False))
  (out/(case+'-native.json')).write_text(json.dumps(evidence,ensure_ascii=False))
  checks.append({'case':case,'condition':actual,'entities':len(scene['entities']),'returncode':evidence['returncode']})
  print('PASS',case,actual,flush=True)
 result={'passed':True,'checks':checks,'actual_native_turns':4,'actual_model':False,'source_identities':34,'scope':NOTE+' Four independent30minute goal contrasts, not historical full windows.'}
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('RESULT',out/'result.json',flush=True)
finally:harness_engine.close_harness()
