"""Structured Native unit candidates reuse the public tool/commit boundary."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import harness_engine as h, unit_planning as planning
import verify_unit_output_recovery as fixture


class UnitOrderSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.UnitOutputRecoveryTests()
        self.f.setUp()
        self.args = dict(order=dict(action='hold', duration='next'),
                         rationale='本单位休整，等待宿主结算。', expected_effect='维持当前阵位。')

    def tearDown(self):
        self.f.tearDown()

    def context(self):
        from backend import unit_order_submission as proposal
        return proposal.context(self.f.session, self.f.prepared, self.f.uid,
                                operation_id=self.f.observer.operation_id)

    def events(self, ctx, args=None, *, seq=1, sid='qa-native-unit'):
        from backend import unit_order_submission as proposal
        args = copy.deepcopy(self.args if args is None else args)
        reply = proposal.execute(ctx, dict(tool=proposal.TOOL, args=args))
        self.assertTrue(reply['ok'], reply)
        return [dict(type='tool/call', seq=seq, data=dict(callId=f'c{seq}',
                        name=proposal.TOOL, arguments=json.dumps(args, ensure_ascii=False))),
                dict(type='tool/result', seq=seq+1, data=dict(message=dict(
                    toolCallId=f'c{seq}', content=[dict(type='text', text=json.dumps(reply))])))], reply

    def record(self, ctx, args=None, *, seq=1, text='已提交。', reason='completed'):
        events, reply = self.events(ctx, args, seq=seq)
        run = SimpleNamespace(session_id='qa-native-unit', final_response=text,
                              finish_reason=reason, events=events)
        self.f.observer.record_result(run)
        return run, reply

    def test_structured_candidate_survives_actual_malformed_final_shape_without_json_retry(self):
        before = copy.deepcopy(self.f.session)
        def native(binding, prompt, observer, **kwargs):
            self.assertIn('submit_unit_order', prompt)
            self.assertIn('unit_order', kwargs['context'])
            run, _ = self.record(kwargs['context'], text=fixture.BAD)
            return run, copy.deepcopy(self.f.binding)
        with patch.object(h, 'unit_run', side_effect=native) as run:
            orders, decisions = planning.plan(self.f.session, self.f.prepared, self.f.observer)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(orders[0]['action'], 'hold')
        self.assertEqual(decisions[0]['rationale'], self.args['rationale'])
        self.assertEqual(decisions[0]['proposal']['source'], 'dsh_native_unit_order_tool')
        self.assertEqual(self.f.observer.json_recoveries, 0)
        self.assertEqual(self.f.prepared['state']['agent_sessions'][self.f.uid], self.f.binding)
        self.assertEqual(self.f.session, before)

    def test_normal_command_receipts_retain_proposal_proof_without_a_new_state_store(self):
        from gentactix import commands
        ctx = self.context()
        def native(binding, prompt, observer, **kwargs):
            run, _ = self.record(kwargs['context'])
            return run, copy.deepcopy(self.f.binding)
        with patch.object(h, 'unit_run', side_effect=native):
            orders, decisions = planning.plan(self.f.session, self.f.prepared, self.f.observer)
        after = copy.deepcopy(self.f.session['war_state'])
        cs, rows = commands.finish(self.f.session, self.f.prepared, after,
                                  executed=orders, rationales=decisions, runs=self.f.observer.runs)
        receipt = next(r for r in cs['receipts'] if r['unit_id']==self.f.uid)
        decision = next(r for r in rows if r['unit_id']==self.f.uid)
        self.assertEqual(receipt['proposal'], decisions[0]['proposal'])
        self.assertEqual(decision['proposal'], receipt['proposal'])

    def test_submission_is_readonly_and_exactly_bound_to_unit_world_and_operation(self):
        from backend import unit_order_submission as proposal
        ctx = self.context(); saved = copy.deepcopy((ctx, self.f.session, self.args))
        _, reply = self.record(ctx)
        result, proof = proposal.submitted(self.f.observer, ctx)
        self.assertEqual(result, self.args)
        self.assertEqual(proof['unit_id'], self.f.uid)
        self.assertEqual(proof['proposal_digest'], reply['proposal_digest'])
        self.assertEqual((ctx, self.f.session, self.args), saved)
        for field in ('operation_id', 'unit_id', 'world_version'):
            changed = copy.deepcopy(ctx); changed['unit_order'][field] = 'other'
            with self.subTest(field=field), self.assertRaises(ValueError):
                proposal.submitted(self.f.observer, changed)
        stale = copy.deepcopy(ctx); stale['session']['war_state']['red_units'][0]['hp'] -= 1
        self.assertFalse(proposal.execute(stale, dict(tool=proposal.TOOL, args=self.args))['ok'])

    def test_native_unit_tool_also_works_when_global_planner_uses_json_mode(self):
        from backend import unit_order_submission as proposal
        self.f.session['agent_mode'] = 'json'
        reply = proposal.execute(self.context(), dict(tool=proposal.TOOL, args=self.args))
        self.assertTrue(reply['ok'], reply)

    def test_javascript_integral_number_roundtrip_preserves_candidate_proof(self):
        from backend import unit_order_submission as proposal
        ctx = self.context()
        # Provider tool/call may retain 4.0, while JS JSON.stringify sends 4
        # to the Python bridge. These denote the same JSON integer value.
        public_args = {**self.args, 'order': dict(action='hold', duration='until_turn', end_turn=4.0)}
        bridge_args = copy.deepcopy(public_args); bridge_args['order']['end_turn'] = 4
        events, reply = self.events(ctx, bridge_args)
        events[0]['data']['arguments'] = json.dumps(public_args)
        self.f.observer.record_result(SimpleNamespace(session_id='qa-native-unit', final_response='done',
                                                     finish_reason='completed', events=events))
        args, proof = proposal.submitted(self.f.observer, ctx)
        self.assertIs(type(args['order']['end_turn']), int)
        self.assertEqual(args['order']['end_turn'], 4)
        self.assertEqual(proof['proposal_digest'], reply['proposal_digest'])

    def test_fractional_or_boolean_deadline_is_not_repaired_as_an_integer(self):
        from backend import unit_order_submission as proposal
        ctx = self.context()
        for number in (4.5, True, float('nan'), float('inf')):
            args = {**self.args, 'order': dict(action='hold', duration='until_turn', end_turn=number)}
            saved = copy.deepcopy(args)
            self.assertFalse(proposal.execute(ctx, dict(tool=proposal.TOOL, args=args))['ok'])
            self.assertEqual(type(args['order']['end_turn']), type(saved['order']['end_turn']))

    def test_unknown_fields_wrong_identity_and_long_public_text_are_rejected(self):
        from backend import unit_order_submission as proposal
        ctx = self.context()
        variants = [{**self.args, 'unit_updates': []}, {**self.args, 'rationale': 'x'*1001},
                    {**self.args, 'expected_effect': None}, {**self.args, 'rationale': ''},
                    {**self.args, 'order': {**self.args['order'], 'unit_id': 'other'}},
                    {**self.args, 'order': {**self.args['order'], 'rationale': 'nested'}}]
        for args in variants:
            with self.subTest(args=list(args)):
                self.assertFalse(proposal.execute(ctx, dict(tool=proposal.TOOL, args=args))['ok'])

    def test_effect_fields_name_the_exact_forbidden_order_paths_without_repair(self):
        from backend import unit_order_submission as proposal
        ctx=self.context();saved=copy.deepcopy(ctx)
        args={**self.args,'order':{**self.args['order'],'formation':{'fatigue':0},'fatigue':0}}
        reply=proposal.execute(ctx,dict(tool=proposal.TOOL,args=args))
        self.assertFalse(reply['ok'])
        self.assertIn('order.formation',reply['error'])
        self.assertIn('order.fatigue',reply['error'])
        self.assertIn('action',reply['error'])
        self.assertEqual(ctx,saved)
        self.assertEqual(args['order']['formation'],{'fatigue':0})

    def test_scoped_tool_cannot_bypass_no_fire_or_enable_other_roles(self):
        from backend import unit_order_submission as proposal
        ctx = self.context(); ctx['unit_order']['state']['no_fire'] = True
        from gentactix import commands
        target = next(u['id'] for u in commands.view(self.f.session)['units'] if u['team']=='blue')
        args = {**self.args, 'order': dict(action='fire', duration='next', target_id=target)}
        self.assertFalse(proposal.execute(ctx, dict(tool=proposal.TOOL, args=args))['ok'])
        unscoped = copy.deepcopy(ctx); unscoped.pop('unit_order')
        self.assertFalse(proposal.execute(unscoped, dict(tool=proposal.TOOL, args=self.args))['ok'])
        for role, unit in [('chat', True), ('scenario-builder', True), ('engine', False)]:
            self.assertNotIn(proposal.TOOL, h.role_policy(role, tools=True, unit=unit)['allowed_tools'])
        for external in (False, True):
            policy = h.role_policy('engine', tools=True, unit=True, external=external)
            self.assertIn(proposal.TOOL, policy['allowed_tools'])
            self.assertNotIn('submit_turn_report', policy['allowed_tools'])

    def test_forged_unpaired_failed_and_changed_arguments_cannot_be_accepted(self):
        from backend import unit_order_submission as proposal
        ctx = self.context(); self.record(ctx)
        for variant in ('unpaired', 'failed', 'changed', 'digest', 'wrong_unit'):
            observer = copy.deepcopy(self.f.observer); events = observer.runs[0]['events']
            if variant=='unpaired': del events[0]
            elif variant=='changed':
                args = json.loads(events[0]['arguments']); args['rationale'] += '修改'
                events[0]['arguments'] = json.dumps(args)
            else:
                value = json.loads(events[1]['message']['content'][0]['text'])
                if variant=='failed': value['ok'] = False
                elif variant=='digest': value['proposal_digest'] = '0'*64
                else: value['unit_id'] = 'other'
                events[1]['message']['content'][0]['text'] = json.dumps(value)
            with self.subTest(variant=variant):
                if variant in ('unpaired', 'failed'): self.assertIsNone(proposal.submitted(observer, ctx))
                else:
                    with self.assertRaises(ValueError): proposal.submitted(observer, ctx)

    def test_last_valid_submission_is_selected_and_previous_runs_can_be_excluded(self):
        from backend import unit_order_submission as proposal
        ctx = self.context(); self.record(ctx)
        newer = {**self.args, 'rationale': '最新公开依据。'}; self.record(ctx, newer, seq=3)
        self.assertEqual(proposal.submitted(self.f.observer, ctx)[0], newer)
        self.assertIsNone(proposal.submitted(self.f.observer, ctx, start=2))

    def test_empty_completion_is_allowed_only_with_valid_current_tool_receipt(self):
        from backend import runtime_bridge
        ctx = self.context(); events, _ = self.events(ctx)
        payload = dict(session_id='qa-native-unit', finish_reason='completed', final_response='', events=events)
        class Subscription:
            def drain(self, callback): pass
            def close(self): pass
        harness = SimpleNamespace(client=SimpleNamespace(subscribe_session_notifications=lambda sid:Subscription()))
        with patch.object(h, 'get_harness', return_value=harness), patch.object(runtime_bridge, 'control', return_value=payload):
            result = h._native_control_run('qa-native-unit', '/unit-run', {}, self.f.observer, context=ctx)
        self.assertEqual(result.final_response, '')
        self.assertEqual(self.f.observer.runs[-1]['final_format'], 'native_unit_order_tool')
        self.assertEqual(self.f.observer.empty_recoveries, 0)
        payload['events'] = []
        with patch.object(h, 'get_harness', return_value=harness), patch.object(runtime_bridge, 'control', return_value=payload), self.assertRaises(h.EmptyFinalResponseError):
            h._native_control_run('qa-native-unit', '/unit-run', {}, self.f.observer, context=ctx)

    def test_aborted_or_max_tokens_runtime_cannot_use_an_accepted_tool(self):
        from backend import runtime_bridge
        ctx = self.context(); events, _ = self.events(ctx)
        class Subscription:
            def drain(self, callback): pass
            def close(self): pass
        harness = SimpleNamespace(client=SimpleNamespace(subscribe_session_notifications=lambda sid:Subscription()))
        for reason in ('error', 'max-tokens', 'aborted'):
            payload = dict(session_id='qa-native-unit', finish_reason=reason, final_response='done', events=events)
            with self.subTest(reason=reason), patch.object(h, 'get_harness', return_value=harness), patch.object(runtime_bridge, 'control', return_value=payload), self.assertRaises(h.HarnessRunError):
                h._native_control_run('qa-native-unit', '/unit-run', {}, self.f.observer, context=ctx)


class UnitOrderRouteTests(unittest.TestCase):
    def setUp(self):
        import verify_command_backend as api_fixture
        from backend import main
        self.api = api_fixture.CommandAPITests(); self.api.setUp()
        self.addCleanup(self.api.tearDown)
        self.main = main; self.session = main._SESSIONS[self.api.sid]
        view = self.api.view(); self.uid = view['units'][0]['id']
        self.api.put([dict(unit_id=u['id'], action='hold') for u in view['units'][1:]], unit_agents=[self.uid])
        self.calls = 0; self.proof = None

    def native(self, binding, prompt, observer, **kwargs):
        self.calls += 1
        args = dict(order=dict(action='hold', duration='next'), rationale='本单位按当前态势保持阵位。', expected_effect='等待整轮结算。')
        ctx = kwargs['context']; sid = 'gentactix-unit-' + kwargs['namespace'] + '-qa'
        reply = self.main._native_tool_dispatch(ctx, dict(tool='submit_unit_order', session_id=sid, args=args))
        self.assertTrue(reply['ok'], reply); self.proof = reply['proposal_digest']
        events = [dict(type='tool/call', seq=1, data=dict(name='submit_unit_order', callId='unit', arguments=args)),
                  dict(type='tool/result', seq=2, data=dict(message=dict(toolCallId='unit', content=[dict(type='text', text=json.dumps(reply))])))]
        run = SimpleNamespace(session_id=sid, finish_reason='completed', final_response=fixture.BAD, events=events)
        observer.record_result(run)
        return run, dict(session_id=sid, factory='DSH.AgentRegistry', persistence='session_journal')

    def test_exactly_once_commit_persists_proof_and_original_native_binding_on_cold_restore(self):
        from backend import session_store
        request = self.api.request()
        with patch.object(h, 'unit_run', side_effect=self.native), patch.object(h, 'get_ai_response', side_effect=AssertionError('covered')):
            response = self.api.client.post(self.api.path+'/next', json=request)
            repeated = self.api.client.post(self.api.path+'/next', json=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(repeated.status_code, 200, repeated.text); self.assertEqual(self.calls, 1)
        self.assertEqual(self.session['turn_count'], 1)
        row = next(r for r in self.session['trajectory'][-1]['decisions'] if r['unit_id']==self.uid)
        self.assertEqual(row['proposal']['proposal_digest'], self.proof)
        loaded, errors = session_store.load_all(); self.assertFalse(errors)
        self.assertEqual(loaded[self.api.sid]['war_state'], self.session['war_state'])
        self.assertEqual(loaded[self.api.sid]['command_state'], self.session['command_state'])
        self.assertEqual(loaded[self.api.sid]['trajectory'][-1]['decisions'], self.session['trajectory'][-1]['decisions'])

    def test_cancel_after_candidate_preserves_world_queue_tasks_and_native_bindings(self):
        before = copy.deepcopy(self.session)
        def cancel(*args, **kwargs):
            value = self.native(*args, **kwargs); self.session['cancel_requested'] = True; return value
        with patch.object(h, 'unit_run', side_effect=cancel):
            response = self.api.client.post(self.api.path+'/next', json=self.api.request())
        self.assertEqual(response.status_code, 409, response.text)
        for field in ('war_state', 'command_state', 'turn_count'):
            self.assertEqual(self.session[field], before[field])

    def test_disk_failure_after_candidate_cannot_consume_orders_or_adopt_binding(self):
        from backend import session_store
        before = copy.deepcopy(self.session)
        with patch.object(h, 'unit_run', side_effect=self.native), patch.object(session_store, 'save', side_effect=OSError('QA full disk')):
            response = self.api.client.post(self.api.path+'/next', json=self.api.request())
        self.assertEqual(response.status_code, 502, response.text)
        for field in ('war_state', 'command_state', 'turn_count'):
            self.assertEqual(self.session[field], before[field])


if __name__ == '__main__': unittest.main()
