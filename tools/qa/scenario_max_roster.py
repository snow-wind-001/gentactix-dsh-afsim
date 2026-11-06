"""Real final-bundle AFSIM check for the documented 12+12 formation limit."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=18942);a=p.parse_args()
assert 18900<=a.port<=18999
API=f'http://127.0.0.1:{a.port}'
def call(method,path,payload=None):
    data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    req=urllib.request.Request(API+path,data=data,method=method,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)

sessions=call('GET','/api/sessions')['sessions'];sid=sessions[0]['session_id'];snap=call('GET','/api/sessions/'+sid)
config=copy.deepcopy(snap['settings']['synthetic_configuration']);mission=snap['settings']['mission_id'];parent=snap['settings']['scenario_draft_id']
cx,cy=snap['war_state']['center']
for side,sign in [('red',-1),('blue',1)]:
    seed=copy.deepcopy(config['teams'][side][0]);rows=[]
    for i in range(12):
        row=copy.deepcopy(seed);row['name']=('红方' if side=='red' else '蓝方')+f'上限验收编组{i+1}'
        row['position']={'lat':cx+(i-5.5)*.0005,'lng':cy+sign*.012};rows.append(row)
    config['teams'][side]=rows
draft=call('POST','/api/scenarios/validate',{'mission_id':mission,'configuration':config,'parent_draft_id':parent})
assert draft['afsim']['entity_count']==24
sid=call('POST','/api/sessions',{'scenario':'12+12源自史实参考的局部合成上限验收；不是历史兵力。','mission_id':mission,'execution_backend':'afsim','synthetic_configuration':config,'scenario_draft_id':draft['id'],'persist_roles':False})['session_id']
before=call('POST',f'/api/sessions/{sid}/init');view=call('GET',f'/api/sessions/{sid}/commands')
revision={k:view[v] for k,v in [('expected_turn','turn'),('revision','revision'),('world_version','world_version')]}
call('PUT',f'/api/sessions/{sid}/commands',{**revision,'director':True,'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']]})
view=call('GET',f'/api/sessions/{sid}/commands')
after=call('POST',f'/api/sessions/{sid}/next',{'batch_id':'max-24','expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version']})
assert after['afsim']['model_skipped'] and after['afsim']['entity_count']==24
assert [len(after['war_state'][t+'_units']) for t in ('red','blue')]==[12,12]
for side in ('red','blue'):
    for old,new in zip(before['war_state'][side+'_units'],after['war_state'][side+'_units']):
        assert new['personnel']['committed']==new['personnel']['current']+new['personnel']['casualties']+new['personnel']['noncombat_losses']==old['personnel']['committed']
result={'passed':True,'session_id':sid,'roster':[12,12],'turn':after['turn_count'],'native_source':after['afsim']['source'],'model_skipped':True}
(ROOT/'.cache/qa/history-process/max-roster.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
