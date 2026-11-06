"""Create a NEW isolated API case; no existing game or user configuration edits."""
import argparse
import json
from pathlib import Path
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    from tools.qa.transfer_campaign_fixture import campaign_inputs, NOTE
    root=Path('.cache/qa/transfer-window-2026-11-03/live-final')
    if (root/'live-case.json').exists():raise SystemExit('Preserve previous evidence')
    api='http://127.0.0.1:19318'
    def call(path,body=None,method=None):
        req=urllib.request.Request(api+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
            headers={'Content-Type':'application/json'},method=method)
        with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)
    s,p=campaign_inputs()
    created=call('/api/sessions',dict(scenario=NOTE,battle=s['definition']['battle'],time_step='30分钟',product_mode='historical',
        simulation_mode='open',execution_backend='afsim',agent_mode='native',persist_roles=True,historical_parameters=p,historical_initial_version='1.1.0'))
    sid=created['session_id'];initial=call('/api/sessions/'+sid+'/init',{})
    root.mkdir(parents=True,exist_ok=True)
    (root/'initial.json').write_text(json.dumps(initial,ensure_ascii=False,indent=2)+'\n')
    view=call('/api/sessions/'+sid+'/commands');units={u['name']:u for u in view['units']}
    agents=[units[n]['id'] for n in ('红一方面军第3军','红四方面军第4军')]
    intent=('四军转移软件验收，数值均为明确估计，不是完整历史复原；没有蓝方计算单位。'
        '每个原生单位Agent先用get_campaign_objectives核对本单位到达目标和资源条件，再用get_afsim_observation按本单位ID复核态势。'
        '用move和duration=until_arrived向自己的目标中心转移，宿主只提交预算内路段；不因没有敌军而待命或宣告胜利。'
        '不改人工命令，不编造敌人、损失、下级部队或到达事实。')
    call('/api/sessions/'+sid+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=False,no_fire=True,intent=intent,unit_agents=agents,
        orders=[dict(unit_id=units['红四方面军第30军']['id'],action='hold',duration='next')]),'PUT')
    info=dict(api=api,ui='http://127.0.0.1:19329',session_id=sid,turn=1,actor_count=4,native_decision_count=2,
        step_seconds=1800,command_unit=units['红一方面军第1军']['id'])
    (root/'live-case.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n')
    print('New isolated case',sid,'four sourced armies; two Native agents',flush=True)


if __name__=='__main__':main()
