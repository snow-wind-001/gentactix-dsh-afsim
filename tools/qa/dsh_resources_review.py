"""Real readonly native resource review after the explicit semantics clarification."""
import argparse,json,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');args=p.parse_args()
if not args.live:p.error('Use --live against the owned isolated API18998')
root=Path('.cache/qa/dsh-resources');sid=json.load(open(root/'session-ids.json'))['afsim'];base='http://127.0.0.1:18998/api/sessions/'+sid
home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions');offsets={str(p):p.stat().st_size for p in home.glob('*/*/session.v4.jsonl')}
def call(path='',data=None):
 req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
before=call()['war_state'];answer=call('/chat',{'message':'只读核对本局从开局到当前的粮弹收支。用每单位一行的简短表格列毛到货、粮食消耗、弹药消耗和当前粮食；再说明delivery的模型含义，以及燃油净减少能否全归于移动。实际读取工具，不下令，不用旧对话替代本轮数据。'})
(root/'native-analysis-clarified.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2)+'\n')
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
assert any(c['name']=='get_afsim_changes' and json.loads(c['arguments']).get('mode')=='aggregate' for c in calls)
(root/'native-analysis-clarified-tools.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2)+'\n')
(root/'native-analysis-clarified-results.json').write_text(json.dumps({'readonly':True,'actual_aggregate_tool':True,'all_free_text_verified':False,'engine_meta':answer['engine_meta']},ensure_ascii=False,indent=2)+'\n')
print('PASS actual aggregate read and unchanged native world; prose requires separate review',flush=True)
