"""Real command/effect consistency using source-bound, explicitly estimated QA units."""
import argparse,copy,json,urllib.error,urllib.request,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live with the owned isolated API18998')
r=Path('.cache/qa/dsh-effects');ids=json.load(open(r/'session-ids.json'));result={'passed':False,'checks':[],'historical_fit_verified':False}
def save(n,v):(r/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(method,path,value=None):
 req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:1600]) from e

def check(ok,s):
 if not ok:raise AssertionError(s)
 result['checks'].append(s);print('PASS',s,flush=True)
def view(sid):
 v=call('GET',f'/api/sessions/{sid}/commands');return v,{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
def world(sid):return call('GET',f'/api/sessions/{sid}')['war_state']
def step(sid,orders,instruction,no_fire=False):
 if orders is not None:
  _,rev=view(sid);call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,'no_fire':no_fire,'unit_agents':[]})
 _,rev=view(sid);return call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
try:
 check(not call('GET','/api/health')['build']['restart_required'],'fresh source and control endpoints')
 sid=ids['afsim'];first=json.load(open(r/'native-initial-response.json'))['body']
 check(world(sid)==first['war_state'],'cancel preserved the exact native first-turn world')
 check(not first['war_state']['afsim']['model_skipped'],'native first step actually used DSH planning')
 exported=call('GET',f'/api/sessions/{sid}/export')['session'];turn=next(t for t in exported['trajectory'] if t['turn']==1)
 tools={e.get('name') for run in turn['runs'] for e in run.get('events',[]) if e.get('type')=='tool/call'}
 save('native-planner-tools',sorted(tools));check({'get_afsim_observation','retrieve_history'}<=tools,'native planner actually observes and retrieves')
 v,_=view(sid);orders=[{'unit_id':u['id'],'action':'fire','target_id':next(e['id'] for e in v['units'] if e['team']!=u['team']),'duration':'next'} for u in v['units']]
 current=step(sid,orders,'双方按确认命令实际交火，战果由AFSIM产生，不套历史损失配额。');save('native-turn2',current)
 w=current['war_state'];check(w['afsim']['model_skipped'],'manual native firefight needs no extra planning call')
 check(all(u['formation']['last_execution']['fire_cycles']>0 for t in ('red','blue') for u in w[t+'_units']),'native firing receipts match both fire orders')
 check(all(u['personnel']['casualties']>0 for t in ('red','blue') for u in w[t+'_units']),'actual native fire produces positive recorded attrition on both sides')
 frozen=copy.deepcopy(w);factual=next(r0 for r0 in w['afsim']['orders'] if r0['unit']==w['red_units'][0]['name'])
 branch=call('POST',f'/api/sessions/{sid}/counterfactual',{'turn':2,'mode':'mission','orders':[factual]});save('native-counterfactual',branch)
 check(branch['alternative']['red_units'][0]['personnel']['casualties']==0,'withholding blue fire removes native red combat losses from the same prior state')
 check(world(sid)==frozen,'native intervention is readonly')
 sid=ids['narrative'];frozen_initial=copy.deepcopy(world(sid));v,_=view(sid)
 red=next(u for u in v['units'] if u['team']=='red');point={'lat':red['position']['lat']+.0009,'lng':red['position']['lng']}
 orders=[{'unit_id':u['id'],'action':'move' if u['team']=='red' else 'hold','duration':'next',**({'destination':point} if u['team']=='red' else {})} for u in v['units']]
 after=step(sid,orders,'AFSIM关闭。执行已确认的位置命令：红方北移约100米，蓝方待命，不开火。双方本轮无补给到货，按既有粮耗和油料预算提交完整收支。坐标与公开决策必须对应实际命令，不能伪造原生回执。',True);save('dsh-turn1',after)
 w=after['war_state'];check(w['dsh_execution']['command_validation_version']=='dsh-command-effects-1' and not w.get('afsim'),'DSH estimate carries the verified command-effect contract without AFSIM')
 from gentactix import missions
 check(missions.distance(w['red_units'][0],point)<.01,'real DSH honors the selected red map destination')
 check(missions.distance(w['blue_units'][0],frozen_initial['blue_units'][0])<.01 and not w['engagements'],'held blue unit stays in place and does not fire')
 v,_=view(sid);red=next(u for u in v['units'] if u['team']=='red')
 orders=[{'unit_id':u['id'],'action':'hold' if u['team']=='red' else 'fire','duration':'next',**({'target_id':red['id']} if u['team']=='blue' else {})} for u in v['units']]
 after=step(sid,orders,'只有蓝方按确认fire命令射击红方，红方hold不反击，不要把待命变成自动还击。按当前资源与条件估计效果并对应实际事件；双方无到货，完整收支、人员分类和公开决策一致。不设伤亡下限。');save('dsh-turn2',after)
 w=after['war_state'];check(all(e['attacker']==w['blue_units'][0]['name'] and e['weapon_action']=='fire' for e in w['engagements']),'actual DSH engagement events obey the authorized blue-only fire command')
 check(w['blue_units'][0]['personnel']['casualties']==0,'no unexplained combat loss is added to the unengaged blue target')
 after=step(sid,[],'由你自主判断双方各单位最合适的本轮行动。先核对当前单位与资源，双方所有可行动单位都要明确命令和公开依据；结果坐标、交战、目标及战斗减员须对应实际命令，不虚构历史战果。');save('dsh-turn3',after)
 main=copy.deepcopy(after['war_state']);check(len(main['mission']['last_orders'])==2,'DSH autonomous step still covers both actual units')
 v,_=view(sid)
 for u in v['units']:
  evidence=call('GET',f'/api/sessions/{sid}/unit-decisions?unit_id='+u['id']+'&start_turn=3&end_turn=3&limit=25')
  save('decision-'+u['team'],evidence)
  check(bool(evidence['items']) and evidence['items'][0]['action']==next(o['action'] for o in main['mission']['last_orders'] if o['unit']==u['name']),u['team']+' public decision matches its actual third-turn command')
 alternate=call('POST',f'/api/sessions/{sid}/counterfactual',{'turn':2,'mode':'mission','orders':[]});save('dsh-counterfactual',alternate)
 check(all(u['personnel']['casualties']==0 for t in ('red','blue') for u in alternate['alternative'][t+'_units']),'readonly DSH all-hold branch cannot invent combat losses')
 check(world(sid)==main and alternate['read_only'],'DSH intervention does not alter the committed main world')
 check(main['current_time']=='1951-10-05 05:30' and main['historical_initial']==frozen_initial['historical_initial'],'three exact half-hour steps preserve sourced identities and facts')
 result.update(passed=True,sessions=ids)
except Exception as e:result['error']=str(e);raise
finally:save('live-results',result)
