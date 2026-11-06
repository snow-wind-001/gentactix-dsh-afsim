"""Control identity, cancellation, resumption and untrusted proposal regressions."""
import copy, json, unittest
from unittest.mock import patch
from gentactix import commands, crossings
from backend import dsh_simulation
import verify_afsim_crossing as fixture
from verify_dsh_crossing import proposal
from verify_dsh_resources import model_result

class CrossingControlTests(unittest.TestCase):

    def setUp(self):
        self.fixture = fixture.NativeCrossingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s = {'id': 'qa-control', 'war_state': self.fixture.world, 'turn_count': 0, 'time_step': '30分钟', 'simulation_mode': 'open', 'execution_backend': 'narrative'}
        self.identity = commands.view(self.s)['units'][0]['id']
        self.move = {'unit_id': self.identity, 'action': 'move', 'destination': {'lat': 27.303, 'lng': 107.4}, 'duration': 'until_arrived'}
        self.queue([self.move])
        self.advance(proposal(self.s['war_state']))

    def queue(self, orders):
        self.s['command_state'] = commands.replace_queue(self.s, orders, control_team='red', director=False, no_fire=False, intent='')

    def advance(self, value):
        prepared = commands.prepare(self.s)
        with patch.object(dsh_simulation.h, 'get_ai_response', return_value=value):
            result, orders, _ = dsh_simulation.advance(self.s, prepared, None)
        after = result['updated_state']
        cs, _ = commands.finish(self.s, prepared, after, executed=orders)
        self.s.update(war_state=after, command_state=cs, turn_count=self.s['turn_count'] + 1)
        return after

    def test_cancel_is_control_input_then_native_or_dsh_receipt_not_immediate_world_rewrite(self):
        prior = copy.deepcopy(self.s['war_state'])
        old = self.s['command_state']['orders'][0]['id']
        self.s['command_state'] = commands.cancel(self.s, old)
        self.assertEqual(self.s['war_state'], prior)
        self.assertEqual(commands.prepare(self.s)['cancelled_tasks'][0]['id'], old)
        v = model_result(prior)
        v['unit_updates'][0]['crossing'] = {'served_work': 300, 'last_work': 0, 'status': 'cancelled', 'events': []}
        after = self.advance(v)
        task = after['red_units'][0]['crossing']
        self.assertEqual(task['intent_id'], old)
        self.assertEqual(task['served_work'], 300)
        self.assertEqual(task['status'], 'cancelled')
        receipt = next((r for r in reversed(self.s['command_state']['receipts']) if r['unit_id'] == self.identity))
        self.assertEqual(receipt['status'], 'cancelled')
        self.assertIn('不退回', receipt['reason'])
        self.assertEqual(after['red_units'][0]['personnel'], prior['red_units'][0]['personnel'])

    def test_cancel_and_reissue_same_destination_cannot_reuse_previous_service(self):
        old = self.s['command_state']['orders'][0]['id']
        self.s['command_state'] = commands.cancel(self.s, old)
        self.queue([self.move])
        new = self.s['command_state']['orders'][0]['id']
        self.assertNotEqual(old, new)
        after = self.advance(proposal(self.s['war_state']))
        self.assertEqual(after['red_units'][0]['crossing']['intent_id'], new)
        self.assertEqual(after['red_units'][0]['crossing']['served_work'], 300)
        self.assertEqual(after['red_units'][0]['crossing']['last_work'], 300)

    def test_unchanged_confirmed_command_keeps_identity_and_previous_service(self):
        old = copy.deepcopy(self.s['command_state']['orders'][0])
        self.queue([{k: old[k] for k in ('id', 'unit_id', 'action', 'destination', 'duration')}])
        self.assertEqual(self.s['command_state']['orders'][0]['id'], old['id'])
        v = proposal(self.s['war_state'], 400)
        v['unit_updates'][0]['crossing']['last_work'] = 100
        v['combined_arms']['bridge']['crossing_receipt']['used_work'] = 100
        after = self.advance(v)
        self.assertEqual(after['red_units'][0]['crossing']['served_work'], 400)
        self.assertEqual(after['red_units'][0]['crossing']['intent_id'], old['id'])

    def test_model_cannot_forge_the_host_intent_to_claim_old_work(self):
        before = copy.deepcopy(self.s['war_state'])
        v = proposal(before, 400)
        v['orders'][0]['intent_id'] = before['red_units'][0]['crossing']['intent_id']
        v['unit_updates'][0]['crossing']['last_work'] = 100
        v['combined_arms']['bridge']['crossing_receipt']['used_work'] = 100
        with patch.object(dsh_simulation.h, 'get_ai_response', return_value=v), self.assertRaises(ValueError):
            dsh_simulation.advance(self.s, None, None)
        self.assertEqual(self.s['war_state'], before)

    def test_identical_counterfactual_uses_factual_identity_without_mutating_request(self):
        before = copy.deepcopy(self.s['war_state'])
        factual = copy.deepcopy(before['mission']['last_orders'])
        request = copy.deepcopy(factual)
        request[0]['intent_id'] = 'b' * 32
        record = {'after': before}
        resolved = crossings.comparison_orders(record, request)
        self.assertEqual(resolved, factual)
        self.assertEqual(request[0]['intent_id'], 'b' * 32)
        changed = copy.deepcopy(request)
        moving = next((o for o in changed if o['action'] == 'move'))
        moving['lng'] += 0.001
        self.assertEqual(next((o for o in crossings.comparison_orders(record, changed) if o['action'] == 'move'))['intent_id'], moving.get('intent_id'))

    def test_previous_unbound_task_remains_unbound_under_its_existing_command(self):
        legacy = dsh_simulation.apply(self.fixture.world, proposal(self.fixture.world), '30分钟')
        self.s['war_state'] = legacy
        order = self.s['command_state']['orders'][0]
        order['created_turn'] = 0
        raw = commands.prepare(self.s)['manual'][0]['order']
        self.assertNotIn('intent_id', raw)
        self.assertEqual(crossings.plan(legacy['combined_arms']['bridge'], legacy['red_units'][0], raw)['task']['served_work'], 300)

    def test_native_compiler_preserves_host_identity_and_cancellation_for_replacement(self):
        from backend import afsim_world
        self.s['command_state'] = commands.cancel(self.s, self.s['command_state']['orders'][0]['id'])
        self.queue([self.move])
        prepared = commands.prepare(self.s)
        orders = commands.merge_proposal(self.s, prepared, [])
        scene = afsim_world.compile_scene(self.s['war_state'], orders, 1800, native_rules=True)
        entity = next((e for e in scene['entities'].values() if e['name'] == orders[0]['unit']))
        self.assertEqual(entity['crossing_plan']['task']['intent_id'], orders[0]['intent_id'])
        self.assertEqual(entity['crossing_plan']['task']['served_work'], 0)

    def test_comparison_labels_work_for_the_current_task_not_a_lifetime_total(self):
        from gentactix import missions
        result = missions.compare_states(self.fixture.world, self.s['war_state'], self.s['war_state'], [])
        labels = {r['metric'] for r in result['metrics']}
        self.assertIn('红方当前任务已服务工作量', labels)
        self.assertNotIn('红方累计渡运工作量', labels)

    def test_unreceived_native_cancellation_is_not_reported_as_executed(self):
        self.s['execution_backend'] = 'afsim'
        self.s['command_state'] = commands.cancel(self.s, self.s['command_state']['orders'][0]['id'])
        prepared = commands.prepare(self.s)
        after = copy.deepcopy(self.s['war_state'])
        after['red_units'][0]['formation']['last_execution'] = {'turn': 2, 'blocked': 0, 'action': '未交付'}
        cs, _ = commands.finish(self.s, prepared, after, executed=commands.merge_proposal(self.s, prepared, []))
        receipt = next((r for r in reversed(cs['receipts']) if r['unit_id'] == self.identity))
        self.assertEqual(receipt['status'], 'blocked')
        self.assertIn('未交付', receipt['reason'])
        self.assertEqual(len(cs['archive']), 1)
        self.s.update(command_state=cs, war_state=after, turn_count=2)
        self.assertEqual(len(commands.prepare(self.s)['cancelled_tasks']), 1)

    def test_replacement_exposes_zero_start_work_without_rewriting_previous_task(self):
        before = copy.deepcopy(self.s['war_state'])
        self.s['command_state'] = commands.cancel(self.s, self.s['command_state']['orders'][0]['id'])
        self.queue([self.move])
        prepared = commands.prepare(self.s)
        item = next(r for r in prepared['crossing_inputs'] if r['unit'] == before['red_units'][0]['name'])
        self.assertEqual(item['start_work'], 0)
        self.assertEqual(item['required_work'], 600)
        self.assertEqual(item['operation'], 'start')
        self.assertEqual(self.s['war_state'], before)
        self.assertIn('crossing_inputs', commands.instruction(prepared))

    def test_retry_draft_does_not_copy_host_control_tokens_into_model_output_example(self):
        bad = proposal(self.s['war_state'], 400)
        bad['unit_updates'][0]['crossing']['last_work'] = 100
        bad['unit_updates'][0]['crossing']['events'] = []
        bad['combined_arms']['bridge']['crossing_receipt']['used_work'] = 100
        good = copy.deepcopy(bad)
        good['unit_updates'][0]['crossing']['events'] = [{'phase': 'entered', 'seconds': 0, 'lat': 27.299, 'lng': 107.4}]
        with patch.object(dsh_simulation.h, 'get_ai_response', side_effect=[bad, good]) as model:
            dsh_simulation.advance(self.s, commands.prepare(self.s), None)
        text = model.call_args.args[0].split('上次候选（未执行的模型草稿，非新态势）：')[1].split('\n纠正上述')[0]
        draft = json.loads(text)
        self.assertTrue(all(not {'intent_id', 'cancel_crossing'} & set(o) for o in draft['orders']))
if __name__ == '__main__':
    unittest.main()
