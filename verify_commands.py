"""Order-domain regressions. Synthetic mission fixtures, no SDK or model calls."""
import copy
import unittest

from gentactix import commands as c, missions as m


def session():
    return {'id': '123456abcdef', 'role_epoch': 1, 'turn_count': 0, 'time_step': '30分钟',
            'simulation_mode': 'open', 'war_state': m.initial('AJ15-local-v1')}


def save(s, orders, **options):
    return c.replace_queue(s, orders, **{'control_team': 'red', 'director': False,
                                       'no_fire': False, 'intent': '', **options})


class OrderDomainTests(unittest.TestCase):
    def test_receipt_budget_is_frozen_from_before_world(self):
        from gentactix import sustainment
        s=session();s.update(war_state=m.initial('CA-AJ18-v1'),execution_backend='afsim')
        s['war_state']['mission']['turn']=1;s['turn_count']=1
        prepared=c.prepare(s);after=copy.deepcopy(s['war_state'])
        after['mission']['turn']=2
        expected=sustainment.decision_context(s['war_state'],s['war_state']['red_units'][0])
        result,_=c.finish(s,prepared,after,instruction='本轮补给')
        receipt=result['receipts'][-len(c.view(s)['units'])]
        self.assertEqual({k:receipt['decision_context'][k] for k in expected},expected)
        self.assertEqual(receipt['operator_instruction'],'本轮补给')
        self.assertEqual(receipt['decision_context']['team_hold_food_budget'],
                         sustainment.assess(s['war_state'])['teams']['red']['minimum_hold_food'])
        self.assertNotEqual(expected['remaining_turns'],sustainment.decision_context(after,after['red_units'][0])['remaining_turns'])

    def test_over_budget_error_identifies_actor_distance_and_correction(self):
        s=session();actor=next(u for u in c.view(s)['units'] if u['team']=='red')
        destination={'lat':actor['position']['lat']+.05,'lng':actor['position']['lng']}
        order={'unit_id':actor['id'],'action':'move','duration':'next','destination':destination}
        original=copy.deepcopy(s)
        with self.assertRaises(ValueError) as error:save(s,[order])
        message=str(error.exception)
        for text in (actor['name'],actor['id'],'km','until_arrived','预算'):
            self.assertIn(text,message)
        self.assertEqual(s,original)
    def test_native_nondelivery_never_completes_model_or_one_turn_human_orders(self):
        for source in ('model_batch','native_unit_agent','human'):
            for action in ('recon','hold'):
                with self.subTest(source=source,action=action):
                    s=session();s.update(war_state=m.initial('CA-AJ18-v1'),execution_backend='afsim')
                    actor=next(u for u in c.view(s)['units'] if u['team']=='red')
                    if source=='human':
                        s['command_state']=save(s,[{'unit_id':actor['id'],'action':action,'duration':'next'}])
                    prepared=c.prepare(s);after=copy.deepcopy(s['war_state'])
                    unit=next(u for u in after['red_units'] if u['name']==actor['name'])
                    unit['formation']['last_execution']={'turn':1,'action':'未交付','command_done':0,'blocked':0}
                    state,_=c.finish(s,prepared,after,executed=[{'unit':actor['name'],'action':action}],
                        rationales=[{'team':'red','unit_name':actor['name'],'source':source,'rationale':'QA规划'}])
                    receipt=next(r for r in state['receipts'] if r['unit_id']==actor['id'])
                    self.assertEqual(receipt['status'],'blocked')
                    self.assertIn('未交付',receipt['reason'])
                    self.assertEqual(receipt['source'],source)
                    self.assertFalse(state['orders'])
                    if source=='human':self.assertNotIn('按用户已确认命令执行',receipt['rationale'])

    def test_native_nondelivery_retains_continuous_move_even_if_at_destination(self):
        s=session();s.update(war_state=m.initial('CA-AJ18-v1'),execution_backend='afsim')
        actor=next(u for u in c.view(s)['units'] if u['team']=='red')
        unit=next(u for u in s['war_state']['red_units'] if u['name']==actor['name'])
        destination={'lat':unit['lat'],'lng':unit['lng']+.001}
        s['command_state']=save(s,[{'unit_id':actor['id'],'action':'move','duration':'until_arrived','destination':destination}])
        prepared=c.prepare(s);after=copy.deepcopy(s['war_state'])
        following=next(u for u in after['red_units'] if u['name']==actor['name']);following.update(destination)
        following['formation']['last_execution']={'turn':1,'action':'未交付','command_done':0,'blocked':0}
        state,_=c.finish(s,prepared,after,executed=[prepared['manual'][0]['order']])
        receipt=next(r for r in state['receipts'] if r['unit_id']==actor['id'])
        self.assertEqual(receipt['status'],'blocked')
        self.assertEqual(len(state['orders']),1)
        self.assertEqual(state['orders'][0]['status'],'executing')
        self.assertEqual(state['orders'][0]['destination'],destination)

    def test_bounded_native_nondelivery_retries_but_never_claims_completion(self):
        s=session();s.update(war_state=m.initial('CA-AJ18-v1'),execution_backend='afsim')
        actor=next(u for u in c.view(s)['units'] if u['team']=='red')
        s['command_state']=save(s,[{'unit_id':actor['id'],'action':'hold','duration':'until_turn','end_turn':2}])
        for turn in (1,2):
            prepared=c.prepare(s);self.assertEqual(len(prepared['manual']),1)
            after=copy.deepcopy(s['war_state'])
            unit=next(u for u in after['red_units'] if u['name']==actor['name'])
            unit['formation']['last_execution']={'turn':turn,'action':'未交付','command_done':0,'blocked':0}
            state,_=c.finish(s,prepared,after,executed=[prepared['manual'][0]['order']])
            receipt=next(r for r in state['receipts'] if r['turn']==turn and r['unit_id']==actor['id'])
            self.assertEqual(receipt['status'],'blocked' if turn==1 else 'expired')
            self.assertIn('未交付',receipt['reason'])
            self.assertEqual(len(state['orders']),1 if turn==1 else 0)
            if turn==1:self.assertEqual(state['orders'][0]['status'],'executing')
            s.update(command_state=state,turn_count=turn,war_state=after)

    def test_bounded_preparation_ends_when_unit_is_disabled(self):
        self.s['command_state']=save(self.s,[self.order(duration='until_turn',end_turn=3)])
        prepared=c.prepare(self.s);after=copy.deepcopy(self.s['war_state'])
        unit=next(u for u in after['red_units'] if u['name']==self.red['name']);unit['hp']=0;unit['personnel']['current']=0
        state,_=c.finish(self.s,prepared,after,executed=[prepared['manual'][0]['order']])
        self.assertFalse(state['orders']);self.assertEqual(state['archive'][-1]['status'],'expired')

    def test_bounded_hold_survives_turns_and_returns_control_after_deadline(self):
        self.s['command_state']=save(self.s,[self.order(duration='until_turn',end_turn=2)])
        identity=self.s['command_state']['orders'][0]['id']
        original_world=copy.deepcopy(self.s['war_state'])
        for turn in (1,2):
            prepared=c.prepare(self.s)
            self.assertEqual(len(prepared['manual']),1)
            proposal={'unit':self.red['name'],'action':'resupply'}
            executed=c.merge_proposal(self.s,prepared,[proposal])
            self.assertEqual(next(o['action'] for o in executed if o['unit']==self.red['name']),'hold')
            after=copy.deepcopy(self.s['war_state'])
            state,decisions=c.finish(self.s,prepared,after,executed=executed)
            receipt=next(r for r in state['receipts'] if r['turn']==turn and r['unit_id']==self.red['id'])
            self.assertEqual(receipt['source'],'human')
            self.assertEqual(receipt['command_id'],identity)
            self.assertEqual(receipt['status'],'executing' if turn==1 else 'completed')
            self.assertEqual(len(state['orders']),1 if turn==1 else 0)
            self.s.update(command_state=state,turn_count=turn)
            c.validate_saved(self.s)
        prepared=c.prepare(self.s)
        self.assertFalse(prepared['manual'])
        self.assertEqual(c.merge_proposal(self.s,prepared,[proposal]),[proposal])
        self.assertEqual(self.s['war_state'],original_world)

    def test_bounded_preparation_orders_validate_and_cancel_without_model(self):
        for extra in ({'end_turn':True},{'end_turn':0},{'end_turn':1001},{'end_turn':1.5},
                      {'end_turn':2,'action':'fire'},{'end_turn':2,'action':'move'},{}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                save(self.s,[self.order(duration='until_turn',**extra)])
        with self.assertRaises(ValueError):save(self.s,[self.order(duration='next',end_turn=2)])
        self.s['command_state']=save(self.s,[self.order(duration='until_turn',end_turn=2)])
        old=self.s['command_state']['orders'][0]
        restored=copy.deepcopy(self.s);c.validate_saved(restored)
        self.assertEqual(c.prepare(restored)['manual'][0]['command']['end_turn'],2)
        restored['command_state']=c.cancel(restored,old['id'])
        self.assertFalse(c.prepare(restored)['manual'])
        self.assertEqual(restored['command_state']['archive'][-1]['status'],'cancelled')
        edited=save(self.s,[{**self.order(duration='until_turn',end_turn=3),'id':old['id']}])
        self.assertNotEqual(edited['orders'][0]['id'],old['id'])

    def test_overdue_preparation_does_not_override_a_new_model_decision(self):
        self.s['command_state']=save(self.s,[self.order(duration='until_turn',end_turn=1)])
        self.s['turn_count']=1  # Restored older queue at its exact deadline.
        prepared=c.prepare(self.s)
        self.assertFalse(prepared['manual'])
        actual=[{'unit':self.red['name'],'action':'resupply'}]
        self.assertEqual(c.merge_proposal(self.s,prepared,actual),actual)
        state,_=c.finish(self.s,prepared,copy.deepcopy(self.s['war_state']),executed=actual)
        receipt=next(r for r in state['receipts'] if r['unit_id']==self.red['id'])
        self.assertEqual(receipt['source'],'model_batch');self.assertIsNone(receipt['command_id'])
        self.assertFalse(state['orders'])
        self.assertEqual(state['archive'][-1]['status'],'expired')

    def setUp(self):
        self.s = session()
        self.rows = c.view(self.s)['units']
        self.red = next(u for u in self.rows if u['team'] == 'red')
        self.blue = next(u for u in self.rows if u['team'] == 'blue')

    def order(self, action='hold', **extra):
        return {'unit_id': self.red['id'], 'action': action, **extra}

    def test_partial_native_execution_receipt_explains_resources_and_actual_executor(self):
        for engine in ('afsim','narrative'):
            s=session();s.update(war_state=m.initial('CA-AJ18-v1'),execution_backend=engine)
            unit=s['war_state']['red_units'][0];entry=next(u for u in c.view(s)['units'] if u['name']==unit['name'])
            destination={'lat':unit['lat']+.001,'lng':unit['lng']}
            s['command_state']=save(s,[{'unit_id':entry['id'],'action':'move','destination':destination,'duration':'next'}])
            prepared=c.prepare(s);after=copy.deepcopy(s['war_state']);changed=after['red_units'][0]
            changed['lat']+=.0005;changed['formation']['last_execution']={'turn':1,'action':'move','blocked':10,'command_done':1}
            state,_=c.finish(s,prepared,after,executed=[prepared['manual'][0]['order']])
            receipt=next(r for r in state['receipts'] if r['unit_id']==entry['id'])
            self.assertIn('燃油',receipt['reason'])
            self.assertNotIn('行动未执行',receipt['reason'])
            self.assertNotEqual(receipt['before_position'],receipt['after_position'])
            self.assertEqual('AFSIM' in receipt['reason'],engine=='afsim')

    def test_fuel_limited_continuous_move_finishes_inside_arrival_tolerance(self):
        s=session();s.update(war_state=m.initial('CA-AJ18-v1'),execution_backend='afsim')
        unit=s['war_state']['red_units'][0];entry=next(u for u in c.view(s)['units'] if u['name']==unit['name'])
        destination={'lat':unit['lat']+.001,'lng':unit['lng']}
        s['command_state']=save(s,[{'unit_id':entry['id'],'action':'move','destination':destination,'duration':'until_arrived'}])
        prepared=c.prepare(s);after=copy.deepcopy(s['war_state']);after['red_units'][0]['lat']+=.00095
        after['red_units'][0]['formation']['last_execution']={'turn':1,'action':'move','blocked':10,'command_done':1}
        state,_=c.finish(s,prepared,after,executed=[prepared['manual'][0]['order']])
        receipt=next(r for r in state['receipts'] if r['unit_id']==entry['id'])
        self.assertEqual(receipt['status'],'completed')
        self.assertFalse(state['orders'])
        self.assertIn('燃油',receipt['reason'])

    def test_legacy_ids_are_stable_and_dont_modify_initial_hash(self):
        before = copy.deepcopy(self.s)
        self.assertEqual(c.view(self.s), c.view(copy.deepcopy(self.s)))
        self.assertEqual(self.s, before)
        self.s['command_state'] = c.state(self.s)
        self.assertEqual(c.view(self.s)['units'][0]['id'], self.rows[0]['id'])
        self.s['role_epoch'] += 1
        self.s.pop('command_state')
        self.assertNotEqual(c.view(self.s)['units'][0]['id'], self.rows[0]['id'])

    def test_permission_requires_explicit_director(self):
        order = {'unit_id': self.blue['id'], 'action': 'hold'}
        with self.assertRaisesRegex(ValueError, '权限'):
            save(self.s, [order])
        self.assertEqual(len(save(self.s, [order], director=True)['orders']), 1)

    def test_queue_rejects_duplicate_unknown_and_injected_state(self):
        for orders in ([self.order(), self.order()], [self.order(unit_id='missing')],
                       [self.order(war_state={'hp': 999})]):
            with self.assertRaises(ValueError):
                save(self.s, orders)
        self.assertNotIn('command_state', self.s)

    def test_revision_checks_clock_queue_and_world(self):
        token = c.world_version(self.s)
        c.check_revision(self.s, 0, 0, token)
        for turn, rev, digest in [(1, 0, token), (0, 1, token), (0, 0, 'stale'), (False, 0, token)]:
            with self.assertRaises(c.Conflict):
                c.check_revision(self.s, turn, rev, digest)
        self.s['war_state']['red_units'][0]['logistics']['food'] -= 1
        with self.assertRaises(c.Conflict):
            c.check_revision(self.s, 0, 0, token)

    def test_replay_and_terminal_are_readonly(self):
        self.s['simulation_mode'] = 'replay'
        with self.assertRaisesRegex(ValueError, '回放'):
            save(self.s, [self.order()])
        self.s['simulation_mode'] = 'open'
        self.s['war_state']['mission']['status'] = 'completed'
        with self.assertRaisesRegex(ValueError, '结算'):
            save(self.s, [self.order()])

    def test_target_validation_unknown_is_not_zero(self):
        for destination in ({'lat': None, 'lng': 1}, {'lat': True, 'lng': 1},
                            {'lat': 91, 'lng': 1}, {'lat': 1, 'lng': float('nan')},
                            {'lat': 1, 'lng': 1, 'hp': 100}):
            with self.assertRaises(ValueError):
                save(self.s, [self.order('move', destination=destination)])

    def test_map_boundaries_and_single_turn_budget(self):
        origin = self.red['position']
        distant = c.towards(origin, {'lat': origin['lat']+.05, 'lng': origin['lng']}, 1.6)
        with self.assertRaisesRegex(ValueError, '预算'):
            save(self.s, [self.order('move', destination=distant)])
        with self.assertRaisesRegex(ValueError, '边界'):
            save(self.s, [self.order('move', destination={'lat': origin['lat']+1, 'lng': origin['lng']}, duration='until_arrived')])

    def test_continuous_movement_is_bounded_and_survives_checkpoint(self):
        origin = self.red['position']
        target = c.towards(origin, {'lat': origin['lat']+.05, 'lng': origin['lng']}, 1.5)
        self.s['command_state'] = save(self.s, [self.order('move', destination=target, duration='until_arrived')])
        for turn in range(1, 4):
            prepared = c.prepare(self.s)
            orders = c.merge_proposal(self.s, prepared, [])
            after = m.advance(self.s['war_state'], orders, self.s['time_step'])
            cs, decisions = c.finish(self.s, prepared, after, executed=orders)
            moved = c.distance(c.unit_position(self.s['war_state']['red_units'][0]), c.unit_position(after['red_units'][0]))
            self.assertLessEqual(moved, .601)
            self.assertEqual(len(decisions), 6)
            self.assertEqual(cs['receipts'][-6]['source'], 'human')
            self.assertEqual(cs['receipts'][-6]['run_ids'], [])
            self.s.update(war_state=after, command_state=copy.deepcopy(cs), turn_count=turn)
            c.validate_saved(self.s)
        self.assertFalse(self.s['command_state']['orders'])
        self.assertLessEqual(c.distance(c.unit_position(after['red_units'][0]), target), .01)

    def test_low_food_halves_movement(self):
        self.s['war_state']['red_units'][0]['logistics']['food'] = 3
        self.assertAlmostEqual(c.view(self.s)['units'][0]['capabilities']['move_km'], .3)

    def test_manual_commands_cannot_be_overridden_by_model(self):
        self.s['command_state'] = save(self.s, [self.order()])
        prepared = c.prepare(self.s)
        result = c.merge_proposal(self.s, prepared, [{'unit': self.red['name'], 'action': 'move', 'lat': 0, 'lng': 0}])
        self.assertEqual(result, [{'unit': self.red['name'], 'action': 'hold'}])

    def test_no_fire_is_enforced_for_controlled_side(self):
        self.s['command_state'] = save(self.s, [], no_fire=True)
        prepared = c.prepare(self.s)
        with self.assertRaisesRegex(ValueError, '禁止'):
            c.merge_proposal(self.s, prepared, [{'unit': self.red['name'], 'action': 'fire'}])
        self.assertEqual(c.merge_proposal(self.s, prepared, [{'unit': self.blue['name'], 'action': 'fire'}])[0]['action'], 'fire')

    def test_impossible_orders_fail_before_state_change(self):
        with self.assertRaisesRegex(ValueError, '未实现'):
            save(self.s, [self.order('recon')])
        self.s['war_state']['red_units'][0]['logistics']['ammo'] = 0
        with self.assertRaises(ValueError):
            save(self.s, [self.order('fire', target_id=self.blue['id'])])

    def test_unavailable_and_ambiguous_units_cannot_be_commanded(self):
        self.s['war_state']['red_units'][0]['personnel'].update(current=0, casualties=100)
        with self.assertRaisesRegex(ValueError, '行动能力'):
            save(self.s, [self.order()])
        self.s = session()
        self.s['war_state']['red_units'].append(copy.deepcopy(self.s['war_state']['red_units'][0]))
        with self.assertRaisesRegex(ValueError, '歧义'):
            save(self.s, [self.order()])

    def test_cancel_is_copy_on_write_and_archived(self):
        self.s['command_state'] = save(self.s, [self.order()])
        before = copy.deepcopy(self.s)
        cs = c.cancel(self.s, self.s['command_state']['orders'][0]['id'])
        self.assertFalse(cs['orders'])
        self.assertEqual(cs['archive'][-1]['status'], 'cancelled')
        self.assertEqual(self.s, before)

    def test_terminal_expires_continuous_tasks(self):
        origin = self.red['position']
        target = c.towards(origin, {'lat': origin['lat']+.05, 'lng': origin['lng']}, 2)
        self.s['command_state'] = save(self.s, [self.order('move', destination=target, duration='until_arrived')])
        prepared = c.prepare(self.s)
        after = m.advance(self.s['war_state'], c.merge_proposal(self.s, prepared, []), self.s['time_step'])
        after['mission'].update(status='completed', winner='blue')
        cs, _ = c.finish(self.s, prepared, after)
        self.assertFalse(cs['orders'])
        self.assertEqual(cs['archive'][-1]['status'], 'expired')

    def test_all_twenty_missions_keep_command_ledger_and_checkpoint_continuity(self):
        for spec in m.catalog():
            with self.subTest(mission=spec['id']):
                s = {**session(), 'war_state': m.initial(spec['id'])}
                initial = copy.deepcopy(s['war_state'])
                for turn in range(spec['deadline_turn']):
                    rows = c.view(s)['units']
                    orders = [{'unit_id': u['id'], 'action': 'hold'} for u in rows if u['available']]
                    s['command_state'] = save(s, orders, director=True)
                    prepared = c.prepare(s)
                    executed = c.merge_proposal(s, prepared, [])
                    after = m.advance(s['war_state'], executed, s['time_step'])
                    cs, decisions = c.finish(s, prepared, after, executed=executed)
                    self.assertEqual(len(decisions), 6)
                    self.assertEqual(len(after['mission']['ledger']), 6)
                    self.assertEqual(after['mission']['initial_hash'], initial['mission']['initial_hash'])
                    s.update(command_state=cs, war_state=after, turn_count=turn + 1)
                    c.validate_saved(s)
                    s = copy.deepcopy(s)
                    if after['mission']['status'] == 'completed':
                        self.assertFalse(cs['orders'])
                        break

    def test_cross_side_same_names_are_not_commanded_by_name_adapter(self):
        self.s['war_state']['blue_units'][0]['name'] = self.red['name']
        with self.assertRaisesRegex(ValueError, '歧义'):
            save(self.s, [self.order()])

    def test_retired_or_disabled_command_has_explicit_terminal_receipt(self):
        for retired in (True, False):
            s = copy.deepcopy(self.s)
            s['command_state'] = save(s, [self.order()])
            if retired:
                s['war_state']['red_units'].pop(0)
            else:
                s['war_state']['red_units'][0]['personnel']['current'] = 0
            prepared = c.prepare(s)
            cs, _ = c.finish(s, prepared, s['war_state'])
            self.assertFalse(cs['orders'])
            self.assertEqual(cs['archive'][-1]['status'], 'expired')
            receipt = next(r for r in cs['receipts'] if r['unit_id'] == self.red['id'])
            self.assertEqual(receipt['source'], 'unavailable')
            if retired:
                s['command_state'] = cs
                s['war_state']['red_units'].append(copy.deepcopy(self.s['war_state']['red_units'][0]))
                new_id = next(u['id'] for u in c.view(s)['units'] if u['name'] == self.red['name'])
                self.assertNotEqual(new_id, self.red['id'])
                self.assertEqual(new_id, next(u['id'] for u in c.view(s)['units'] if u['name'] == self.red['name']))

    def test_changed_rule_version_pauses_existing_order(self):
        s = copy.deepcopy(self.s)
        s['war_state'].pop('mission')
        s['command_state'] = save(s, [self.order()])
        s['time_step'] = '15分钟'
        prepared = c.prepare(s)
        self.assertFalse(prepared['manual'])
        self.assertIn('规则已变更', prepared['blocked'][0]['reason'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
