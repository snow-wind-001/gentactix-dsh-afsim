"""One real DSH-only turn from the browser-edited, source-bound campaign input."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--draft',required=True)
    p.add_argument('--resume-session')
    args=p.parse_args()
    if not args.live:p.error('Use --live for the configured real DSH')
    root=Path('.cache/qa/synthetic-campaign-2026-10-31/dsh');root.mkdir(parents=True,exist_ok=True)
    base='http://127.0.0.1:19103'
    def call(method,path,data=None):
        request=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(request,timeout=1200) as r:return json.load(r)
        except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:1500]) from e
    tag='retry-' if args.resume_session else ''
    def save(name,d):(root/(tag+name+'.json')).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    if args.resume_session:
        sid=args.resume_session;initial=call('GET',f'/api/sessions/{sid}')
        assert initial['turn_count']==0,'Do not execute a committed turn twice'
        assert initial['war_state']==json.loads((root/'initial.json').read_text())['war_state']
    else:
        draft=json.loads((root.parent/'browser/scenario-drafts'/f'{args.draft}.json').read_text())
        edited=call('POST','/api/scenarios/validate',{'mission_id':draft['mission_id'],
            'configuration':copy.deepcopy(draft['configuration']),'parent_draft_id':draft['id'],'execution_backend':'narrative'})
        sid=call('POST','/api/sessions',{'scenario':'真实DSH：编辑后的会战合成编组QA',
            'battle':draft['historical_base']['initial']['definition']['battle'],'time_step':'30分钟',
            'product_mode':'synthetic','scenario_draft_id':edited['id'],
            'execution_backend':'narrative','persist_roles':False})['session_id']
        save('created',{'session_id':sid,'draft_id':edited['id']})
        initial=call('POST',f'/api/sessions/{sid}/init')
    save('initial',initial)
    world=initial['war_state'];selected=next(u for u in world['red_units'] if u['name']=='前端新增演习部队')
    v=call('GET',f'/api/sessions/{sid}/commands')
    revision=lambda cs:{'expected_turn':cs['turn'],**{k:cs[k] for k in ('revision','world_version')}}
    call('PUT',f'/api/sessions/{sid}/commands',{**revision(v),'control_team':'red','director':True,
        'no_fire':False,'unit_agents':[],'orders':[{'unit_id':u['id'],'duration':'next',
            **({'action':'move','destination':{'lat':selected['lat']+.0005,'lng':selected['lng']}}
               if u['name']==selected['name'] else {'action':'hold'})} for u in v['units']]})
    v=call('GET',f'/api/sessions/{sid}/commands')
    result={'passed':False,'session_id':sid,'actual_dsh':True,'checks':[]};save('result',result)
    try:
        after=call('POST',f'/api/sessions/{sid}/next',{**revision(v),'batch_id':uuid.uuid4().hex,
            'instruction':'执行全部已确认命令。新增演习部队按预算移动，其余待命；无交火不得造战斗损失。过程演员表覆盖实际六单位，继承的入场与历史来源不可改写。'})
        save('turn1',after);new=next(u for u in after['war_state']['red_units'] if u['name']==selected['name'])
        assert new['lat']!=selected['lat'] or new['lng']!=selected['lng']
        result['checks'].append('Real model moves the added exercise unit')
        assert new['exercise_unit_id']==selected['exercise_unit_id']
        assert after['war_state']['historical_initial']==world['historical_initial']
        result['checks'].append('Exercise identity and frozen history remain unchanged')
        assert len(after['war_state']['campaign']['actors'])==6
        assert all(u['personnel']['casualties']==0 for side in ('red','blue') for u in after['war_state'][side+'_units'])
        result['checks'].append('All six campaign rows remain; no fabricated battle losses')
        assert after['turn_count']==1 and not after['war_state'].get('afsim')
        result['checks'].append('DSH-only turn commits once without AFSIM effects')
        result['passed']=True
    finally:save('result',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
