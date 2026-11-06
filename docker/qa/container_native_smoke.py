"""Real DSH native MCP to real AFSIM; no model responses or simulator mocks."""
import copy,json,time
from pathlib import Path
from backend import afsim_world,afsim_rules,harness_engine as h
from gentactix import missions
from tools.afsim.launch import status
result={'scope':'Runtime delivery smoke using explicitly synthetic fixtures; not historical effectiveness or all-battle acceptance','status':status(),'cases':[]}
def run(before,orders,kind):
 snapshot=copy.deepcopy(before);scene=afsim_world.compile_scene(before,orders,1800,native_rules=True)
 started=time.monotonic();positions,evidence=afsim_world.run_scene({},scene)
 assert before==snapshot and evidence['transport']=='dsh-native-mcp' and evidence['returncode']==0
 assert len(positions)==len(scene['entities']) and 'native_effects'in evidence
 observed=afsim_world.apply_observations(before,positions,scene)
 after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,observed)
 missions.validate(after)
 result['cases'].append({'id':before['mission']['id'],'kind':kind,'wall_seconds':time.monotonic()-started,'entity_count':len(positions),'evidence':evidence})
 return after
try:
 before=missions.initial('AJ15-local-v1');unit=before['red_units'][0]
 after=run(before,[{'unit':unit['name'],'action':'move','lat':unit['lat'],'lng':unit['lng']+.005}],'ground_move')
 run(after,[{'unit':after['red_units'][0]['name'],'action':'fire','target':after['blue_units'][0]['name']}],'ground_fire')
 before=missions.initial('AJ18-local-v1')
 run(before,[{'unit':before['red_units'][0]['name'],'action':'air_support','target':before['blue_units'][0]['name']}],'air_strike')
 run(missions.initial('CA-AJ18-v1'),[],'combined_accounting')
 result['passed']=True
finally:
 h.close_harness()
 Path('/data/docker-native-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({'passed':result.get('passed',False),'cases':[{'id':r['id'],'kind':r['kind'],'wall_seconds':r['wall_seconds'],'entity_count':r['entity_count']}for r in result['cases']]},ensure_ascii=False))
