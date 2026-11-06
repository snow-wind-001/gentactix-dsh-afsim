"""Actual DSH configuration/plugin and both executors on the sourced Wujiang phase."""
import argparse,copy,json,time,urllib.request,urllib.error,uuid
from pathlib import Path
from gentactix import missions

p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');args=p.parse_args()
if not args.live:p.error('Requires owned isolated API18998 and real model use')
root=Path('.cache/qa/river-crossing');base='http://127.0.0.1:18998';checks=[]
BATTLE='红军长征-强渡乌江-1935.01.01至1935.01.06'
def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(method,path,v=None):
 req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if v is None else json.dumps(v,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:2400])
def check(ok,label):
 if not ok:raise AssertionError(label)
 checks.append(label);save('live-checks',checks);print('PASS',label,flush=True)
def view(sid):
 v=call('GET',f'/api/sessions/{sid}/commands');return v,{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
end=time.monotonic()+90
while True:
 try:health=call('GET','/api/health');break
 except OSError:
  if time.monotonic()>end:raise
  time.sleep(.25)
check(not health['build']['restart_required'],'current source API')
for row in json.load(open(root/'before-api-restart.json')):
 check(call('GET','/api/sessions/'+row['session_id'])['war_state']==row['world'],'cold restore '+row['session_id'])
if (root/'historical-draft.json').exists():
 assert args.resume;draft=json.load(open(root/'historical-draft.json'))
else:
 instruction=('仅配置follow_on_jan3桥成后的后续通行阶段，不重现此前泅渡、夜渡和桥头夺取。所有以下数量、位置、能力明确标为软件QA估计，不是历史实力表或1935年水文。'
 '时钟1935-01-03 12:00，每轮30分钟，6轮。area.center=27.3148,107.402，半径30km，terrain_factor=1.5。'
 'goal.team=red、profile=crossing、required_survivors=2、required_turns=1、deadline_turn=6，objective=27.3158,107.402，exit也用该点，radius_km=.1。'
 '只配置5个有来源ID：军委纵队局部1600人、红5军团局部3000人，3个黔军团各当地投入1000人；不可称全军实到。'
 '两红方位置分别27.3138,107.402与27.3137,107.402；三蓝方位置分别27.33,107.40、27.331,107.402、27.332,107.404，是退却部队本地计算位置估计。'
 '单位type均步兵、speed=3km/h、自卫直射500m、控制半径0.1km、motorized=false；军委纵队formation.role=support，其余infantry。'
 '装备仅transport：军委纵队4、红5军团6、蓝方各2，其他五类为0。没有来源确认的飞机与兵种不虚构。'
 '所有单位food=ammo=80，fatigue=suppression=entrenchment=0，dispersion_km2=3，protection=.1，signal=100、intel_confidence=80、intel_age_min=0；fuel_liters=spares=materials=shells=aa_rounds=reload_remaining=0。'
 '双方后方support位置红27.31,107.402、蓝27.34,107.402，stock=0和五类inventory全0，禁止伪造补给。'
 'facility保留id，name写江界河后续通行计算通道，lat=27.3148,lng=107.402，progress=integrity=100，materials=0，capacity=2、used=0；rules.bridge_enabled=true、air_support=false、motorized=false，convoy_km_per_turn=10、required_survivors=2。'
 '必须完整填写facility.crossing_model：version=formation-crossing-1，barrier.a=27.3148,107.397、b=27.3148,107.407；banks.a=27.3145,107.402、b=27.3151,107.402；'
 'throughput_work_per_hour=15000、equipment_work armor10 artillery5 air_defense5 engineer0 transport2；build_progress_per_engineer_hour=10、supply_work_per_unit=100；assumption明确所有几何与能力为QA估计、不是现代岸线复原历史。'
 'rules.command_base_s=command_signal_s=command_distance_s_per_km=0，是QA隔离队列因素；保留其余模板规则。'
 '真实调用skill、basis和校验工具，最后实际装载AFSIM；不要用普通assault占点代替渡运目标。')
 op=uuid.uuid4().hex;save('build-request',{'operation_id':op,'instruction':instruction})
 print('BUILD real DSH native skill for Wujiang',flush=True)
 draft=call('POST','/api/historical-scenarios/build',{'battle':BATTLE,'phase_id':'follow_on_jan3','instruction':instruction,
  'time_step':'30分钟','execution_backend':'afsim','operation_id':op});save('historical-draft',draft)
calls={e.get('name') for run in draft['construction']['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
check({'read_scenario_skill','get_scenario_basis','validate_scenario_configuration'}<=calls,'native DSH skill/basis/validation called')
check(draft['validation']['scope']=='native_load','native AFSIM actually loads draft')
params=draft['parameters'];check(len(params['actors'])==5 and params['goal']['profile']=='crossing','sourced actors and crossing goal')
check(params['facility']['crossing_model']['throughput_work_per_hour']==15000,'explicit estimated facility parameters preserved')
ids=json.load(open(root/'session-ids.json')) if (root/'session-ids.json').exists() else {}
for engine in ('afsim','narrative'):
 if engine not in ids:
  selected=draft
  if engine=='narrative':
   op=uuid.uuid4().hex;save('narrative-validate-request',{'operation_id':op})
   selected=call('POST','/api/historical-scenarios/validate',{'parameters':params,'parent_draft_id':draft['id'],'execution_backend':engine,'operation_id':op});save('narrative-draft',selected)
  ids[engine]=call('POST','/api/sessions',{'scenario':'乌江后续通行QA-'+engine,'battle':BATTLE,'product_mode':'historical',
   'execution_backend':engine,'use_rag':True,'persist_roles':False,'historical_parameters':params,'scenario_draft_id':selected['id']})['session_id'];save('session-ids',ids)
 sid=ids[engine];state=call('GET',f'/api/sessions/{sid}')
 if not state.get('war_state'):state=call('POST',f'/api/sessions/{sid}/init')
 if not (root/(engine+'-initial.json')).exists():save(engine+'-initial',state)
 if state['turn_count']==0:
  v,rev=view(sid);orders=[{'unit_id':u['id'],'action':'move','destination':{'lat':27.3158,'lng':107.402},'duration':'next'} if u['team']=='red'
    else {'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units']]
  call('PUT',f'/api/sessions/{sid}/commands',{**rev,'control_team':'red','director':True,'no_fire':True,'orders':orders,'unit_agents':[]})
  _,rev=view(sid);print('TURN real '+engine,flush=True)
  state=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':
   '严格执行确认命令：两红方依登记两岸通道向27.3158,107.402移动，三蓝方待命。禁止开火，无库存不补给。按当前编组渡运模型的实际容量和有效时间排队，允许未完成留在入口，不能直接瞬移、照搬历史结果或补伤亡。'
   +('先实际get_afsim_observation读取通道和单位，再提交原生命令。' if engine=='afsim' else
   'AFSIM关闭，由DSH估计过程。跨河单位更新crossing仅填served_work,last_work,status,events；累计=上轮+本轮，事件用岸点与回合秒数。提交combined_arms.bridge.crossing_receipt的used_work/cargo_work=0/budget_work=7500；used_work为两任务增量之和，不是0。未通过可排队，完整通过须出口事件。粮食移动扣4、待命扣2，按提示提交全员resource_ledger。')});save(engine+'-turn1',state)
 w=state['war_state'];missions.validate(w)
 tasks=[u['crossing'] for u in w['red_units']];receipt=w['combined_arms']['bridge']['crossing_receipt']
 check(len(tasks)==2 and sum(t['last_work'] for t in tasks)>0,engine+' actual crossing tasks receive service')
 check(receipt['used_work']+receipt['cargo_work']<=receipt['budget_work']+.003,engine+' shared work budget respected')
 check(not w['engagements'] and all(u['personnel']['casualties']==0 for _,u in missions.units(w)),engine+' no invented firing or casualties')
 check(w['historical_initial']==json.load(open(root/(engine+'-initial.json')))['war_state']['historical_initial'],engine+' source snapshot unchanged')
 check(all(t['source']==('dsh_model_estimate' if engine=='narrative' else 'afsim_native_estimate') for t in tasks),engine+' task provenance honest')
 if engine=='afsim' and not (root/'counterfactual.json').exists():
  before=copy.deepcopy(w);v,rev=view(sid)
  comparison=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':1,'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units'] if u['team']=='red']});save('counterfactual',comparison)
  check(call('GET',f'/api/sessions/{sid}')['war_state']==before,'readonly native comparison leaves main unchanged')
  check(not any(u.get('crossing') for u in comparison['alternative']['red_units']),'cancelled move removes crossing service in same-prior branch')
save('live-result',{'passed':True,'checks':checks,'session_ids':ids,'full_campaign_verified':False,'historical_calibration':False})
