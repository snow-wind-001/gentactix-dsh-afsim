"""AFSIM integration contracts with a deterministic test executor; not a live probe."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from backend import main, harness_engine as h, afsim_world
    from verify_afsim_world import world
    HAS_SDK = True
except ImportError:
    HAS_SDK = False


@unittest.skipUnless(HAS_SDK, 'Requires the desktop SDK environment')
class AfsimBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.patches = []
        def use(value):
            self.patches.append(value); return value.start()
        use(patch.dict(os.environ, {'GENTACTIX_TRACE_DIR': self.temp.name + '/traces', 'GENTACTIX_SESSION_DIR': self.temp.name + '/sessions'}))
        use(patch.object(h, 'enable_afsim_runtime'))
        use(patch('tools.afsim.launch.status', return_value={'available': True, 'missing': [], 'verified': False}))
        use(patch.object(h, 'get_ai_response_with_retry', return_value=world()))
        use(patch.object(h, 'get_role_session', return_value=None))
        self.planner = use(patch.object(h, 'get_ai_response',
            side_effect=lambda *a, **kw: self.full_plan(kw['native_context']['session']['id'])))
        self.executor = use(patch.object(afsim_world, 'run_scene', side_effect=self.execute))
        main._SESSIONS.clear(); self.client = TestClient(main.app)

    def tearDown(self):
        for value in reversed(self.patches): value.stop()
        main._SESSIONS.clear(); self.temp.cleanup()

    def execute(self, session, scene, *_args, **_kwargs):
        evidence={'source': 'test_fixture', 'status': 'completed', 'returncode': 0, 'wall_ms': 1,
                 'seconds': scene['seconds'], 'entity_count': len(scene['entities']), 'scope': afsim_world.SCOPE}
        if scene.get('native_model'):
            # Explicit deterministic executor fixture. Real WSF comparisons run
            # separately; never label this oracle result as a native execution.
            from gentactix import missions
            from backend import afsim_rules
            expected=missions.advance(session['war_state'],scene['native_model']['orders'],session['time_step'])
            by_name={u['name']:u for _,u in missions.units(expected)}; ledger={r['unit']:r for r in expected['mission']['ledger']}
            rows={}
            for identity,entity in scene['entities'].items():
                u=by_name[entity['name']]; row={**u['personnel'],**u['equipment'][0],**u['logistics'],
                    'hp100':round(u['hp']*100),'supply':u['supply'],**ledger.get(u['name'],{})}
                row['connectivity']={'未切断':1,'已切断':0}.get(row.get('supply_status'),-1)
                rows[identity]={key:row.get(key,0) for key in afsim_rules.UNIT_FIELDS}
            m=expected['mission']; goal={**m,**m['metrics'],'terminal':int(m['status']=='completed'),'success':int(m.get('winner')=='red')}
            evidence['native_effects']={'version':afsim_rules.VERSION,'input_digest':scene['native_model']['input_digest'],'units':rows,
                'depots':{i:d['stock'] for i,d in enumerate(expected['supply_nodes'])},
                'mission':{key:goal[key] for key in afsim_rules.MISSION_FIELDS}}
        return ({identity:entry['target'] for identity,entry in scene['entities'].items()},evidence)

    def create(self, **options):
        response = self.client.post('/api/sessions', json={'scenario': '教学测试', 'time_step': '15分钟',
            'execution_backend': 'afsim', 'persist_roles': False, **options})
        self.assertEqual(response.status_code, 200, response.text)
        sid = response.json()['session_id']
        response = self.client.post(f'/api/sessions/{sid}/init')
        self.assertEqual(response.status_code, 200, response.text)
        return sid

    def advance(self, sid, batch='test-batch'):
        view = self.client.get(f'/api/sessions/{sid}/commands').json()
        return self.client.post(f'/api/sessions/{sid}/next', json={'batch_id': batch,
            'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version']})

    def queue_all(self, sid):
        view = self.client.get(f'/api/sessions/{sid}/commands').json()
        response = self.client.put(f'/api/sessions/{sid}/commands', json={'expected_turn': view['turn'],
            'revision': view['revision'], 'world_version': view['world_version'], 'director': True,
            'orders': [{'unit_id': unit['id'], 'action': 'hold', 'duration': 'next'} for unit in view['units']]})
        self.assertEqual(response.status_code, 200, response.text)

    def test_manual_batch_executes_without_model_and_preserves_ledger(self):
        sid = self.create(); before = copy.deepcopy(main._SESSIONS[sid]['war_state'])
        self.queue_all(sid); response = self.advance(sid)
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()['war_state']
        self.planner.assert_not_called()
        for key, value in before['red_units'][0]['personnel'].items():
            self.assertEqual(after['red_units'][0]['personnel'][key], value)
        self.assertEqual(after['afsim']['effects_source'], 'not_modeled; existing_ledgers_preserved')
        self.assertEqual(after['simulation_clock']['elapsed_seconds'], 900)

    def test_model_cannot_replace_authoritative_world(self):
        sid = self.create(); before = copy.deepcopy(main._SESSIONS[sid]['war_state'])
        self.planner.side_effect = None
        self.planner.return_value = {'updated_state': {'red_units': []}}
        calls = self.executor.call_count
        response = self.advance(sid)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(main._SESSIONS[sid]['war_state'], before)
        self.assertEqual(self.executor.call_count, calls)

    def full_plan(self, sid):
        from gentactix import commands
        return {'orders': [{'unit_id': identity, 'action': 'hold',
            'rationale': '守备观察，暂不主动射击', 'expected_effect': '保持阵地'}
            for identity, (entry, unit) in commands.resolve_units(main._SESSIONS[sid]).items()
            if commands.available(unit)]}

    def test_missing_blue_decisions_retry_before_execution(self):
        sid = self.create(); complete = self.full_plan(sid)
        from gentactix import commands
        blue = {i for i, (e, _) in commands.resolve_units(main._SESSIONS[sid]).items() if e['team'] == 'blue'}
        partial = {'orders': [o for o in complete['orders'] if o['unit_id'] not in blue]}
        self.planner.side_effect = [partial, complete]
        result = self.advance(sid)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.planner.call_count, 2)
        self.assertIn('遗漏', self.planner.call_args.args[0])
        receipts = main._SESSIONS[sid]['command_state']['receipts']
        self.assertTrue(all(r['source'] != 'default_hold' for r in receipts if r['team'] == 'blue'))

    def test_repeated_missing_blue_plan_is_not_committed(self):
        sid = self.create(); before = copy.deepcopy(main._SESSIONS[sid]['war_state'])
        self.planner.side_effect = None; self.planner.return_value = {'orders': []}
        calls = self.executor.call_count
        result = self.advance(sid)
        self.assertEqual(result.status_code, 502, result.text)
        self.assertIn('遗漏', result.text)
        self.assertEqual(self.executor.call_count, calls)
        self.assertEqual(main._SESSIONS[sid]['war_state'], before)

    def test_known_battle_rejects_wrong_continent_before_native_load(self):
        broken = world()
        broken['center'] = [40.78341, 114.87139]
        for _, unit in __import__('gentactix.commands', fromlist=['iter_units']).iter_units(broken):
            unit.update(lat=40.78341, lng=114.87139)
        broken['blue_units'][0].update(lat=40.792, lng=40.792)
        calls = self.executor.call_count
        with patch.object(h, 'get_ai_response_with_retry', return_value=broken):
            response = self.client.post('/api/sessions', json={'scenario': '张家口局部战斗',
                'battle': '抗日战争-全面反攻与受降总览-1945.08至1945.09', 'execution_backend': 'afsim'})
            sid = response.json()['session_id']
            response = self.client.post(f'/api/sessions/{sid}/init')
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn('战区', response.text)
        self.assertEqual(self.executor.call_count, calls)
        self.assertIsNone(main._SESSIONS[sid]['war_state'])

    def test_bad_planner_ids_get_one_feedback_retry_before_native_execution(self):
        sid = self.create()
        self.planner.side_effect = [{'orders': [{'unit_id': 'invented', 'action': 'hold'}]}, self.full_plan(sid)]
        calls = self.executor.call_count
        result = self.advance(sid)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.planner.call_count, 2)
        self.assertEqual(self.executor.call_count, calls + 1)
        self.assertIn('候选未执行', self.planner.call_args.args[0])

    def test_malformed_json_gets_existing_feedback_retry_before_execution(self):
        sid = self.create(); calls = self.executor.call_count
        malformed = '{"orders":[{"destination":{"lat":39.97,","lng":125.8035}}]}'
        def first(*_args, **_kwargs):
            self.planner.side_effect = None
            self.planner.return_value = self.full_plan(sid)
            return h.parse_json_object(malformed)
        self.planner.side_effect = first
        result = self.advance(sid)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.planner.call_count, 2)
        self.assertEqual(self.executor.call_count, calls + 1)
        self.assertIn('JSON', self.planner.call_args.args[0])
        self.assertIn('候选未执行', self.planner.call_args.args[0])

    def test_repeated_parse_failure_keeps_world_time_and_manual_queue(self):
        sid = self.create()
        view = self.client.get(f'/api/sessions/{sid}/commands').json()
        self.client.put(f'/api/sessions/{sid}/commands', json={'expected_turn':view['turn'],
            'revision':view['revision'],'world_version':view['world_version'],'director':True,
            'orders':[{'unit_id':view['units'][0]['id'],'action':'hold','duration':'next'}]})
        session = main._SESSIONS[sid]
        before = copy.deepcopy(session['war_state']); queue = copy.deepcopy(session['command_state'])
        calls = self.executor.call_count
        self.planner.side_effect = ValueError('AI 返回的 JSON 无法解析：bad delimiter')
        result = self.advance(sid)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.planner.call_count, 2)
        self.assertEqual(self.executor.call_count, calls)
        self.assertEqual(session['war_state'], before)
        self.assertEqual(session['command_state'], queue)
        self.assertEqual(session['turn_count'], 0)

    def test_cancel_after_parse_failure_prevents_retry_and_execution(self):
        sid = self.create(); session = main._SESSIONS[sid]
        before = copy.deepcopy(session['war_state']); calls = self.executor.call_count
        def failed(*_args, **_kwargs):
            session['cancel_requested'] = True
            raise ValueError('AI 返回的 JSON 无法解析：bad delimiter')
        self.planner.side_effect = failed
        result = self.advance(sid)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.planner.call_count, 1)
        self.assertEqual(self.executor.call_count, calls)
        self.assertEqual(session['war_state'], before)

    def test_runtime_failure_does_not_consume_queue_or_advance_time(self):
        sid = self.create(); self.queue_all(sid)
        session = main._SESSIONS[sid]; before = copy.deepcopy(session['war_state']); queue = copy.deepcopy(session['command_state'])
        self.executor.side_effect = RuntimeError('AFSIM runtime disconnected')
        response = self.advance(sid)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(session['war_state'], before)
        self.assertEqual(session['turn_count'], 0)
        self.assertEqual(session['command_state'], queue)

    def test_legacy_mode_does_not_activate_afsim(self):
        response = self.client.post('/api/sessions', json={'scenario': 'legacy'})
        sid = response.json()['session_id']
        self.assertNotIn('execution_backend', main._SESSIONS[sid])

    def test_external_planner_cannot_read_unbounded_legacy_world_tools(self):
        policy = h.role_policy('engine', tools=True, external=True)
        self.assertEqual(set(policy['allowed_tools']), {
            'get_campaign_lifecycle', 'get_force_tasks', 'get_campaign_objectives', 'get_force_organization', 'preview_force_task', 'preview_force_conversion', 'get_afsim_observation', 'get_afsim_changes', 'retrieve_history', 'evaluate_action'})
        self.assertEqual(policy['max_tokens'], h.role_policy('engine', tools=True)['max_tokens'])
        self.assertEqual(policy['reasoning_effort'], h.role_policy('engine', tools=True)['reasoning_effort'])

    def test_first_external_turn_has_command_batch_contract_before_saving_orders(self):
        sid = self.create()
        self.assertNotIn('command_state', main._SESSIONS[sid])
        view = self.client.get(f'/api/sessions/{sid}/commands').json()
        self.assertTrue(view['enabled'], 'Frontend must submit revision and batch on the first external turn')
        response = self.advance(sid)
        self.assertEqual(response.status_code, 200, response.text)

    def test_external_chat_uses_current_committed_observation(self):
        from types import SimpleNamespace
        sid = self.create(); self.queue_all(sid); self.advance(sid)
        with patch.object(h, '_run_brain', return_value=SimpleNamespace(events=[], final_response='只读分析')) as run:
            response = self.client.post(f'/api/sessions/{sid}/chat', json={'message':'当前时间与实体位置？'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(run.call_args.kwargs['native_context']['session']['turn_count'], 1)
        self.assertIn('get_afsim_observation', run.call_args.args[0])
        self.assertIsNone(run.call_args.args[1], 'A fresh external observation must replace stale chat memory')

    def test_default_observation_exposes_force_counts_without_full_source_documents(self):
        from backend import afsim_state
        sid=self.create();s=main._SESSIONS[sid];u=s['war_state']['red_units'][0]
        u['personnel']={'committed':1500,'current':1400,'casualties':80,'noncombat_losses':20,'source':'演习估计'}
        u['historical_reference']={'id':'ref-1','name':'来源部队','context':'x'*10000,'sources':[{'full_document':'x'*10000}]}
        row=next(r for r in afsim_state.observation(s)['units'] if r['team']=='red')
        self.assertEqual(row['personnel']['current'],1400)
        self.assertEqual(row['personnel']['noncombat_losses'],20)
        self.assertNotIn('sources',row['historical_reference'])
        self.assertLessEqual(len(row['historical_reference']['context']),200)

    def test_external_review_is_read_only_and_uses_bounded_native_tools(self):
        from types import SimpleNamespace
        sid = self.create(); self.queue_all(sid); self.advance(sid)
        before = copy.deepcopy(main._SESSIONS[sid]['war_state'])
        with patch.object(h, '_run_brain', return_value=SimpleNamespace(events=[], final_response='运动有证据，其余未建模。')) as run:
            response = self.client.post(f'/api/sessions/{sid}/review')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(run.call_args.kwargs['native_context']['session']['war_state']['current_time'], before['current_time'])
        self.assertEqual(main._SESSIONS[sid]['war_state'], before)

    def test_afsim_failure_does_not_fall_back_to_narrative(self):
        sid = self.create(); self.executor.side_effect = RuntimeError('native execution failed')
        response = self.advance(sid)
        self.assertEqual(response.status_code, 502)
        self.assertIn('native execution failed', response.text)
        self.assertEqual(main._SESSIONS[sid]['turn_count'], 0)

    def compare(self, sid):
        view = self.client.get(f'/api/sessions/{sid}/commands').json()
        return self.client.post(f'/api/sessions/{sid}/commands/compare', json={
            'expected_turn': view['turn'], 'revision': view['revision'], 'world_version': view['world_version'],
            'turn': 1, 'orders': [{'unit_id': view['units'][0]['id'], 'action': 'hold', 'duration': 'next'}]})

    def test_afsim_comparison_is_read_only_and_does_not_call_model(self):
        sid = self.create(); self.queue_all(sid)
        self.assertEqual(self.advance(sid).status_code, 200)
        session = main._SESSIONS[sid]; before = copy.deepcopy(session)
        response = self.compare(sid)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['mode'], 'controlled_afsim')
        self.assertTrue(response.json()['read_only'])
        self.assertEqual(session, before)
        self.planner.assert_not_called()

    def test_afsim_comparison_failure_is_reported_without_mutating_world(self):
        sid = self.create(); self.queue_all(sid); self.advance(sid)
        session = main._SESSIONS[sid]; before = copy.deepcopy(session)
        self.executor.side_effect = RuntimeError('counterfactual process failed')
        response = self.compare(sid)
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(session, before)

    def test_cancelled_external_turn_preserves_queue_and_world(self):
        sid = self.create(); self.queue_all(sid)
        session = main._SESSIONS[sid]; before = copy.deepcopy(session['war_state'])
        queue = copy.deepcopy(session['command_state'])
        def cancel(*args, **kwargs):
            session['cancel_requested'] = True
            return self.execute(*args, **kwargs)
        self.executor.side_effect = cancel
        response = self.advance(sid)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(session['war_state'], before)
        self.assertEqual(session['command_state'], queue)
        self.assertEqual(session['turn_count'], 0)

    def test_same_command_batch_cannot_advance_twice(self):
        sid = self.create(); self.queue_all(sid)
        self.assertEqual(self.advance(sid).status_code, 200)
        calls = self.executor.call_count
        response = self.advance(sid)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(main._SESSIONS[sid]['turn_count'], 1)
        self.assertEqual(self.executor.call_count, calls)

    def test_implicit_holds_are_valid_external_counterfactual_evidence(self):
        sid = self.create(); self.assertEqual(self.advance(sid).status_code, 200)
        response = self.compare(sid)
        self.assertEqual(response.status_code, 200, response.text)

    def test_external_world_cannot_use_narrative_model_state_counterfactual(self):
        sid = self.create(); self.advance(sid)
        response = self.client.post(f'/api/sessions/{sid}/counterfactual', json={
            'turn':1,'mode':'model','instruction':'前往另一个位置'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('AFSIM', response.text)

    def test_unit_agent_receives_current_round_intent_and_rules(self):
        from types import SimpleNamespace
        import json
        sid = self.create(); view = self.client.get(f'/api/sessions/{sid}/commands').json()
        unit_id = view['units'][0]['id']
        response = self.client.put(f'/api/sessions/{sid}/commands',json={
            'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version'],
            'orders':[],'unit_agents':[unit_id]})
        self.assertEqual(response.status_code,200,response.text)

        def run(binding, prompt, observer, **kwargs):
            self.assertIn('ROUND-INTENT-TEST',prompt)
            identity = f"gentactix-unit-{kwargs['namespace']}-test"
            return SimpleNamespace(final_response=json.dumps({'order':{'unit_id':unit_id,'action':'hold'}})), {'session_id':identity}
        with patch.object(h,'unit_run',side_effect=run):
            view=self.client.get(f'/api/sessions/{sid}/commands').json()
            response=self.client.post(f'/api/sessions/{sid}/next',json={
                'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version'],
                'batch_id':'unit-intent','instruction':'ROUND-INTENT-TEST'})
        self.assertEqual(response.status_code,200,response.text)

    def test_fixed_rule_counterfactual_executes_external_engine_before_returning(self):
        sid=self.create(mission_id='AJ15-local-v1',time_step='30分钟')
        self.queue_all(sid); self.advance(sid)
        before=copy.deepcopy(main._SESSIONS[sid]['war_state']); calls=self.executor.call_count
        response=self.client.post(f'/api/sessions/{sid}/counterfactual',json={'turn':1,'mode':'mission','orders':[]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['mode'],'controlled_afsim')
        self.assertEqual(self.executor.call_count,calls+1)
        self.assertEqual(main._SESSIONS[sid]['war_state'],before)


if __name__ == '__main__':
    unittest.main()
