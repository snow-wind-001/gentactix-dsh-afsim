"""Real native DSH skill, both execution modes, commands and readonly air review."""
import argparse,copy,json,time,urllib.error,urllib.request,uuid
from pathlib import Path
from gentactix import missions,air_assets
from tools.qa.historical_air_fixture import BATTLE
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live on owned isolated API18998')
r=Path('.cache/qa/historical-air');base='http://127.0.0.1:18998';checks=[]
def save(name,v):(r/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def check(ok,label):
 if not ok:raise AssertionError(label)
 checks.append(label);print('PASS',label,flush=True);save('live-checks',checks)
def call(method,path,v=None):
 req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if v is None else json.dumps(v,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:2200])
def view(sid):
 v=call('GET',f'/api/sessions/{sid}/commands');return v,{k:v[k] for k in ('revision','world_version')}|{'expected_turn':v['turn']}
def step(sid,instruction):
 _,rev=view(sid);return call('POST',f'/api/sessions/{sid}/next',{**rev,'instruction':instruction,'batch_id':uuid.uuid4().hex})
end=time.monotonic()+90
while True:
 try:health=call('GET','/api/health');break
 except OSError:
  if time.monotonic()>end:raise
  time.sleep(.3)
check(not health['build']['restart_required'],'owned API uses current source')
if (r/'air-draft.json').exists():
 assert a.resume,'Use --resume for existing owned draft'
 draft=json.load(open(r/'air-draft.json'))
else:
 instruction=('只配置dongkou_late_april所列具名地面与航空身份；所有下述数值均标记软件QA估计而非历史实力、阵地或机场。'
  '从execution_window.start开始，每轮30分钟，共4轮，goal.team=red，delay，required_survivors=1，required_turns=1。'
  'area.center用洞口现代参考27.05272,110.53610，半径10km，terrain_factor=1.5，目标中心相同，出口在中心正南约5km，radius_km=0.5。'
  '第57师局部投入1800人位于中心南约300米，日第116师团当地投入2400人在中心北约300米；都是步兵，速度3km/h、自卫直射1200m、控制半径0.2km。'
  '每个地面编组artillery=4,transport=4,armor=engineer=air_defense=0；role=infantry，motorized=false，food=ammo=80，shells=48，'
  'fuel_liters=2000,spares=20,materials=16,aa_rounds=0,reload_remaining=0，fatigue=10，suppression=0，entrenchment=10，dispersion_km2=3，protection=.15，signal=90，intel_confidence=80，intel_age_min=10。'
  '双方补给节点在各自后方约2km，stock=0且五类inventory全部0；不声称解决真实运输。facility只是中心计算汇总点，progress/integrity/materials/capacity/used均0，bridge_enabled=false。'
  '开启air_support=true。aviation只填ww2.cacw.group5：initial committed=4架、ordnance=8工作单位、fuel=16工作单位；'
  'entry lat=27.02272,lng=110.52610，是计算入场/返场点而非真实机场。'
  '航空rules保持模板：package2、fuel_per_aircraft2、preparation_s60、speed_mps120、altitude_m3000、target_radius_km0.5、personnel_per_effective_aircraft8、equipment_per_effective_aircraft1。'
  '第五大队不放进actors；蓝方航空没有来源，不创造飞机。该窗口不是25日真实空袭记录复原，缺载史实仍null。'
  '真实读取skill和basis，用原生工具校验完整配置，最后实际AFSIM装载。')
 op=uuid.uuid4().hex;save('build-request',{'operation_id':op,'instruction':instruction})
 print('BUILD real DSH native skill',flush=True)
 draft=call('POST','/api/historical-scenarios/build',{'battle':BATTLE,'phase_id':'dongkou_late_april','instruction':instruction,'time_step':'30分钟','execution_backend':'afsim','operation_id':op});save('air-draft',draft)
calls={e.get('name') for run in draft['construction']['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
check({'read_scenario_skill','get_scenario_basis','validate_scenario_configuration'}<=calls,'actual native DSH skill and validation calls')
check(draft['validation']['scope']=='native_load','actual draft loaded in native AFSIM')
params=draft['parameters'];check(set(params['actors'])=={'ww2.cn.division57','ww2.jp.division116'} and set(params['aviation'])=={'ww2.cacw.group5'},'ground and aviation historical identities separate')
check(params['aviation']['ww2.cacw.group5']['initial']=={'committed':4,'ordnance':8,'fuel':16},'DSH respects explicit QA air resource inputs')
ids=json.load(open(r/'session-ids.json')) if (r/'session-ids.json').exists() else {}
for engine in ('afsim','narrative'):
 if engine not in ids:
  selected=draft
  if engine=='narrative':
   op=uuid.uuid4().hex;save('narrative-validate-request',{'operation_id':op})
   selected=call('POST','/api/historical-scenarios/validate',{'parameters':params,'parent_draft_id':draft['id'],'execution_backend':engine,'operation_id':op});save('narrative-draft',selected)
  ids[engine]=call('POST','/api/sessions',{'scenario':'湘西航空资源QA-'+engine,'battle':BATTLE,'product_mode':'historical','execution_backend':engine,'use_rag':True,'persist_roles':False,'historical_parameters':params,'scenario_draft_id':selected['id']})['session_id'];save('session-ids',ids)
 sid=ids[engine];state=call('GET',f'/api/sessions/{sid}')
 if not state.get('war_state'):state=call('POST',f'/api/sessions/{sid}/init')
 if not (r/(engine+'-initial.json')).exists():save(engine+'-initial',state)
 if state['turn_count']==0:
  msg=('本轮第57师只执行air_support，target精确使用日军第116师团当地投入部分，air_pool=ww2.cacw.group5；日方hold。双方地面单位不射击不移动不补给。'
       '使用已登记2架任务包，完整起飞、目标复核、打击与返场。独立扣2航空弹药与4航空燃油工作单位，地面ammo不消耗；粮食按现有规则消耗。'
       '飞行时刻和战损依照计算规则与实际执行，不按历史伤亡配额。'
       +('实际调用get_afsim_observation与retrieve_history再输出两方命令。' if engine=='afsim' else
         'AFSIM已关闭，由DSH估计完整过程；按当前prompt提交aviation全部池余额与missions完整events，以及单位更新、交战和resource_ledger；不要声称原生AFSIM执行。'))
  state=step(sid,msg);save(engine+'-turn1',state)
 w=state['war_state'];missions.validate(w);air_assets.validate_state(air_assets.world_definition(w),w['air_operations'])
 check(w['air_operations']['pools']['ww2.cacw.group5']['fuel']==12 and w['air_operations']['pools']['ww2.cacw.group5']['ordnance']==6,engine+' consumes independent aviation fuel and ordnance')
 check(len(w['air_operations']['missions'])==1 and w['air_operations']['missions'][0]['events'][-1]['phase']=='returned',engine+' returns a complete single flight task')
 check(w['air_operations']['assets']['blue']['committed']==0,engine+' has no invented blue aircraft')
 check(w['historical_initial']==json.load(open(r/(engine+'-initial.json')))['war_state']['historical_initial'],engine+' source facts remain unchanged')
 check(all(u['logistics']['ammo']==80 for _,u in missions.units(w)),engine+' aircraft do not spend ground ammunition')
 check((w['air_operations']['missions'][0]['source']=='dsh_model_estimate')==(engine=='narrative'),engine+' evidence source is honest')
 if engine=='afsim':
  check(not w['afsim']['model_skipped'],'actual DSH planner participated')
  before=copy.deepcopy(w);v,rev=view(sid)
  compare=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':1,'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']});save('air-counterfactual',compare)
  check(compare['alternative']['air_operations']['assets']['red']['fuel']==16,'same-prior counterfactual cancels aviation consumption')
  check(call('GET',f'/api/sessions/{sid}')['war_state']==before,'counterfactual leaves main world unchanged')
  if not (r/'native-analysis.json').exists():
   answer=call('POST',f'/api/sessions/{sid}/chat',{'message':'只读实际调用get_afsim_observation，核对本轮第五大队的资源池ID、投入/可用/损失飞机、累计架次、油弹余额、航路各阶段及目标当轮实际战损。解释缺载人数/飞机库存仍null，配置4架和入场点属于估计，不是25日真实任务复原。不下令，不改变战局。'});save('native-analysis',answer)
   check(answer['war_state']==before,'native DSH air review is readonly')
save('live-result',{'passed':True,'checks':checks,'sessions':ids,'historical_fit_verified':False})
print('LIVE AIR ACCEPTANCE PASS',flush=True)
