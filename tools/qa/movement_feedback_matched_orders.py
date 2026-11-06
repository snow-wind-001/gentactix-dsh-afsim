"""Normal API: same initial22, tasks and DSH-accepted actions for native comparison."""
import argparse
import json

from . import movement_feedback_live as workflow


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=workflow.ROOT;api=workflow.workflow.api
    cases=json.loads((root/'cases.json').read_text());sid=cases['afsim'];base='/sessions/'+sid
    if (root/'matched-command-setup.json').exists():raise ValueError('Preserve prior command intervention')
    dsh=json.loads((root/'dsh-t1-review/authoritative-after.json').read_text())
    dsh_before=json.loads((root/'dsh-t1-review/authoritative-before.json').read_text())
    af=api.call('GET',base+'/export')['session'];assert af['turn_count']==0
    for key in ('red_units','blue_units','supply_nodes','campaign','campaign_plan','campaign_lifecycle','simulation_clock'):
        assert af['war_state'][key]==dsh_before['war_state'][key],key
    view=api.call('GET',base+'/commands')
    dsh_names={r['id']:r['name'] for r in dsh['command_state']['registry']}
    af_names={r['name']:r['id'] for r in view['units']}
    decisions={r['unit_id']:r for r in dsh['command_state']['receipts'] if r['turn']==1}
    orders=[]
    for identity in dsh_before['command_state']['unit_agents']:
        raw=decisions[identity]['planned'];order=dict(unit_id=af_names[dsh_names[identity]],action=raw['action'],duration='next')
        if raw['action']=='move':order['destination']={k:raw[k] for k in ('lat','lng')}
        if raw.get('target'):order['target_id']=af_names[raw['target']]
        if raw.get('air_pool'):order['air_pool']=raw['air_pool']
        orders.append(order)
    api.call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        orders=orders,unit_agents=[],control_team='red',director=True,no_fire=False,
        intent='物理对照：同初态、同20个任务、另两单位采用DSH已接收动作，经普通命令接口提交；不再调用模型重复规划。'))
    result=dict(passed=True,afsim=sid,dsh=cases['narrative'],manual_orders=orders,all22_initial_accounts_equal=True,
        scope='Matching numerical initial state/tasks/actions; no independent native-agent latency or historical efficacy claim')
    (root/'matched-command-setup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('Matched two accepted actions; retained20 task actors and exact numerical initial state')


if __name__=='__main__':main()
