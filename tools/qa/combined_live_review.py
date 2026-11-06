"""Read-only native intervention and real DSH observation on the completed demo."""
import hashlib
import json
from pathlib import Path
import urllib.request

BASE='http://127.0.0.1:8700/api/sessions/84b4267a9109'
OUT=Path('.cache/qa/combined-arms')
def call(path='',payload=None):
    data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    request=urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=900) as response:return json.load(response)
def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
before=call();view=call('/commands')
support=next(u for u in view['units'] if u['team']=='red' and '支援' in u['name'])
revision={'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version']}
comparison=call('/commands/compare',{**revision,'turn':7,'orders':[{'unit_id':support['id'],'action':'hold','duration':'next'}]})
assert comparison['mode']=='controlled_afsim' and comparison['read_only']
assert comparison['external_execution']['source']=='dsh_native_mcp_controller'
assert any(m['delta']!=0 for m in comparison['metrics'])
assert fingerprint(before['war_state'])==fingerprint(call()['war_state'])
(OUT/'live-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
print(json.dumps({'comparison':True,'nonzero_metrics':sum(m['delta']!=0 for m in comparison['metrics']),'world_unchanged':True}),flush=True)
after=call('/chat',{'message':'请使用get_afsim_observation查证最新6个单位的当前态势、桥梁施工和战役目标。解释本局最终胜负、人员装备账是否连续、反复跨河为何被阻止，以及航空打击是否等同于目标占领。不得将教学数据写成历史战果；不要生成新命令或内部思维链。请用400字以内公开说明。'})
assert fingerprint(before['war_state'])==fingerprint(after['war_state'])
answer=after['chat_messages'][-1]['content']
assert answer.strip() and after['engine_meta']['finish_reason']=='completed'
(OUT/'live-review.json').write_text(json.dumps({'passed':True,'world_unchanged':True,'answer':answer,'engine_meta':after['engine_meta']},ensure_ascii=False,indent=2))
print(json.dumps({'dsh_review':True,'world_unchanged':True,'answer_chars':len(answer),'engine_ms':after['engine_meta']['elapsed_ms']}))
