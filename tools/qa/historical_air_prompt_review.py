"""One real DSH continuation after removing contradictory air-action examples."""
import argparse,json,time,urllib.request,urllib.error,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Requires owned API18998 and real model use')
r=Path('.cache/qa/historical-air');base='http://127.0.0.1:18998'
def save(n,v):(r/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(method,path,data=None):
 req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
 except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:1800])
end=time.monotonic()+90
while True:
 try:health=call('GET','/api/health');break
 except OSError:
  if time.monotonic()>end:raise
  time.sleep(.2)
assert not health['build']['restart_required']
for row in json.load(open(r/'before-prompt-restart.json')):
 restored=call('GET','/api/sessions/'+row['session_id'])
 assert restored['war_state']==row['world']
save('cold-restore-current',{'passed':True,'worlds':32,'exact_equal':True})
source=json.load(open(r/'session-ids.json'))['narrative'];original=call('GET','/api/sessions/'+source)['war_state']
def view(sid):
 v=call('GET',f'/api/sessions/{sid}/commands');return v,{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
if (r/'prompt-branch.json').exists():sid=json.load(open(r/'prompt-branch.json'))['session_id']
else:
 _,rev=view(source);branch=call('POST',f'/api/sessions/{source}/commands/open-branch',rev);sid=branch['session_id'];save('prompt-branch',{'session_id':sid,'source_session_id':source})
state=call('GET',f'/api/sessions/{sid}')
if state['turn_count']==1:
 v,rev=view(sid);red=next(u for u in v['units'] if u['team']=='red');blue=next(u for u in v['units'] if u['team']=='blue')
 orders=[{'unit_id':red['id'],'action':'air_support','air_pool':'ww2.cacw.group5','target_id':blue['id'],'duration':'next'},
         {'unit_id':blue['id'],'action':'hold','duration':'next'}]
 call('PUT',f'/api/sessions/{sid}/commands',{**rev,'control_team':'red','director':True,'no_fire':False,'orders':orders,'unit_agents':[]})
 _,rev=view(sid)
 print('DSH real continuation with corrected air example',flush=True)
 state=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,
  'instruction':'严格执行已确认人工命令：第57师以ww2.cacw.group5的2架任务包对原目标航空支援，日方待命；不移动、不补给、不开地面火。只估计本轮过程。航空弹药再扣2、燃油再扣4；独立库存余额应为4和8。交战weapon_action使用air_support，不能用bombard代替空袭。人员分类和装备状态采用当前提示契约，损失按防护/掩体和实际投入估计，不追求固定历史配额。'})
 save('prompt-continuation',state)
w=state['war_state'];pool=w['air_operations']['pools']['ww2.cacw.group5'];assert state['turn_count']==2 and pool['ordnance']==4 and pool['fuel']==8 and pool['sorties']==4
assert w['air_operations']['missions'][0]['source']=='dsh_model_estimate'
assert all(e['weapon_action']=='air_support' for e in w['engagements'])
assert call('GET','/api/sessions/'+source)['war_state']==original
export=call('GET',f'/api/sessions/{sid}/export')['session'];record=next(t for t in export['trajectory'] if t['turn']==2)
save('prompt-continuation-result',{'passed':True,'branch_session_id':sid,'original_unchanged':True,'turn':2,'run_count':len(record['runs']),
 'manual_pool_preserved':record['after']['mission']['last_orders'][0].get('air_pool')=='ww2.cacw.group5',
 'engine_meta':state['engine_meta'],'air_assets':pool,'all_free_text_verified':False,'historical_fit_verified':False})
print('PASS corrected prompt actual DSH continuation; native runtime calls',len(record['runs']),flush=True)
