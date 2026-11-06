"""Normal DSH skill -> AFSIM launch/control/observe over sourced Xiangjiang phases."""
import argparse,copy,json,time,urllib.error,urllib.request,uuid
from datetime import datetime
from pathlib import Path
from gentactix import historical_operations as ho,missions
from tools.qa.xiangjiang_fixture import inputs,BATTLE,NOTE
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live on owned isolated API18998')
r=Path('.cache/qa/xiangjiang');base='http://127.0.0.1:18998'
def save(name,v):(r/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(method,path,v=None,expected=200):
 request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if v is None else json.dumps(v,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(request,timeout=1200) as f:status,value=f.status,json.load(f)
 except urllib.error.HTTPError as e:status,value=e.code,json.loads(e.read())
 if status!=expected:raise RuntimeError(str(status)+': '+str(value)[:1800])
 return value
end=time.monotonic()+20
while True:
 try:health=call('GET','/api/health');break
 except OSError:
  if time.monotonic()>end:raise
  time.sleep(.2)
assert not health['build']['restart_required']
if not a.resume:
 assert not (r/'session-ids.json').exists(),'Use --resume for existing owned sessions'
 save('previous-worlds',[{'session_id':row['session_id'],'world':call('GET','/api/sessions/'+row['session_id'])['war_state']} for row in call('GET','/api/sessions')['sessions']])
ids=json.load(open(r/'session-ids.json')) if (r/'session-ids.json').exists() else {}
results=[]
for phase in ('xinxu_nov28','guanghuapu_nov30_morning'):
 result={'phase':phase,'passed':False,'historical_fit_verified':False,'checks':[]};results.append(result)
 def check(ok,text):
  if not ok:raise AssertionError(text)
  result['checks'].append(text);print(phase,'PASS',text,flush=True)
 def view(sid):
  v=call('GET',f'/api/sessions/{sid}/commands');return v,{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
 def step(sid,instruction=''):
  _,rev=view(sid);return call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
 try:
  snapshot,qa=inputs(phase);expected=set(ho.partition(snapshot));dp=r/(phase+'-draft.json')
  if a.resume and dp.exists():draft=json.load(open(dp))
  else:
   instruction=('仅使用本阶段可配置历史ID。人数、装备、位置及效能均明确为软件QA估计，不是历史实到，不由战果反推。'
    '按geographic_scope.center为工作中心，局部半径3公里、地形因子1.5；红步兵在中心北约300米，蓝步兵在中心南约300米，'
    '多个红步兵经度稍错开，军委炮兵营在红方后方北约1.7公里，经度略错开。'
    '红步兵团每个900人，桂军师只绑定该地域投入1800人，不是整个师；若有军委炮兵营则150人、4门火炮、240发炮弹。'
    '所有其他编组artillery=0；所有编组armor/air_defense/engineer/transport=0、fuel_liters/spares/materials/aa_rounds=0。'
    '均徒步、motorized=false，无航空、桥梁。步兵type步兵、role=infantry，炮兵营type炮兵、role=support。'
    'speed3，步兵自卫直射1000米、炮兵自卫500米；间瞄artillery_range_m=6000、min_range300，不能把间瞄射程赋给自卫直射。'
    '粮弹工作量80，fatigue15、entrenchment15、suppression0、dispersion_km2=0.5、protection0.15、signal80、intel_confidence80、intel_age_min0。'
    '从execution_window.start开始，每轮30分钟。goal.team=red,profile=delay,deadline_turn=8,required_turns=2,required_survivors=1；'
    '目标中心为工作中心，退出点在工作中心正北约1.3公里，radius_km=0.25。迟滞只保护本地域北向通路，不代表纵队已经过江。'
    '双方后方各约2公里设估计补给节点，stock和五类库存均0，只检验携行物资，不声称已解决徒步输送。'
    'facility仅计算汇总点：progress/integrity/materials/capacity/used全0，不设置假桥梁障碍。'
    '遵守阶段排除项：不得提前添加24/45师、红18团或接替部队，不混入另一个阻击方向。'
    '红10团400余、红5师2000余与宽口径3500不是同窗口，不套历史伤亡配额。'
    '真实读取skill和basis，用原生工具完成分片校验，最后实际AFSIM装载。')
   operation_id=uuid.uuid4().hex;save(phase+'-build-request',{'operation_id':operation_id,'phase_id':phase,'instruction':instruction})
   print(phase,'BUILD DSH native skill',flush=True)
   draft=call('POST','/api/historical-scenarios/build',{'battle':BATTLE,'phase_id':phase,'instruction':instruction,'execution_backend':'afsim','time_step':'30分钟','operation_id':operation_id});save(phase+'-draft',draft)
  calls={e.get('name') for run in draft['construction']['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
  required={'read_scenario_skill','get_scenario_basis','validate_scenario_configuration'}
  if draft['construction'].get('workflow')=='native_agent_registry_scoped_drafts':required.add('update_scenario_configuration')
  check(draft['construction']['source']=='dsh_native_skill' and required<=calls,'actual native skill, source, configuration and validation calls')
  check(draft['validation']['scope']=='native_load','actual AFSIM draft load')
  if phase not in ids:
   ids[phase]=call('POST','/api/sessions',{'scenario':'湘江具名历史局部QA-'+phase,'battle':BATTLE,'product_mode':'historical','execution_backend':'afsim','use_rag':True,'persist_roles':False,'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id']})['session_id'];save('session-ids',ids)
  sid=ids[phase];result['session_id']=sid;state=call('GET',f'/api/sessions/{sid}')
  if not state.get('war_state'):state=call('POST',f'/api/sessions/{sid}/init')
  if not (r/(phase+'-initial.json')).exists():save(phase+'-initial',state)
  check({u['historical_unit_id'] for _,u in missions.units(state['war_state'])}==expected,'all exact non-overlapping source actors imported')
  check(state['war_state']['historical_initial']==snapshot,'unknown historical facts remain frozen and separate')
  if state['turn_count']==0:
   answer=step(sid,'实际调用get_afsim_observation和retrieve_history，核对本阶段双方实际编组。每个可行动步兵fire最近敌方步兵；如果有炮兵营则bombard最近敌方步兵，不移动。双方每个单位明确合法命令与公开依据。AFSIM负责效果，不提前加入后续部队，不为历史伤亡配额扣人。');save(phase+'-turn1',answer)
  else:answer=json.load(open(r/(phase+'-turn1.json')))
  check(not answer['war_state']['afsim']['model_skipped'],'actual DSH planned the first round')
  trajectory=call('GET',f'/api/sessions/{sid}/export')['session']['trajectory'];first=next(t for t in trajectory if t['turn']==1)
  used={e.get('name') for run in first['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
  check({'get_afsim_observation','retrieve_history'}<=used,'planner actually observes AFSIM and retrieves battle-scoped history')
  current=call('GET',f'/api/sessions/{sid}');v,rev=view(sid)
  branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':1,'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']});save(phase+'-counterfactual',branch)
  check(all(u['personnel']['casualties']==0 for u in branch['alternative']['blue_units']),'same-prior red hold removes blue combat losses')
  check(call('GET',f'/api/sessions/{sid}')['war_state']==current['war_state'],'readonly branch leaves committed world unchanged')
  completed=current['turn_count'];ledger=[]
  for n in range(1,9):
   if n<=completed:answer=json.load(open(r/(phase+'-turn'+str(n)+'.json')))
   else:
    if answer['war_state']['mission']['status']!='active':break
    v,rev=view(sid);orders=[]
    for u in v['units']:
     order={'unit_id':u['id'],'action':'hold','duration':'next'}
     enemies=[e for e in v['units'] if e['team']!=u['team'] and e['available']]
     if u['available'] and enemies:
      target=min(enemies,key=lambda e:missions.distance(u['position'],e['position']))
      for action in ('bombard','fire'):
       if action not in u['capabilities']['actions']:continue
       limits=u['capabilities']['weapon_limits_m'][action];distance=missions.distance(u['position'],target['position'])*1000
       if limits['min_range_m']<=distance<=limits['max_range_m']:order.update(action=action,target_id=target['id']);break
     orders.append(order)
    call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]});answer=step(sid);save(phase+'-turn'+str(n),answer)
   w=answer['war_state'];missions.validate(w)
   check(w['historical_initial']==snapshot,str(n)+' frozen source roster and facts preserved')
   check(all(u['personnel']['committed']==u['personnel']['current']+u['personnel']['casualties']+u['personnel']['noncombat_losses'] and all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']) for _,u in missions.units(w)),str(n)+' personnel and equipment accounts conserve')
   ledger.append({'turn':n,'clock':w['current_time'],'units':[{k:copy.deepcopy(u[k]) for k in ('name','historical_unit_id','personnel','formation','logistics')} for _,u in missions.units(w)]})
  save(phase+'-ledger',ledger)
  check((datetime.fromisoformat(w['current_time'])-datetime.fromisoformat(draft['parameters']['clock']['start'])).total_seconds()==1800*len(ledger),'exact half-hour clock advancement')
  check(w['mission']['status']!='active','local objective terminates by its deadline')
  before=copy.deepcopy(w);analysis_path=r/(phase+'-analysis.json')
  if a.resume and analysis_path.exists():analysis=json.load(open(analysis_path))
  else:
   analysis=call('POST',f'/api/sessions/{sid}/chat',{'message':'只读调用get_afsim_observation明细和get_afsim_changes(mode=aggregate,since_turn=0)读取全程账。每单位简短表列当前人员、累计战斗减员/阵亡/负伤及火力周期。说明4小时历时不等于持续射击时长。解释红10团400余、红5师2000余、宽口径3500和出发86000至战后30000为何不能变成本局按小时扣兵或全部阵亡。区分当前实际坐标与源资料未知阵地；不下令，不改变主局。'});save(phase+'-analysis',analysis)
  check(analysis['war_state']==before and call('GET',f'/api/sessions/{sid}')['war_state']==before,'real DSH native observation and analysis are readonly')
  result.update(passed=True,turns=len(ledger),totals={u['historical_unit_id']:u['personnel'] for _,u in missions.units(w)})
 except Exception as e:result['error']=str(e);raise
 finally:save(phase+'-result',result);save('live-results',results)
