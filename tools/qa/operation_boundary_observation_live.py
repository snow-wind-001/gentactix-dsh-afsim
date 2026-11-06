"""Two actual production /chat queries over cold-restored boundary worlds."""
import argparse
import json
import math
from pathlib import Path
import time
import urllib.request

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Actual configured model calls require --live')
root=Path('.cache/qa/operation-boundary-2026-11-02');reviews=[]
for engine in ('afsim','narrative'):
    case=json.loads((root/engine/'case.json').read_text());sid=case['session_id'];url='http://127.0.0.1:19136/api/sessions/'+sid
    before=json.load(urllib.request.urlopen(url,timeout=15));world=before['war_state'];unit=next(u for u in world['red_units'] if u['name']=='第159师')
    row=next(r for r in world['unit_participation']['actors'].values() if r['name']==unit['name'])
    expected=dict(turn=before['turn_count'],elapsed_seconds=world['simulation_clock']['elapsed_seconds'],unit_count=6,
        personnel_current=unit['personnel']['current'],casualties=unit['personnel']['casualties'],food=unit['logistics']['food'],
        status=row['status'],zone='outside' if row['status']=='offmap' else 'inside',controls_objectives=row['status']=='deployed',route_id='red-north',full_history_accepted=False)
    marker='BOUNDARY-FACT-'+sid
    message=(marker+'：只读核对当前已提交战局。请真实调用get_afsim_observation先读取全名单，再以ids=["'+case['unit_id']+'"]、detail=true读取第159师和该阵营登记通路。'
        '不要下令、不要补猜。当前第几轮、累计秒数、登记单位总数，第159师现有人数/累计战斗减员/粮食工作量、参与status、operation_zone、controls_objectives资格和登记route_id分别是什么？'
        '参与资格不是夺占目标的结果，完整历史未曾验收。最后用一个JSON对象回答：turn,elapsed_seconds,unit_count,personnel_current,casualties,food,status,zone,controls_objectives,route_id,full_history_accepted。')
    request=urllib.request.Request(url+'/chat',data=json.dumps({'message':message}).encode(),headers={'Content-Type':'application/json'},method='POST')
    started=time.monotonic()
    with urllib.request.urlopen(request,timeout=1000) as response:body=json.load(response)
    (root/(engine+'-query-response.json')).write_text(json.dumps(body,ensure_ascii=False))
    latest=json.load(urllib.request.urlopen(url,timeout=15));assert latest['war_state']==world
    text=body['chat_messages'][-1]['content'];answers=[]
    for i,c in enumerate(text):
        if c!='{':continue
        try:value,_=json.JSONDecoder().raw_decode(text[i:])
        except ValueError:continue
        if isinstance(value,dict) and set(expected)<=set(value):answers.append(value)
    assert len(answers)==1, 'Missing or ambiguous complete answer'
    answer=answers[0]
    for key,value in expected.items():
        if key=='food':assert isinstance(answer[key],(int,float)) and math.isclose(answer[key],value,abs_tol=1e-6)
        else:assert answer[key]==value,(engine,key,answer[key],value)
    proof=dict(engine=engine,session_id=sid,passed=True,expected=expected,answer=answer,world_unchanged=True,
        elapsed_seconds=round(time.monotonic()-started,2),marker=marker,native_call_review_pending=True)
    (root/(engine+'-query-review.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');reviews.append(proof)
    print('PASS',engine,'production factual reply',proof['elapsed_seconds'],flush=True)
(root/'query-review.json').write_text(json.dumps({'passed':True,'cases':reviews,'scope':'Actual production fact answers/world immutability; Native detail-call evidence reviewed separately'},ensure_ascii=False,indent=2)+'\n')
