"""Real frozen backend acceptance for combined arms and strict source replay."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
base='http://127.0.0.1:18902'
out=Path('.cache/qa/map-workbench');out.mkdir(parents=True,exist_ok=True)
def call(method,path,payload=None):
    request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
        data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None)
    with urllib.request.urlopen(request,timeout=900) as response:return json.load(response)
def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
assert call('GET','/openapi.json')['info']['version']=='3.4.0'
assert call('GET','/api/health')['afsim']['available']
assert len(call('GET','/api/missions')['missions'])==65
sid=call('POST','/api/sessions',{'scenario':'3.4.0冻结包团级教学验收','mission_id':'CA-AJ18-v1',
    'execution_backend':'afsim','persist_roles':False})['session_id']
path='/api/sessions/'+sid
initial=call('POST',path+'/init')
view=call('GET',path+'/commands')
rev=lambda v:{'expected_turn':v['turn'],'revision':v['revision'],'world_version':v['world_version']}
orders=[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']]
actor=next(u for u in view['units'] if u['team']=='red')
target=next(u for u in view['units'] if u['team']=='blue')
next(o for o in orders if o['unit_id']==actor['id']).update(action='air_support',target_id=target['id'])
view=call('PUT',path+'/commands',{**rev(view),'director':True,'orders':orders})
final=call('POST',path+'/next',{**rev(view),'batch_id':'frozen-340-manual'})
assert final['turn_count']==1 and final['afsim']['model_skipped']
assert final['afsim']['source']=='dsh_native_mcp_controller'
assert final['war_state']['air_operations']['missions']
for u in final['war_state']['red_units']+final['war_state']['blue_units']:
    p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
    for e in u['equipment']:assert e['committed']==e['operational']+e['damaged']+e['destroyed']
result={'passed':True,'version':'3.4.0','combined_session':sid,'native_mcp':True,'real_afsim':True,'ledger_conserved':True}
print(json.dumps(result),flush=True)
historical=call('POST','/api/sessions',{'scenario':'湘江严格回放','battle':'红军长征-湘江战役-1934.11.25至1934.12.01',
    'simulation_mode':'replay','execution_backend':'afsim'})['session_id']
hp='/api/sessions/'+historical
frame=call('POST',hp+'/init');total=frame['war_state']['history_replay']['total']
for n in range(total-1):frame=call('POST',hp+'/next',{'expected_turn':n})
assert frame['war_state']['history_replay']['status']=='completed'
assert not frame['war_state']['red_units'] and not frame['war_state']['blue_units']
assert frame['afsim']['phase']=='historical_replay'
result.update(history_session=historical,history_frames=total)
print(json.dumps({'history_passed':True,'frames':total}),flush=True)
if args.live:
    before=sha(final['war_state'])
    final=call('POST',path+'/chat',{'message':'请通过原生观察工具核对双方6个编组与桥梁的当前状态，用100字简述当前目标和损失来源。只读分析，不修改战局，不把教学数据写成历史统计。'})
    assert sha(final['war_state'])==before
    assert final['engine_meta']['finish_reason']=='completed'
    assert final['chat_messages'][-1]['content'].strip()
    result.update(real_dsh_analysis=True,analysis_world_unchanged=True)
    (out/'frozen-dsh-answer.txt').write_text(final['chat_messages'][-1]['content'])
    print(json.dumps({'real_dsh_analysis':True,'world_unchanged':True}),flush=True)
(out/'frozen-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
