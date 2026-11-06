"""Opt-in real production chat route over an already isolated QA world."""
import argparse,json,re,time,urllib.request
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--session',default='83e8aaf89608',choices=['83e8aaf89608','bfe68ccafa9c']);args=parser.parse_args()
if not args.live:parser.error('Actual configured model call requires --live')
root=Path('.cache/qa/state-observation-map-2026-11-01');root.mkdir(parents=True,exist_ok=True)
url='http://127.0.0.1:19132/api/sessions/'+args.session
def get():return json.load(urllib.request.urlopen(url,timeout=10))
prefix='' if args.session=='83e8aaf89608' else 'contrast-'
before=get();(root/(prefix+'production-chat-before.json')).write_text(json.dumps(before,ensure_ascii=False))
message=('请核对当前已提交战局的事实：当前T+几、本局累计已过多少秒、已登记计算单位总数、实际目标规则版本、当前目标是否达标、是否必须夺占据点、是否已通过完整历史过程验收。'
 '请使用get_afsim_observation不带ids，从offset=0分页读取完整登记名单，沿next_args读完；不能拿有变化的单位数当全部单位数。'
 '不调用不存在的工具，不补猜缺载字段。最后用一个JSON对象回答，键为turn、elapsed_seconds、unit_count、objective_policy、mission_condition、requires_town_occupation、full_history_accepted；其余中文解释请简短。不要执行任何动作。')
request=urllib.request.Request(url+'/chat',data=json.dumps({'message':message}).encode(),headers={'Content-Type':'application/json'},method='POST')
started=time.monotonic()
try:
 with urllib.request.urlopen(request,timeout=1000) as response:result={'http':response.status,'body':json.load(response)}
except urllib.error.HTTPError as exc:result={'http':exc.code,'body':json.load(exc)}
(root/(prefix+'production-chat-response.json')).write_text(json.dumps(result,ensure_ascii=False))
after=get();assert before['war_state']==after['war_state'],'Readonly chat changed battle state'
report={'http':result['http'],'elapsed_seconds':round(time.monotonic()-started,2),'battle_world_unchanged':True,'actual_production_route':True,'passed':False}
(root/(prefix+'production-chat-review.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
