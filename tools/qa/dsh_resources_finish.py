"""Finish the owned six-turn resource QA and verify terminal state immutability."""
import argparse,copy,json,urllib.error,urllib.request,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live with the owned isolated API18998')
r=Path('.cache/qa/dsh-resources');sid=json.load(open(r/'session-ids.json'))['narrative'];base='http://127.0.0.1:18998/api/sessions/'+sid
result={'passed':False,'checks':[],'historical_fit_verified':False}
def save(n,v):(r/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(path='',value=None,expected=200):
 req=urllib.request.Request(base+path,method='GET' if value is None else 'POST',headers={'Content-Type':'application/json'},data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(req,timeout=1200) as f:status,data=f.status,json.load(f)
 except urllib.error.HTTPError as e:status,data=e.code,json.loads(e.read())
 if status!=expected:raise RuntimeError(str(status)+': '+str(data)[:1400])
 return data
def check(ok,s):
 if not ok:raise AssertionError(s)
 result['checks'].append(s);print('PASS',s,flush=True)
try:
 before=call()['war_state'];expected=json.load(open(r/('narrative-turn6.json' if a.resume else 'narrative-turn4.json')))['war_state']
 check(before==expected,'owned resource world exactly matches its last recorded turn')
 result['reused_completed_turns']=a.resume
 instructions={5:'双方hold，无交火无到货，各消耗2粮食工作量，其他资源不变；完整resource_ledger。supply_status只用未切断/已切断/未知，未补给不表示线路切断。',
 6:'红方hold无到货；蓝方resupply，只安排2份估计小批到货（粮食和弹药各2），各单位仍消耗2粮食工作量，蓝方另估计消耗运补燃油3升。其余分类received/spent为0，除蓝方supply_node.stock扣2外仓库不得改变。全程无交火。严格提交收支与单位变化，是否完成6轮迟滞目标交程序判定，不宣称历史胜利。'}
 for turn,instruction in instructions.items():
  if a.resume:after=json.load(open(r/('narrative-turn'+str(turn)+'.json')))
  else:
   v=call('/commands');after=call('/next',{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version'],'batch_id':uuid.uuid4().hex,'instruction':instruction})
   save('narrative-turn'+str(turn),after)
  w=after['war_state']
  check(w['dsh_execution']['resource_ledger_version']=='dsh-resource-ledger-1' and all(x['food_spent']==2 for x in w['mission']['ledger']),'turn '+str(turn)+' has verified model spending')
  check(all(u['personnel']['casualties']==0 for team in ('red','blue') for u in w[team+'_units']),'turn '+str(turn)+' has no invented fire losses')
  before=w
 check(w['mission']['status']=='completed' and w['mission']['winner']=='blue' and w['current_time']=='1951-10-05 07:00','program goal completes after six exact half-hour steps')
 check(w['red_units'][0]['logistics']['food']==66 and w['blue_units'][0]['logistics']=={'food':70,'ammo':84},'all six rounds preserve cumulative stock accounts')
 blue=next(x for x in w['mission']['ledger'] if x['unit']==w['blue_units'][0]['name'])
 check(blue['delivery']==2 and blue['food_spent']==2,'final positive gross arrival is distinct from unchanged blue food')
 v=call('/commands');rejected=call('/next',{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version'],'batch_id':uuid.uuid4().hex},expected=409);save('finished-rejection',rejected)
 check(call()['war_state']==w,'finished DSH goal rejects extra advancement without changing stocks')
 result['passed']=True
except Exception as e:result['error']=str(e);raise
finally:save('finish-results',result)
