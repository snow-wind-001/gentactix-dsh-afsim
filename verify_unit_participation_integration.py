"""Checked DSH estimates, commands, tasks and cold state; no live model calls."""
import copy
import json
import unittest

from gentactix import commands, missions, unit_participation as participation
from tools.qa.campaign_plan_fixture import session as fixture
from verify_force_task_execution import step, execution, register


def queued(s,unit,point,kind):
    rows=[{k:v for k,v in o.items() if k in commands.DRAFT_FIELDS}
          for o in commands.state(s)['orders'] if o['unit_id']!=unit]
    s['command_state']=commands.replace_queue(s,rows+[dict(unit_id=unit,action='move',
        duration='until_arrived',destination=point,participation=kind)],
        control_team='red',director=True,no_fire=False,intent='QA显式参与机动')


def setup():
    s=fixture();s['execution_backend']='narrative'
    s['command_state']=commands.replace_queue(s,[],control_team='red',director=True,no_fire=False,intent='QA')
    identity=next(i for i,(_,u) in commands.resolve_units(s).items() if u['historical_unit_id']=='ww2.cn.division159')
    return s,identity


class UnitParticipationIntegrationTests(unittest.TestCase):
    def test_arrival_precedes_goal_scoring_and_reentry_keeps_the_same_entity_and_accounts(self):
        s,identity=setup();unit=commands.resolve_units(s)[identity][1];origin=commands.known_position(unit)
        target=copy.deepcopy(s['war_state']['mission']['definition']['campaign_plan']['nodes'][0]['condition']['region']['center'])
        queued(s,identity,target,'withdraw');saved=copy.deepcopy(s)
        a,_=step(s);self.assertEqual(s,saved)
        leaf=commands.resolve_units(a)[identity][1];row=participation.unit_view(a['war_state'],leaf)
        self.assertEqual(row['status'],'reserve');self.assertTrue(row['targetable'])
        self.assertEqual(a['war_state']['campaign_plan']['nodes']['north']['status'],'blocked')
        self.assertEqual(leaf['personnel'],unit['personnel']);self.assertEqual(leaf['equipment'],unit['equipment'])
        self.assertEqual(leaf['logistics']['food'],unit['logistics']['food']-4)
        for _ in range(3):a,_=step(a)
        queued(a,identity,origin,'reenter');b,_=step(a)
        leaf=commands.resolve_units(b)[identity][1];back=participation.unit_view(b['war_state'],leaf)
        self.assertEqual(back['status'],'deployed');self.assertEqual(back['entity_id'],row['entity_id'])
        self.assertEqual(leaf['logistics']['food'],unit['logistics']['food']-14)
        self.assertEqual(leaf['personnel'],unit['personnel']);self.assertTrue(missions.validate(b['war_state']))

    def test_rear_capabilities_and_raw_orders_forbid_attack_but_do_not_hide_enemy_target(self):
        s,identity=setup();unit=commands.resolve_units(s)[identity][1]
        queued(s,identity,dict(lat=unit['lat']+.001,lng=unit['lng']),'withdraw');a,_=step(s)
        row=next(r for r in commands.view(a)['units'] if r['id']==identity)
        self.assertNotIn('fire',row['capabilities']['actions']);self.assertTrue(row['available'])
        self.assertEqual(row['capabilities']['participation']['choices'],['reenter'])
        with self.assertRaises(ValueError):missions.validate_orders(a['war_state'],[dict(unit=unit['name'],action='fire',target=a['war_state']['blue_units'][0]['name'])],'30分钟')
        self.assertTrue(participation.unit_view(a['war_state'],commands.resolve_units(a)[identity][1])['targetable'])

    def test_temporarily_withdrawn_task_member_resumes_but_ordinary_manual_override_does_not(self):
        from gentactix import force_organization as forces
        s,identity=setup();s['force_organization']=forces.detach(s,[identity],'连续任务','软件QA')
        group=s['force_organization']['groups'][-1]['id']
        task=register(s,group,None,execution('保留原任务',finish=dict(kind='turn',end_turn=100,minimum_executions=20)),kind='defend')
        a,_=step(s);old=copy.deepcopy(a['command_state']['task_plans'][task]['execution']['definition'])
        unit=commands.resolve_units(a)[identity][1];origin=commands.known_position(unit)
        queued(a,identity,dict(lat=unit['lat']+.001,lng=unit['lng']),'withdraw');b,_=step(a)
        waiting=next((r for r in commands.prepare(b)['manual'] if r['command']['unit_id']==identity),None)
        self.assertIsNotNone(waiting,'Paused existing task must deliver an explicit waiting hold, not reopen model planning')
        self.assertEqual(waiting['order']['action'],'hold');self.assertFalse(waiting['command']['task_context']['activated'])
        c,_=step(b)
        self.assertEqual(c['command_state']['task_plans'][task]['execution']['member_states'][identity]['status'],'blocked')
        queued(c,identity,origin,'reenter');d,_=step(c);e,prepared=step(d)
        runtime=e['command_state']['task_plans'][task]['execution']
        self.assertEqual(runtime['definition'],old);self.assertEqual(runtime['member_states'][identity]['executions'],2)
        self.assertTrue(any(r['command']['unit_id']==identity for r in prepared['manual']))

    def test_unrelated_group_order_does_not_drop_an_existing_participation_request(self):
        from gentactix import force_organization as forces
        s,identity=setup();unit=commands.resolve_units(s)[identity][1]
        queued(s,identity,dict(lat=unit['lat']+.001,lng=unit['lng']),'withdraw')
        other=next(i for i,(e,_) in commands.resolve_units(s).items() if i!=identity and e['team']=='red')
        s['force_organization']=forces.detach(s,[other],'其他任务群','软件QA')
        s['command_state']=forces.queue(s,s['force_organization']['groups'][-1]['id'],dict(action='hold',duration='next'))
        request=next(o for o in commands.prepare(s)['manual'] if o['command']['unit_id']==identity)
        self.assertEqual(request['order']['participation']['kind'],'withdraw')

    def test_observations_and_report_basis_expose_participation_without_a_second_stock_ledger(self):
        from backend import afsim_state,agent_tools
        from gentactix import turn_settlement,reporting
        s,identity=setup();u=commands.resolve_units(s)[identity][1]
        queued(s,identity,dict(lat=u['lat']+.001,lng=u['lng']),'withdraw');a,_=step(s)
        page=afsim_state.observation(a,dict(ids=[identity],detail=True))
        self.assertEqual(page['units'][0]['participation']['status'],'reserve')
        plain=agent_tools.exec_get_observation(a['war_state'],{'names':[u['name']]})
        self.assertEqual(plain['units'][0]['participation']['status'],'reserve')
        basis=turn_settlement.build(a['war_state'],s['war_state'])
        row=next(r for r in basis['units'] if r['name']==u['name'])
        self.assertEqual(row['participation']['after'],'reserve')
        self.assertIn('后方待命',reporting.facts(a['war_state'],s['war_state']))
        self.assertNotIn('logistics',a['war_state']['unit_participation']['actors'][participation.unit_view(a['war_state'],commands.resolve_units(a)[identity][1])['entity_id']])

    def test_cold_world_validation_and_forged_participation_are_checked_by_the_normal_validator(self):
        s,identity=setup();u=commands.resolve_units(s)[identity][1]
        queued(s,identity,dict(lat=u['lat']+.001,lng=u['lng']),'withdraw');a,_=step(s)
        cold=json.loads(json.dumps(a));self.assertTrue(missions.validate(cold['war_state']))
        self.assertEqual(step(a)[0]['war_state'],step(cold)[0]['war_state'])
        key=participation.unit_view(cold['war_state'],commands.resolve_units(cold)[identity][1])['entity_id']
        cold['war_state']['unit_participation']['actors'][key]['status']='deployed'
        with self.assertRaises(ValueError):missions.validate(cold['war_state'])

    def test_backend_cannot_write_participation_in_a_dsh_candidate(self):
        from backend import dsh_simulation
        from verify_campaign_plan_backends import proposal
        s,_=setup();value=proposal(s['war_state']);value['unit_participation']={'version':participation.VERSION}
        saved=copy.deepcopy(s['war_state'])
        with self.assertRaisesRegex(ValueError,'顶层字段'):dsh_simulation.apply(s['war_state'],value,'30分钟')
        self.assertEqual(s['war_state'],saved)


if __name__=='__main__':unittest.main()
