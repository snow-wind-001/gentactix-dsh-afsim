"""Interleaved same-world phases and real participation/resource contracts."""
import copy
import json
import unittest

from backend import dsh_simulation
from gentactix import commands, historical_operations, missions, unit_participation as up
from tools.qa.boundary_lifecycle_fixture import inputs, member, seed_damage, partial_exit
from verify_campaign_plan_backends import proposal
from verify_unit_participation import order


class BoundaryLifecycleTests(unittest.TestCase):
    def world(self):
        return seed_damage(historical_operations.initial(*inputs()))

    def step(self, before, point=None, kind=None, request_id='a'*32):
        value = proposal(before)
        if point:
            name = member(before)['name']
            target = before['mission']['definition']['operation_boundary']['routes'][0]['outside' if kind == 'withdraw' else 'inside']
            raw = order(name, target, kind, request_id)
            raw.update(point)
            value['orders'] = [raw if r['unit'] == name else r for r in value['orders']]
            row = next(r for r in value['unit_updates'] if r['unit'] == name)
            row.update(point); row['logistics']['food'] -= 2
            next(r for r in value['resource_ledger']['units'] if r['unit'] == name)['food_spent'] += 2
        saved = copy.deepcopy(before)
        after = dsh_simulation.apply(before, value, '15分钟')
        self.assertEqual(before, saved)
        self.assertTrue(missions.validate(copy.deepcopy(after)))
        return after

    def test_first_stage_transition_preserves_partial_exit_and_all_entities(self):
        w = self.world(); u = copy.deepcopy(member(w))
        a = self.step(w, partial_exit(w), 'withdraw')
        self.assertEqual(a['campaign_lifecycle']['phase_index'], 1)
        row = up.unit_view(a, member(a), 'red')
        self.assertEqual(row['status'], 'withdrawing')
        self.assertEqual(row['pending']['id'], 'a'*32)
        self.assertEqual(row['pending']['issued_turn'], 0)
        self.assertEqual(member(a)['personnel'], u['personnel'])
        self.assertEqual(member(a)['equipment'], u['equipment'])
        self.assertEqual(set(a['unit_participation']['actors']), set(w['unit_participation']['actors']))
        self.assertEqual(a['mission']['definition'], w['mission']['definition'])

    def test_cancel_during_stage_two_clears_only_request(self):
        w = self.world(); a = self.step(w, partial_exit(w), 'withdraw')
        b = self.step(a)
        self.assertEqual(up.unit_view(b, member(b))['status'], 'deployed')
        self.assertIsNone(up.unit_view(b, member(b))['pending'])
        for k in ('lat','lng','personnel','equipment'):
            self.assertEqual(member(b)[k], member(a)[k])
        self.assertEqual(member(b)['formation']['fatigue'], 40)
        self.assertEqual(member(b)['formation']['intel_age_min'], member(a)['formation']['intel_age_min']+15)
        self.assertEqual(member(b)['logistics']['food'], member(a)['logistics']['food']-2)
        self.assertEqual(b['campaign_lifecycle']['phase_index'], 1)

    def test_phase_three_does_not_redeploy_an_outside_unit_or_reset_resources(self):
        w = self.world(); route = w['mission']['definition']['operation_boundary']['routes'][0]
        a = self.step(w, partial_exit(w), 'withdraw')
        b = self.step(a, route['outside'], 'withdraw')
        c = self.step(b)
        self.assertEqual(c['campaign_lifecycle']['phase_index'], 2)
        self.assertEqual(up.unit_view(c, member(c))['status'], 'offmap')
        self.assertEqual(c['campaign_plan']['nodes']['north']['status'], 'waiting_phase')
        d = self.step(c)
        self.assertEqual(d['campaign_plan']['nodes']['north']['status'], 'blocked')
        self.assertEqual(member(d)['logistics'], dict(food=68, ammo=80))
        self.assertEqual(member(d)['personnel'], member(w)['personnel'])
        self.assertEqual(member(d)['equipment'], member(w)['equipment'])
        self.assertEqual(d['mission']['status'], 'active')

    def test_cold_roundtrip_keeps_pending_identity_and_next_outcome(self):
        w = self.world(); a = self.step(w, partial_exit(w), 'withdraw')
        restored = json.loads(json.dumps(a)); self.assertTrue(missions.validate(restored))
        point = a['mission']['definition']['operation_boundary']['routes'][0]['outside']
        self.assertEqual(self.step(restored, point, 'withdraw'), self.step(a, point, 'withdraw'))

    def test_reentry_remains_pending_across_stage_sampling_then_arrives(self):
        w = self.world(); route = w['mission']['definition']['operation_boundary']['routes'][0]
        a = self.step(w, partial_exit(w), 'withdraw')
        b = self.step(a, route['outside'], 'withdraw')
        c = self.step(b, partial_exit(w), 'reenter', 'b'*32)
        self.assertEqual(c['campaign_lifecycle']['phase_index'], 2)
        self.assertEqual(up.unit_view(c, member(c))['status'], 'returning')
        self.assertFalse(up.unit_view(c, member(c))['controls_objectives'])
        restored = json.loads(json.dumps(c))
        d = self.step(restored, route['inside'], 'reenter', 'b'*32)
        row = up.unit_view(d, member(d))
        self.assertEqual(row['status'], 'deployed'); self.assertIsNone(row['pending'])
        self.assertEqual(member(d)['personnel'], member(w)['personnel'])
        self.assertEqual(member(d)['equipment'], member(w)['equipment'])

    def test_offmap_actor_cannot_fire_after_phase_changes(self):
        w = self.world(); route = w['mission']['definition']['operation_boundary']['routes'][0]
        a = self.step(w, partial_exit(w), 'withdraw')
        b = self.step(a, route['outside'], 'withdraw'); c = self.step(b)
        saved = copy.deepcopy(c)
        with self.assertRaisesRegex(ValueError, '返回|重返|场外'):
            missions.validate_orders(c, [dict(unit=member(c)['name'], action='fire', target=c['blue_units'][0]['name'])], '15分钟')
        self.assertEqual(c, saved)

    def test_returning_inside_still_reports_its_actual_status_when_fire_is_blocked(self):
        w = self.world(); route = w['mission']['definition']['operation_boundary']['routes'][0]
        a = self.step(w, partial_exit(w), 'withdraw')
        b = self.step(a, route['outside'], 'withdraw')
        c = self.step(b, partial_exit(w), 'reenter', 'b'*32)
        self.assertEqual(up.unit_view(c, member(c))['operation_zone'], 'inside')
        with self.assertRaisesRegex(ValueError, '重新投入途中'):
            up.check_order(c, dict(unit=member(c)['name'], action='fire', target=c['blue_units'][0]['name']))

    def test_real_command_cancel_preserves_original_task_and_explicit_blue_control(self):
        from gentactix import force_organization as forces
        from verify_force_task_execution import execution, register
        s=dict(id='boundary-life-command-qa',war_state=self.world(),time_step='15分钟',turn_count=0,
               role_epoch=0,product_mode='historical',simulation_mode='open',execution_backend='narrative')
        pairs=commands.resolve_units(s);uid=next(i for i,(_,u) in pairs.items() if u['name']==member(s['war_state'])['name'])
        s['force_organization']=forces.detach(s,[uid],'QA原任务群','仅测试指挥保留')
        gid=s['force_organization']['groups'][-1]['id']
        task=register(s,gid,None,execution('QA持续任务',finish=dict(kind='turn',end_turn=100,minimum_executions=20)),kind='defend')
        route=s['war_state']['mission']['definition']['operation_boundary']['routes'][0]
        others=[dict(unit_id=i,action='hold',duration='until_turn',end_turn=100) for i in pairs if i!=uid]
        s['command_state']=commands.replace_queue(s,[*others,dict(unit_id=uid,action='move',duration='until_arrived',
            participation='withdraw',destination=route['outside'])],control_team='red',director=True,no_fire=False,intent='QA明确控制双方')
        def advance(session):
            prior=copy.deepcopy(session);prepared=commands.prepare(session)
            self.assertEqual({r['order']['unit'] for r in prepared['manual']},{u['name'] for _,u in missions.units(session['war_state'])})
            value=proposal(session['war_state']);orders={r['unit']:r for r in value['orders']}
            for item in prepared['manual']:
                raw=item['order'];orders[raw['unit']]=raw
                if raw['action']=='move':
                    row=next(r for r in value['unit_updates'] if r['unit']==raw['unit'])
                    row.update({k:raw[k] for k in ('lat','lng')});row['logistics']['food']-=2
                    next(r for r in value['resource_ledger']['units'] if r['unit']==raw['unit'])['food_spent']+=2
            value['orders']=list(orders.values());w=dsh_simulation.apply(session['war_state'],value,'15分钟')
            cs,_=commands.finish(session,prepared,w,executed=value['orders'])
            self.assertEqual(session,prior)
            return {**copy.deepcopy(session), 'war_state':w,'command_state':cs,'turn_count':session['turn_count']+1}
        s=advance(s);self.assertEqual(s['war_state']['campaign_lifecycle']['phase_index'],1)
        command=next(o for o in s['command_state']['orders'] if o['unit_id']==uid)
        s['command_state']=commands.cancel(s,command['id'])
        s['command_state']=commands.replace_queue(s,others,control_team='red',director=True,no_fire=False,intent='QA撤销退出并保持蓝方待命')
        s=advance(s)
        state=s['command_state']['task_plans'][task]['execution']['member_states'][uid]
        self.assertNotEqual(state['status'],'manual_override');self.assertEqual(state['executions'],0)
        self.assertIsNone(up.unit_view(s['war_state'],member(s['war_state']))['pending'])
        s=advance(s)
        self.assertEqual(s['command_state']['task_plans'][task]['execution']['member_states'][uid]['executions'],1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
