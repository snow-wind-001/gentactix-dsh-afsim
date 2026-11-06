"""Verify actual DSH explanation of native firing-stop metadata after codebook fix."""
import argparse,json,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
if not a.live:p.error('Use --live against owned QA18998')
r=Path('.cache/qa/xiangjiang');sid=json.load(open(r/'session-ids.json'))['xinxu_nov28'];base='http://127.0.0.1:18998/api/sessions/'+sid
home=Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions');offsets={str(p):p.stat().st_size for p in home.glob('*/*/session.v4.jsonl')}
def save(n,v):(r/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(path='',data=None):
 req=urllib.request.Request(base+path,headers={'Content-Type':'application/json'},data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
 with urllib.request.urlopen(req,timeout=1200) as f:return json.load(f)
before=call()['war_state'];save('codebook-review-before',before)
answer=call('/chat',{'message':'请实际调用get_afsim_changes(mode=aggregate,since_turn=0)读取本局全程账，按返回的fire_stop_counts和fire_stop_reasons，简短列每单位代码6、8的含义和出现次数。代码0结合动作和fire_cycles解释，不能把待命认作射击。没有列出的代码不猜。说明程序已记录的停止条件，与未完成的真实历史因果标定有什么区别。不下令，不改变主局。'});save('codebook-review',answer)
assert answer['war_state']==before and call()['war_state']==before and answer['engine_meta']['finish_reason']=='completed'
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
save('codebook-review-tools',calls)
assert any(c['name']=='get_afsim_changes' and json.loads(c['arguments']).get('mode')=='aggregate' and json.loads(c['arguments']).get('since_turn')==0 for c in calls)
save('codebook-review-results',{'passed':True,'readonly':True,'actual_aggregate_tool':True,'all_free_text_verified':False,'engine_meta':answer['engine_meta']})
print('PASS real aggregate tool read and exact world preserved; review text separately',flush=True)
