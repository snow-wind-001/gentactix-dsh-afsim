"""Run an actual DSH native planner operation for restoration/cancellation QA."""
import argparse,json,urllib.error,urllib.request,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--phase',choices=['initial','cancel'],required=True);a=p.parse_args()
if not a.live:p.error('Use --live on owned QA18998')
r=Path('.cache/qa/dsh-effects');sid=json.load(open(r/'session-ids.json'))['afsim'];base='http://127.0.0.1:18998/api/sessions/'+sid

def call(method,path='',data=None):
 req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
 try:
  with urllib.request.urlopen(req,timeout=1200) as f:return f.status,json.load(f)
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
v=call('GET','/commands')[1];rev={'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
if a.phase=='initial':
 blue=next(u for u in v['units'] if u['team']=='blue');status,data=call('PUT','/commands',{**rev,'control_team':'red','director':True,'no_fire':True,'unit_agents':[],'orders':[{'unit_id':blue['id'],'action':'hold','duration':'next'}]});assert status==200,data
 v=call('GET','/commands')[1];rev={'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
message=('实际读取get_afsim_observation和retrieve_history，明确区分计算部署与历史资料。红方571团按当前坐标向正北移动约100米，蓝方3RAR执行已确认待命。不得开火。只提交合法命令和各单位公开依据，不编造兵力变化。' if a.phase=='initial' else '实际读取全部原生态势、完整累计变化及历史资料，核对补给与目标。双方本轮不得射击，只在确认任务与资源后明确待命；解释本轮公开决策依据，不提交完整战局。')
before=call('GET')[1];(r/('native-'+a.phase+'-before.json')).write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
status,data=call('POST','/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':message});(r/('native-'+a.phase+'-response.json')).write_text(json.dumps({'status':status,'body':data},ensure_ascii=False,indent=2)+'\n');print('native',a.phase,'HTTP',status,flush=True)
