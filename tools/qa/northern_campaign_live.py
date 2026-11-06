"""Normal API preparation and read-only audits for the actual northern-front draft.

Physical turns are deliberately left to the frontend. No parameter filling,
host combat calculation, historical outcome forcing or existing-game migration.
"""
import argparse
import json
import math
from pathlib import Path
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare-afsim','configure','combat-orders','hold-manual','audit'])
    parser.add_argument('root',type=Path)
    parser.add_argument('engine',choices=['narrative','afsim'])
    args=parser.parse_args();root=args.root
    source=json.loads((root/'live-case.json').read_text());api=source['api']
    folder=root/args.engine;folder.mkdir(exist_ok=True)
    def save(name,value):
        path=folder/name
        if path.exists():raise ValueError('Preserve earlier evidence: '+str(path))
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    def call(path,body=None,method=None):
        request=urllib.request.Request(api+'/api'+path,method=method or ('POST'if body is not None else 'GET'),
            headers={'Content-Type':'application/json'},data=json.dumps(body,ensure_ascii=False).encode()if body is not None else None)
        with urllib.request.urlopen(request,timeout=180)as response:return json.load(response)
    if args.action=='prepare-afsim':
        if args.engine!='afsim':parser.error('AFSIM variant only')
        if (folder/'variant.json').exists():raise ValueError('AFSIM variant already exists')
        draft=json.loads(Path(source.get('draft_path',root/'resume-browser/draft.json')).read_text())
        variant=call('/historical-scenarios/validate',dict(parent_draft_id=draft['id'],parameters=draft['parameters'],
            required_models=['personnel-rations-1','movement-feedback-1'],execution_backend='afsim'))
        assert variant['parameters']==draft['parameters'],'Do not replace the actual generated parameters'
        save('variant.json',variant)
        created=call('/sessions',dict(scenario='武汉北线双方向软件验证；具名历史身份与明确估计参数，不是完整武汉会战历史标定。',
            battle=draft['initial']['definition']['battle'],time_step='1小时',product_mode='historical',simulation_mode='open',execution_backend='afsim',
            agent_mode='native',persist_roles=True,scenario_draft_id=variant['id'],historical_parameters=variant['parameters'],
            historical_initial_version='1.2.0'))
        snapshot=call('/sessions/'+created['session_id']+'/init',{})
        save('created.json',dict(session_id=created['session_id'],actual_afsim_load=True,second_independent_generation=False))
        save('initial.json',snapshot)
        print('Created AFSIM variant from identical generated parameters',created['session_id']);return
    info=source if args.engine=='narrative'else json.loads((folder/'created.json').read_text())
    sid=info['session_id'];base='/sessions/'+sid
    session=call(base+'/export')['session'];world=session['war_state']
    if args.action=='hold-manual':
        assert session['turn_count']==2 and not call(base+'/progress')['active']
        view=call(base+'/commands');agents=view['unit_agents'];assert len(agents)==2
        orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=20)
                for u in view['units']if u['id']not in agents]
        changed=call(base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
            control_team='red',director=True,no_fire=False,intent=view['intent'],unit_agents=agents,orders=orders),'PUT')
        assert changed['unit_agents']==agents and call(base+'/export')['session']['war_state']==world
        save('manual-holds-t2.json',dict(command_state=changed,world_unchanged=True,
            scope='Six explicit operator holds after the bounded artillery trial; Native units continue to choose based on real remaining stocks.'))
        print('Queued six explicit holds; original two unit Agents remain enabled',sid);return
    if args.action=='combat-orders':
        assert session['turn_count']==1 and not call(base+'/progress')['active']
        case=json.loads((folder/'case.json').read_text());ids=case['ids']
        view=call(base+'/commands');agents=view['unit_agents']
        assert len(agents)==2
        orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=20)
                for u in view['units'] if u['id'] not in agents]
        for order in orders:
            target=({'ww2.cn.army30':'ww2.jp.shinohara_detachment',
                     'ww2.jp.shinohara_detachment':'ww2.cn.army71'})
            for identity,target_id in target.items():
                if order['unit_id']==ids[identity]:
                    order.update(action='bombard',duration='next',target_id=ids[target_id]);order.pop('end_turn')
        intent=('武汉北线双方向QA继续，数字和阵位未作史实标定，人工队列优先。'
            '两个单位Agent各自读取get_campaign_objectives与get_afsim_observation并用submit_unit_order提交。'
            '不得跨到另一方向或编造兵力。红方第38师与蓝方第10师团都已具备抽象火炮资源，'
            '先按本单位当前回执核实有效火炮、炮弹、弹药与炮兵射程；如果对方在炮兵射程内且有资源，'
            '请针对对方提交bombard，不要把800米自卫直射射程误用为全部火炮射程；'
            '资源不足则说明实际约束，可hold休整或向本方向目标move，不能虚构炮弹。'
            '仅公开可观测依据，不输出私有思考，不自动补粮，不预设历史伤亡。')
        changed=call(base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
            control_team='red',director=True,no_fire=False,intent=intent,unit_agents=agents,orders=orders),'PUT')
        assert changed['unit_agents']==agents and call(base+'/export')['session']['war_state']==world
        save('combat-orders-t1.json',dict(command_state=changed,world_unchanged=True,
            scope='Explicit operator artillery orders and shared observable Agent intent, not forced effects or historical calibration.'))
        print('Queued two-axis artillery/control trial; no physical advance',sid);return
    if args.action=='configure':
        if (folder/'case.json').exists():raise ValueError('Already configured; inspect the existing case')
        assert session['turn_count']==0
        units={u['name']:u for team in ('red','blue')for u in world[team+'_units']}
        assert len(world['red_units'])==6 and len(world['blue_units'])==2
        view=call(base+'/commands');ids={units[u['name']]['historical_unit_id']:u['id']for u in view['units']}
        agents=[ids['ww2.cn.division38'],ids['ww2.jp.division10']]
        mountain=next(n['condition']['region']['center']for n in world['mission']['definition']['campaign_plan']['nodes']if n['id']=='red_mountain')
        orders=[dict(unit_id=u['id'],action='hold',duration='until_turn',end_turn=20)for u in view['units']if u['id']not in agents]
        for order in orders:
            if order['unit_id']==ids['ww2.jp.shinohara_detachment']:
                order.update(action='move',duration='until_arrived',destination=mountain);order.pop('end_turn')
        intent=('武汉北线双方向软件验证，数字和阵位明确为估计。人工队列优先且不得修改。'
            '每个独立单位Agent先调用get_campaign_objectives核对自己的目标，再get_afsim_observation按本单位读取当前态势和目标，'
            '用submit_unit_order实际提交一个命令，说明只讲可观测依据，不输出私有思考。'
            '红方第38师保持潢川防线，敌军在有效射程内才fire，否则hold；'
            '蓝方第10师团主动沿本方向接近红38师，远处move且duration=until_arrived，进入有效射程后fire，不能因有人工红方命令就蓝方全体待命。'
            '不跨到另一方向，不瞬移、不自动补粮、不虚构损失或下级。')
        changed=call(base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
            control_team='red',director=True,no_fire=False,intent=intent,unit_agents=agents,orders=orders),'PUT')
        assert changed['unit_agents']==agents and call(base+'/export')['session']['war_state']==world
        save('initial-export.json',session)
        save('case.json',dict(api=api,ui=source['ui'],session_id=sid,engine=args.engine,actor_count=8,team_counts=dict(red=6,blue=2),
            goal_count=5,native_decision_count=2,step_seconds=3600,command_unit=ids['ww2.cn.army71'],ids=ids))
        print('Configured both teams with two Native agents and six explicit manual orders',sid);return
    from backend import session_store
    from gentactix import missions
    session_store.validate(session)
    original=json.loads((folder/'initial-export.json').read_text())
    bindings={identity:row['session_id']for identity,row in session['command_state']['agent_sessions'].items()}
    first_frame=folder/'turn1/after.json'
    if first_frame.exists():
        initial_bindings=json.loads(first_frame.read_text())['command_state']['agent_sessions']
        assert bindings=={identity:row['session_id']for identity,row in initial_bindings.items()}
    identities={u['historical_unit_id']for team in ('red','blue')for u in original['war_state'][team+'_units']}
    rows=[]
    for trace in session['trajectory']:
        if trace['turn']==0:continue
        old,new=trace['before'],trace['after'];missions.validate(new)
        for decision in trace['decisions']:
            if decision.get('source')=='native_unit_agent':
                assert decision['proposal']['source']=='dsh_native_unit_order_tool'
                assert decision['proposal']['session_id']==bindings[decision['unit_id']]
        assert all(run['finish_reason']=='completed'for run in trace['runs'])
        assert new['historical_initial']==original['war_state']['historical_initial']
        assert new['simulation_clock']['elapsed_seconds']-old['simulation_clock']['elapsed_seconds']==3600
        actors=[u for team in ('red','blue')for u in new[team+'_units']]
        assert {u['historical_unit_id']for u in actors}==identities
        assert len(new['campaign_plan']['nodes'])==5
        previous={u['name']:u for team in ('red','blue')for u in old[team+'_units']}
        ledger={r['unit']:r for r in new['mission']['ledger']}
        for u in actors:
            p=u['personnel'];assert p['current']+p['casualties']+p['noncombat_losses']==p['committed']
            for equipment in u['equipment']:
                assert equipment['operational']+equipment['damaged']+equipment['destroyed']==equipment['committed']
            before=previous[u['name']];r=ledger[u['name']]
            for key in ('food','ammo'):
                expected=before['logistics'][key]+r[key+'_received']-r[key+'_spent']
                assert math.isclose(u['logistics'][key],expected,abs_tol=1e-8,rel_tol=0)
        if args.engine=='afsim':assert new.get('afsim') and not new.get('dsh_execution')
        else:assert new.get('dsh_execution') and not new.get('afsim')
        rows.append(dict(turn=trace['turn'],people={team:sum(u['personnel']['current']for u in new[team+'_units'])for team in ('red','blue')},
            combat_losses={team:sum(u['personnel']['casualties']for u in new[team+'_units'])for team in ('red','blue')},
            engagement_count=len(new.get('engagements',[])),status=new['mission']['status'],winner=new['mission'].get('winner')))
    assert not call(base+'/progress')['active']
    save('audit-t'+str(session['turn_count'])+'.json',dict(passed=True,rows=rows,session_id=sid,
        original_unit_sdk_bindings=bindings,
        scope='Current source identities, all-team ledgers, exact clocks and program goals; not historical calibration or complete Wuhan campaign.'))
    print('PASS all-team source and ledger audit',sid,'turn',session['turn_count'])


if __name__=='__main__':main()
