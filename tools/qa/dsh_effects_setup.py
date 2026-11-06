"""Create two owned sourced-unit QA sessions; all numbers/deployments are estimates."""
import argparse,copy,json,time,urllib.request,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live against owned isolated API18998')
r=Path('.cache/qa/dsh-effects')
def call(method,path,value=None):
 req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,headers={'Content-Type':'application/json'},data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
 with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
def save(n,v):(r/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
deadline=time.monotonic()+20
while True:
 try:health=call('GET','/api/health');break
 except OSError:
  if time.monotonic()>=deadline:raise
  time.sleep(.2)
assert not health['build']['restart_required']
old=[]
for row in call('GET','/api/sessions')['sessions']:
 d=call('GET','/api/sessions/'+row['session_id']);old.append({'session_id':row['session_id'],'world':d['war_state']})
save('previous-worlds',old)
parent=json.load(open('.cache/qa/dsh-resources/narrative-draft.json'));params=copy.deepcopy(parent['parameters']);center=params['area']['center']
facts={u['id']:u for u in parent['initial']['definition']['units']}
for identity,actor in params['actors'].items():
 actor['position']={'lat':center['lat']+(.0027 if facts[identity]['team']=='red' else -.0027),'lng':center['lng']}
 actor['assumption']+='；命令效果QA距中心约300米，非历史部署。'
params['assumptions']+='；此次仅验证公开命令、位置及交战效果一致性；局部迟滞目标是软件QA条件，不是历史胜负。'
sids={}
for engine in ('afsim','narrative'):
 draft=call('POST','/api/historical-scenarios/validate',{'parameters':params,'parent_draft_id':parent['id'],'execution_backend':engine,'operation_id':uuid.uuid4().hex});save(engine+'-draft',draft)
 sid=call('POST','/api/sessions',{'scenario':'命令效果控制QA-'+engine,'battle':parent['initial']['definition']['battle'],'product_mode':'historical','execution_backend':engine,'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id'],'persist_roles':False,'use_rag':True})['session_id'];sids[engine]=sid;save('session-ids',sids)
 initial=call('POST',f'/api/sessions/{sid}/init');save(engine+'-initial',initial)
 assert initial['war_state']['historical_initial']==parent['initial']
print(json.dumps({'created':sids,'original_qa_count':len(old),'historical_fit_verified':False}),flush=True)
