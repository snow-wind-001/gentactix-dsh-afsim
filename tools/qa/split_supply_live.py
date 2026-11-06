"""Real DSH decisions -> native AFSIM -> read-only DSH analysis on an isolated API."""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-analysis',action='store_true');args=parser.parse_args()
    root=Path('.cache/qa/split-supply-ui/live');root.mkdir(parents=True,exist_ok=True)
    sid=json.loads(Path('.cache/qa/split-supply-ui/runtime/session-id.json').read_text())['session_id']
    base='http://127.0.0.1:18994/api/sessions/'+sid
    def call(path='',value=None,method=None):
        request=urllib.request.Request(base+path,data=None if value is None else json.dumps(value).encode(),
            headers={'Content-Type':'application/json'},method=method)
        with urllib.request.urlopen(request,timeout=1900) as response:return json.load(response)
    def save(name,value):
        (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def revision(c):return {'expected_turn':c['turn'],'revision':c['revision'],'world_version':c['world_version']}
    started=time.monotonic()
    if args.resume_analysis:
        before=json.loads((root/'before.json').read_text());after=json.loads((root/'after.json').read_text())
        assert call()['war_state']==after['war_state'],'Checkpoint changed; do not replay a committed turn'
    else:
        before=call();save('before.json',before)
        command=call('/commands')
        command=call('/commands',{**revision(command),'orders':[],'control_team':'red','director':True,'no_fire':True,
            'intent':'验证独立粮弹配送：双方全部单位原地补给粮食，弹药满载，不射击、不移动。'},'PUT')
        after=call('/next',{**revision(command),'batch_id':uuid.uuid4().hex,
            'instruction':'请对双方每个可用单位下达resupply，原地补给。全部弹药满载，重点补粮，不射击、不移动。'})
        save('after.json',after)
    world=after['war_state'];rows=world['mission']['ledger']
    checks={'advanced_one_turn':after['turn_count']==before['turn_count']+1,
        'native_success':world['afsim']['returncode']==0,
        'all_resupply':all(row['action']=='resupply' for row in rows),
        'food_only':all(row['food_received']==8 and row['ammo_received']==0 and row['delivery']==4 for row in rows),
        'clock_30m':world['current_time']=='1938-03-31 01:00',
        'ds_had_real_run':after['engine_meta']['tokens']>0}
    print(json.dumps({'next_checks':checks,'elapsed_seconds':round(time.monotonic()-started,2)}),flush=True)
    assert all(checks.values()),checks
    started=time.monotonic()
    analyzed=call('/chat',{'message':'请调用工具核对当前每个单位最近一轮粮食到货、弹药到货、运输质量当量和耗粮量。解释为什么弹药满载仍能收到粮食。区分模型工作量与真实重量；只读分析，不下令。'})
    save('chat.json',analyzed)
    checks['chat_world_unchanged']=analyzed['war_state']==world
    checks['chat_completed']=analyzed['engine_meta']['finish_reason']=='completed'
    result={'passed':all(checks.values()),'checks':checks,'session_id':sid,'real_model':True,
            'next_meta':after['engine_meta'],'chat_meta':analyzed['engine_meta'],
            'chat_seconds':round(time.monotonic()-started,2)}
    save('result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
    print(analyzed['chat_messages'][-1]['content'],flush=True)
    assert result['passed']


if __name__=='__main__':main()
