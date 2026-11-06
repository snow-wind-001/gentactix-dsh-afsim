"""Create a numerical QA game through normal version-pinned API; no turn runs."""
import json
from pathlib import Path
import urllib.request

from tools.qa.campaign_plan_fixture import inputs,NOTE

ROOT=Path('.cache/qa/campaign-plan-2026-10-31/browser')


def call(method,path,data=None):
    request=urllib.request.Request('http://127.0.0.1:19108/api'+path,method=method,
        headers={'Content-Type':'application/json'},data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None)
    with urllib.request.urlopen(request,timeout=180) as response:return json.load(response)


if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True);path=ROOT/'ui-session.json'
    if path.exists():
        result=call('GET','/sessions/'+json.loads(path.read_text())['session_id'])
        print('Existing UI QA retained:',result['session_id'],result['turn_count'])
    else:
        s,p=inputs();created=call('POST','/sessions',dict(scenario='多方向目标图前端验收（数值QA）',
            battle=s['definition']['battle'],time_step='30分钟',product_mode='historical',simulation_mode='open',
            execution_backend='afsim',agent_mode='native',historical_parameters=p,historical_initial_version='1.2.0'))
        sid=created['session_id'];result=call('POST','/sessions/'+sid+'/init');view=call('GET','/sessions/'+sid+'/commands')
        call('PUT','/sessions/'+sid+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
            control_team='red',director=True,no_fire=False,intent=NOTE+' 全部部队预置持续待命；前端随后单独改变两个方向命令。',
            orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=10) for u in view['units']]))
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2));print('Created UI QA:',sid)
