"""Actual read-only DSH review of committed command and casualty receipts."""
import argparse,json,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live against owned isolated API18998')
r=Path('.cache/qa/dsh-effects');sid=json.load(open(r/'session-ids.json'))['afsim'];base='http://127.0.0.1:18998/api/sessions/'+sid
home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions');offsets={str(p):p.stat().st_size for p in home.glob('*/*/session.v4.jsonl')}
def call(path='',value=None):
 req=urllib.request.Request(base+path,headers={'Content-Type':'application/json'},data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
 with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
def save(n,v):(r/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
before=call()['war_state'];save('native-review-before',before)
answer=call('/chat',{'message':'只读核对当前实际命令与战损。请从原生工具读取：每个单位最后动作、实际火力周期、当前人员、累计战斗减员、其中阵亡和负伤，简短列表，并核对人数账。说明这些结果来自哪个执行引擎；当前人数、位置是否为史实实到，是否已完成整场战役伤亡率标定？不要生成新命令，不改变主局，不把减员等同阵亡。'})
save('native-review',answer)
assert answer['engine_meta']['finish_reason']=='completed' and answer['war_state']==before and call()['war_state']==before
calls=[]
for path in home.glob('*/*/session.v4.jsonl'):
 offset=offsets.get(str(path),0)
 if path.stat().st_size==offset:continue
 with path.open('rb') as f:
  f.seek(offset)
  for line in f:
   if not line.endswith(b'\n'):continue
   row=json.loads(line)
   if row.get('type')=='tool/call':calls.append({'session_id':path.parent.name,'seq':row.get('seq'),**(row.get('data') or {})})
save('native-review-tools',calls)
assert any(c['name']=='get_afsim_observation' for c in calls)
save('native-review-results',{'readonly':True,'actual_native_observation':True,'all_free_text_verified':False,'engine_meta':answer['engine_meta']})
print('PASS actual native tool observation and unchanged main world; text needs semantic review',flush=True)
