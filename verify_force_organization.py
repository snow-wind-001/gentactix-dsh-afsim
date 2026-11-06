"""Command hierarchy and runtime task groups must preserve executable leaves."""
import copy
import unittest

from gentactix import commands,historical_operations
from tools.qa.historical_operational_fixture import inputs


def session():
    s,p=inputs();return {'id':'a'*12,'turn_count':0,'role_epoch':0,'product_mode':'historical',
        'simulation_mode':'open','time_step':'30分钟','war_state':historical_operations.initial(s,p)}


class ForceOrganizationTests(unittest.TestCase):
    def test_hierarchy_keeps_reference_and_command_nodes_without_duplicate_strength(self):
        from gentactix import force_organization as f
        s=session();view=f.view(s);leaves=list(commands.resolve_units(s))
        self.assertEqual(set(view['execution_ids']),set(leaves))
        self.assertEqual(view['totals']['red']['current'],6000)
        self.assertEqual(view['totals']['blue']['current'],4800)
        self.assertTrue(any(n['role']=='command' for n in view['nodes']))
        self.assertTrue(any(not n['execution_ids'] for n in view['nodes']))

    def test_split_merge_change_only_task_membership_not_personnel_or_positions(self):
        from gentactix import force_organization as f
        s=session();before=copy.deepcopy(s);ids=list(commands.resolve_units(s))
        a=f.detach(s,ids[1:],'蓝方支援群','同阵营历史部队临时配属，原建制保留')
        s['force_organization']=a
        group=a['groups'][0]['id']
        s['force_organization']=f.detach(s,[ids[1]],'阻击分队','从任务群分出原有下级，未新建士兵')
        self.assertEqual(sorted(len(g['members']) for g in s['force_organization']['groups']),[1,1])
        s['force_organization']=f.merge(s,[g['id'] for g in s['force_organization']['groups']],
            '合成阻援群','恢复统一指挥，尚未发生物理集结')
        self.assertEqual(set(f.member_ids(s,s['force_organization']['groups'][0]['id'])),set(ids[1:]))
        self.assertEqual(s['war_state'],before['war_state'])
        self.assertEqual(len(s['force_organization']['events']),3)
        self.assertEqual(s['force_organization']['events'][-1]['kind'],'merge')
        f.validate(s)

    def test_cross_team_unknown_and_duplicate_members_are_rejected(self):
        from gentactix import force_organization as f
        s=session();ids=list(commands.resolve_units(s));saved=copy.deepcopy(s)
        for members in ([ids[0],ids[1]],['missing'],[ids[0],ids[0]]):
            with self.subTest(members=members),self.assertRaises(ValueError):f.detach(s,members,'非法编组','QA')
        self.assertEqual(s,saved)

    def test_group_order_uses_existing_queue_and_scope_guards(self):
        from gentactix import force_organization as f
        s=session();ids=list(commands.resolve_units(s));s['force_organization']=f.detach(s,ids[1:],'蓝方群','QA明确假设')
        group=s['force_organization']['groups'][0]['id']
        with self.assertRaises(ValueError):f.queue(s,group,{'action':'hold','duration':'next'})
        s['command_state']=commands.replace_queue(s,[],control_team='blue',director=False,no_fire=False,intent='')
        queued=f.queue(s,group,{'action':'hold','duration':'next'})
        self.assertEqual({o['unit_id'] for o in queued['orders']},set(ids[1:]))
        self.assertNotIn('force_organization',s['war_state'])

    def test_mutated_or_duplicate_task_membership_cannot_restore(self):
        from gentactix import force_organization as f
        s=session();ids=list(commands.resolve_units(s));s['force_organization']=f.detach(s,[ids[0]],'红方群','QA')
        s['force_organization']['groups'].append(copy.deepcopy(s['force_organization']['groups'][0]))
        with self.assertRaises(ValueError):f.validate(s)

    def test_long_group_march_respects_authoritative_distance_metric(self):
        from gentactix import force_organization as f
        s=session();ids=[i for i,(e,u) in commands.resolve_units(s).items() if e['team']=='red']
        s['force_organization']=f.detach(s,ids,'远程行军群','QA目标远于本轮机动')
        g=s['force_organization']['groups'][0]['id']
        cs=f.queue(s,g,dict(action='move',duration='until_arrived',destination={'lat':34.57,'lng':117.76}))
        self.assertEqual(len(cs['orders']),len(ids))

    def test_step_projection_never_exceeds_local_distance_budget(self):
        for lat in (0,30.59,60):
            for delta in ((.1,0),(0,.1),(.1,.1)):
                start={'lat':lat,'lng':114.31};end={'lat':lat+delta[0],'lng':114.31+delta[1]}
                p=commands.towards(start,end,1.5)
                self.assertLessEqual(commands.distance(start,p),1.500001)

    def test_native_hierarchy_pages_are_bounded_and_read_only(self):
        from gentactix import force_organization as f
        from backend import agent_tools,harness_engine as h
        s=session();frozen=copy.deepcopy(s);items=[];args={'limit':2}
        while args:
            r=agent_tools.execute_tool_call(s,s['war_state'],{'tool':'get_force_organization','args':args})
            self.assertTrue(r['ok']);self.assertLessEqual(len(r['items']),2)
            items.extend(r['items']);args=r['next_args']
        self.assertEqual(len(items),len(f.view(s)['nodes']))
        self.assertEqual(s,frozen)
        self.assertIn('get_force_organization',h.role_policy('engine',tools=True,external=True)['allowed_tools'])

    def test_incapable_subordinate_stays_in_group_but_does_not_block_survivors(self):
        from gentactix import force_organization as f
        s=session();ids=list(commands.resolve_units(s));s['force_organization']=f.detach(s,ids[1:],'蓝方群','QA')
        group=s['force_organization']['groups'][0]['id']
        s['command_state']=commands.replace_queue(s,[],control_team='blue',director=False,no_fire=False,intent='')
        lost=s['war_state']['blue_units'][0]
        lost['personnel']['casualties']=lost['personnel']['current'];lost['personnel']['current']=0;lost['hp']=0
        cs=f.queue(s,group,dict(action='hold',duration='next'))
        self.assertEqual([o['unit_id'] for o in cs['orders']],[ids[2]])
        v=f.view(s);self.assertEqual(v['groups'][0]['totals']['units'],2)
        self.assertEqual(v['inactive_ids'],[ids[1]])


if __name__=='__main__':unittest.main()
