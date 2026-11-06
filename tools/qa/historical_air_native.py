"""Opt-in native aviation runs; receipt checks, never a combat fallback."""
import argparse,copy,json,os,time
from pathlib import Path
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Actual AFSIM requires --live')
r=Path('.cache/qa/historical-air/native')/str(time.time_ns());r.mkdir(parents=True)
for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):os.environ['GENTACTIX_'+key]=str(r.resolve()/suffix)
from backend import afsim_world,afsim_rules,afsim_air
from gentactix import missions,historical_operations as ho,sim_clock,air_assets
from tools.qa.historical_air_fixture import inputs
results=[]
def native(label,w,orders):
    before=copy.deepcopy(w);scene=afsim_world.compile_scene(w,orders,1800,native_rules=True)
    with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
        positions,e=afsim_world.run_scene({},scene)
        after=afsim_rules.apply_telemetry(e['native_effects'],scene['native_model'],scene,afsim_world.apply_observations(w,positions,scene))
    after['current_time'],after['simulation_clock']=sim_clock.target(w,'30分钟');missions.validate(after)
    assert before==w
    receipts=after['air_operations']['missions'] if after.get('air_operations') else []
    for task in receipts:assert task['events'][0]['phase']=='launch' and task['events'][-1]['phase']=='returned'
    (r/(label+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
    (r/(label+'-telemetry.json')).write_text(json.dumps(e['native_effects'],ensure_ascii=False,indent=2)+'\n')
    results.append({'label':label,'passed':True,'afsim':{k:v for k,v in e.items() if k!='native_effects'},'flight_tasks':len(receipts),'assets':after.get('air_operations',{}).get('assets'),'historical_fit_verified':False})
    print(label,'PASS',len(receipts),'native flight tasks',flush=True)
    return after
try:
    s,p=inputs();world=ho.initial(s,p);red=world['red_units'][0]['name'];blue=world['blue_units'][0]['name']
    order={'unit':red,'action':'air_support','target':blue,'air_pool':'ww2.cacw.group5'}
    after=native('xiangxi-air',world,[order]);held=native('xiangxi-hold',world,[])
    pool=after['air_operations']['pools']['ww2.cacw.group5']
    assert pool['sorties']==2 and pool['ordnance']==6 and pool['fuel']==12 and pool['ready']==4
    assert held['blue_units'][0]['personnel']['casualties']==0<after['blue_units'][0]['personnel']['casualties']
    assert held['air_operations']['pools']['ww2.cacw.group5']['fuel']==16
    assert after['historical_initial']==s
    # Independent QA registry, not a published historical assertion or catalog edit.
    from verify_afsim_air import ExplicitAirTests
    fixture=ExplicitAirTests();fixture.setUp()
    try:
        value=native('qa-both-sides',fixture.world,fixture.orders())
        pools=value['air_operations']['pools'];assert pools['qa.red.air1']['sorties']==0
        assert pools['qa.red.air2']['sorties']==2 and pools['qa.blue.air1']['sorties']==1
        assert pools['qa.red.air1']['fuel']==24 and pools['qa.blue.air1']['fuel']==21
        air_assets.validate_state(fixture.definition,value['air_operations'])
    finally:fixture.doCleanups()
finally:
    (r/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');(r.parent/'latest.json').write_text(json.dumps({'directory':str(r)})+'\n')
