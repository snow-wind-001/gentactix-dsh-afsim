"""Native batch proposals over 22 identities; offline transport fixtures only."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import harness_engine as h, unit_order_submission as submission
from gentactix import commands
from tools.qa.turn_preview_page_fixture import session


class PlannerOrderSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.session = session()
        self.session.update(execution_backend='afsim', scenario_input='22单位混合指挥离线回归，非真实推演')
        view = commands.view(self.session)
        self.human = next(u for u in view['units'] if u['team'] == 'red')
        self.agent = next(u for u in view['units'] if u['team'] == 'blue')
        state = commands.replace_queue(self.session,
            [dict(unit_id=self.human['id'], action='hold', duration='next')],
            control_team='red', director=True, no_fire=False, intent='离线验收')
        state['unit_agents'] = [self.agent['id']]
        self.session['command_state'] = state
        self.prepared = commands.prepare(self.session)
        self.covered = {self.human['name'], self.agent['name']}
        self.observer = h.RunObserver('offline planner proposal')
        self.ctx = submission.planner_context(self.session, self.prepared, self.covered,
            operation_id=self.observer.operation_id)
        self.args = dict(orders=[dict(unit_id=u['id'], action='hold', duration='next',
            rationale='依据本轮权威状态休整。', expected_effect='保持阵位，等待实际结算。')
            for u in view['units'] if u['available'] and u['name'] not in self.covered])

    def record(self, *, text='已提交。', reason='completed', args=None, record=True):
        args = copy.deepcopy(self.args if args is None else args)
        reply = submission.execute_planner(self.ctx, dict(tool=submission.PLANNER_TOOL, args=args))
        self.assertTrue(reply['ok'], reply)
        events = [dict(type='tool/call', seq=1, data=dict(name=submission.PLANNER_TOOL,
            callId='planner', arguments=json.dumps(args, ensure_ascii=False))),
            dict(type='tool/result', seq=2, data=dict(message=dict(toolCallId='planner',
                content=[dict(type='text', text=json.dumps(reply))])))]
        result = SimpleNamespace(session_id='qa-planner', finish_reason=reason,
            final_response=text, events=events)
        if record: self.observer.record_result(result)
        return result, reply

    def test_twenty_remaining_orders_are_readonly_and_exclude_both_takeovers(self):
        self.assertEqual(len(self.args['orders']), 20)
        before = copy.deepcopy((self.session, self.prepared, self.ctx, self.args))
        _, reply = self.record()
        args, proof = submission.submitted_planner(self.observer, self.ctx)
        self.assertEqual(args, self.args)
        self.assertEqual(reply['order_count'], 20)
        self.assertEqual(proof['source'], 'dsh_native_planner_order_tool')
        self.assertEqual(proof['proposal_digest'], reply['proposal_digest'])
        self.assertEqual((self.session, self.prepared, self.ctx, self.args), before)

    def test_missing_duplicate_unknown_and_protected_units_are_rejected(self):
        for variant in ('missing', 'duplicate', 'unknown', 'human', 'agent'):
            args = copy.deepcopy(self.args)
            if variant == 'missing': args['orders'].pop()
            else:
                args['orders'][-1]['unit_id'] = {
                    'duplicate': args['orders'][0]['unit_id'], 'unknown': 'invented-id',
                    'human': self.human['id'], 'agent': self.agent['id']}[variant]
            with self.subTest(variant=variant):
                saved = copy.deepcopy((self.ctx, args))
                reply = submission.execute_planner(self.ctx, dict(tool=submission.PLANNER_TOOL, args=args))
                self.assertFalse(reply['ok'], reply)
                self.assertEqual((self.ctx, args), saved)

    def test_bad_fields_effects_and_empty_rationale_are_not_repaired(self):
        for variant in ('extra', 'state', 'rationale', 'duration', 'action'):
            args = copy.deepcopy(self.args)
            if variant == 'extra': args['updated_state'] = {}
            elif variant == 'state': args['orders'][0]['personnel'] = 9000
            elif variant == 'rationale': args['orders'][0]['rationale'] = ''
            elif variant == 'duration': args['orders'][0]['duration'] = 'until_turn'
            else: args['orders'][0]['action'] = 'invented-action'
            with self.subTest(variant=variant):
                self.assertFalse(submission.execute_planner(self.ctx,
                    dict(tool=submission.PLANNER_TOOL, args=args))['ok'])

    def test_stale_world_or_command_revision_is_rejected(self):
        for variant in ('world', 'commands'):
            ctx = copy.deepcopy(self.ctx)
            if variant == 'world': ctx['session']['war_state']['red_units'][0]['logistics']['food'] -= 1
            else: ctx['session']['command_state']['revision'] += 1
            with self.subTest(variant=variant):
                self.assertFalse(submission.execute_planner(ctx,
                    dict(tool=submission.PLANNER_TOOL, args=self.args))['ok'])

    def test_no_explicit_planner_binding_means_no_submission(self):
        ctx = copy.deepcopy(self.ctx)
        ctx.pop('planner_orders')
        self.assertFalse(submission.execute_planner(ctx,
            dict(tool=submission.PLANNER_TOOL, args=self.args))['ok'])

    def test_replay_and_other_backend_do_not_gain_proposal_permission(self):
        for field, value in [('simulation_mode', 'replay'), ('execution_backend', 'narrative')]:
            ctx = copy.deepcopy(self.ctx); ctx['session'][field] = value
            with self.subTest(field=field):
                self.assertFalse(submission.execute_planner(ctx,
                    dict(tool=submission.PLANNER_TOOL, args=self.args))['ok'])

    def test_corrupted_operation_or_candidate_proof_is_rejected(self):
        for variant in ('operation_id', 'proposal_digest', 'required_units_digest'):
            self.observer = h.RunObserver('offline forged planner proof')
            self.record()
            event = self.observer.runs[-1]['events'][-1]
            reply = json.loads(event['message']['content'][0]['text'])
            reply[variant] = 'forged'
            event['message']['content'][0]['text'] = json.dumps(reply)
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                submission.submitted_planner(self.observer, self.ctx)

    def test_failed_runtime_or_unpaired_tool_is_not_accepted(self):
        for variant in ('error', 'max-tokens', 'aborted', 'unpaired'):
            self.observer = h.RunObserver('offline incomplete planner proof')
            self.record(reason=variant if variant != 'unpaired' else 'completed')
            if variant == 'unpaired': self.observer.runs[-1]['events'].pop(0)
            with self.subTest(variant=variant):
                self.assertIsNone(submission.submitted_planner(self.observer, self.ctx))

    def test_harness_consumes_native_proof_without_recopying_final_json(self):
        def run(*args, **kwargs):
            return self.record(text='候选已提交；尚未执行。')[0]
        with patch.object(h, '_run_brain', side_effect=run):
            result = h.get_ai_response('工具提交，不重抄JSON', observer=self.observer, native_context=self.ctx)
        self.assertEqual(result, self.args)
        self.assertEqual(self.observer.runs[-1]['final_format'], 'native_planner_order_tool')
        self.assertEqual(self.observer.json_recoveries, 0)

    def test_plain_final_without_tool_remains_strict(self):
        result = SimpleNamespace(final_response='口头声称已提交')
        with patch.object(h, '_run_brain', return_value=result), self.assertRaises(h.JSONOutputError):
            h.get_ai_response('legacy fallback', observer=self.observer, native_context=self.ctx)

    def test_valid_legacy_json_is_not_credited_as_native_submission(self):
        result = SimpleNamespace(session_id='legacy-qa', finish_reason='completed',
            final_response=json.dumps(self.args, ensure_ascii=False), events=[])
        self.observer.record_result(result)
        with patch.object(h, '_run_brain', return_value=result):
            value = h.get_ai_response('legacy fallback', observer=self.observer, native_context=self.ctx)
        self.assertEqual(value, self.args)
        self.assertEqual(self.observer.runs[-1]['final_format'], 'legacy_planner_json')

    def test_completed_empty_ack_uses_only_the_current_native_receipt(self):
        result, _ = self.record(text='', record=False)
        with patch.object(h, 'complete_ex', side_effect=lambda *a, **kw: h._gate(result)):
            value = h.get_ai_response('native submit', observer=self.observer, native_context=self.ctx)
        self.assertEqual(value, self.args)
        self.assertEqual(self.observer.empty_recoveries, 0)
        self.assertEqual(self.observer.last_finish, 'completed')

    def test_runtime_failure_cannot_be_overridden_by_a_candidate_receipt(self):
        for reason in ('error', 'max-tokens', 'aborted'):
            result, _ = self.record(reason=reason, record=False)
            with self.subTest(reason=reason), patch.object(h, 'complete_ex',
                    side_effect=lambda *a, **kw: h._gate(result)), self.assertRaises(h.HarnessRunError):
                h.get_ai_response('native submit', observer=self.observer, native_context=self.ctx)

    def test_planner_tool_is_not_exposed_to_unit_or_unbound_roles(self):
        self.assertIn(submission.PLANNER_TOOL, h.role_policy(tools=True, external=True, planner=True)['allowed_tools'])
        for options in ({}, dict(tools=True), dict(tools=True, external=True), dict(tools=True, external=True, unit=True)):
            self.assertNotIn(submission.PLANNER_TOOL, h.role_policy(**options)['allowed_tools'])

    def test_mixed_advance_keeps_human_and_agent_orders_and_records_proof(self):
        from backend import afsim_turns
        native = [commands.step_order(self.session, dict(unit_id=self.agent['id'],
            action='hold', duration='next'), self.prepared['state'])]
        def run(*args, **kwargs):
            self.ctx = kwargs['native_context']
            return self.record()[0]
        with patch.object(h, 'NATIVE_RUNTIME', True), patch.object(h, '_run_brain', side_effect=run), \
                patch.object(afsim_turns, 'execute_scene', return_value='fixture') as execute:
            result = afsim_turns.advance(self.session, self.prepared, self.observer, native_orders=native)
        self.assertEqual(result, 'fixture')
        orders = execute.call_args.args[1]
        self.assertEqual(len(orders), 22)
        self.assertEqual(len({o['unit'] for o in orders}), 22)
        decisions = execute.call_args.kwargs['decisions']
        self.assertEqual(len(decisions), 20)
        self.assertTrue(all(d['proposal']['source'] == 'dsh_native_planner_order_tool' for d in decisions))
        state, records = commands.finish(self.session, self.prepared,
            copy.deepcopy(self.session['war_state']), executed=orders,
            rationales=decisions, runs=self.observer.runs)
        self.assertEqual(sum('proposal' in r for r in records), 20)
        self.assertEqual(sum('proposal' in r for r in state['receipts']), 20)

    def test_native_retry_requests_tool_without_replaying_invalid_text(self):
        from backend import afsim_turns
        native = [commands.step_order(self.session, dict(unit_id=self.agent['id'],
            action='hold', duration='next'), self.prepared['state'])]
        error = h.JSONOutputError('untrusted raw content', raw_text='untrusted raw content', reason='missing_complete_object')
        with patch.object(h, 'NATIVE_RUNTIME', True), \
             patch.object(h, 'get_ai_response', side_effect=[error, self.args]) as planner, \
             patch.object(afsim_turns, 'execute_scene', return_value='fixture') as execute:
            self.assertEqual(afsim_turns.advance(self.session, self.prepared, self.observer, native_orders=native), 'fixture')
        self.assertEqual(planner.call_count, 2)
        retry = planner.call_args.args[0]
        self.assertIn('submit_planner_orders', retry)
        self.assertNotIn('untrusted raw content', retry)
        execute.assert_called_once()


if __name__ == '__main__':
    unittest.main()
