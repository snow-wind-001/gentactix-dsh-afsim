"""Read-only historical narration is prose; quoted sources cannot corrupt frames."""
import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class HistoryCommentaryTests(unittest.TestCase):
    def setUp(self):
        from backend import main,harness_engine
        from fastapi.testclient import TestClient
        self.main,self.h=main,harness_engine;self.root=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':self.root.name+'/sessions','GENTACTIX_TRACE_DIR':self.root.name+'/traces'});self.env.start()
        self.run=patch.object(harness_engine,'_run_brain',return_value=SimpleNamespace(final_response='来源记载“形成包围”，不是"全师已歼"。',events=[]));self.model=self.run.start()
        self.json=patch.object(harness_engine,'get_ai_response',side_effect=AssertionError('Narration must not use battle JSON parser'));self.json.start()
        self.client=TestClient(main.app)
        r=self.client.post('/api/sessions',json={'scenario':'来源讲解引号回归','battle':'抗日战争-万家岭战役-1938.09下旬至1938.10',
            'product_mode':'analysis','simulation_mode':'replay','execution_backend':'narrative','historical_source_version':'1.1.0','persist_roles':False})
        self.assertEqual(r.status_code,200,r.text);self.sid=r.json()['session_id'];self.url='/api/sessions/'+self.sid

    def tearDown(self):
        self.main._SESSIONS.pop(self.sid,None);self.json.stop();self.run.stop();self.env.stop();self.root.cleanup()

    def test_ordinary_quoted_prose_commits_exact_source_frame_without_json_parse(self):
        from gentactix import history_replay
        r=self.client.post(self.url+'/init');self.assertEqual(r.status_code,200,r.text)
        s=self.main._SESSIONS[self.sid]
        self.assertEqual(s['history_commentary']['explanation'],'来源记载“形成包围”，不是"全师已歼"。')
        self.assertEqual(s['war_state'],history_replay.frame_for_session(s,0))
        self.assertIn('只读历史回溯分析员',self.model.call_args.args[0])
        self.assertNotIn('source_snapshot',self.model.call_args.args[0])
        self.assertEqual(self.model.call_args.kwargs['role'],'chat')

    def test_invalid_or_failed_narration_never_advances_or_rewrites_saved_frame(self):
        from backend import session_store
        self.assertEqual(self.client.post(self.url+'/init').status_code,200)
        s=self.main._SESSIONS[self.sid];before=copy.deepcopy(session_store.serializable(s))
        for value in ('',None,{'updated_state':{'red_units':[{'name':'invented'}]}}):
            self.model.return_value=SimpleNamespace(final_response=value,events=[])
            r=self.client.post(self.url+'/next',json={'expected_turn':0})
            self.assertEqual(r.status_code,409,r.text)
            self.assertEqual(s['war_state'],before['war_state']);self.assertEqual(s['turn_count'],0)
            self.assertEqual(s['trajectory'],before['trajectory'])
        self.model.side_effect=RuntimeError('harness unfinished: max-tokens')
        r=self.client.post(self.url+'/next',json={'expected_turn':0});self.assertEqual(r.status_code,502,r.text)
        loaded,errors=session_store.load_all();self.assertFalse(errors);self.assertEqual(loaded[self.sid]['war_state'],before['war_state'])

    def test_cancelled_narration_retains_original_frame_then_normal_retry_commits_once(self):
        self.assertEqual(self.client.post(self.url+'/init').status_code,200)
        s=self.main._SESSIONS[self.sid];before=copy.deepcopy(s['war_state'])
        def cancel(*args,**kwargs):
            s['cancel_requested']=True
            return SimpleNamespace(final_response='尚未提交的讲解',events=[])
        self.model.side_effect=cancel
        r=self.client.post(self.url+'/next',json={'expected_turn':0});self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(s['war_state'],before);self.assertEqual(s['turn_count'],0)
        self.model.side_effect=None;self.model.return_value=SimpleNamespace(final_response='按下一条来源事件继续讲解。',events=[])
        r=self.client.post(self.url+'/next',json={'expected_turn':0});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(s['turn_count'],1);self.assertEqual(len(s['trajectory']),2)

    def assert_source_call(self, world, role, role_id):
        call = self.model.call_args
        self.assertIn('只读历史回溯分析员', call.args[0])
        self.assertNotIn('依据最新态势', call.args[0])
        self.assertEqual(call.args[1], role_id)
        self.assertEqual(call.kwargs['role'], role)
        context = call.kwargs.get('native_context')
        self.assertIsNotNone(context, 'normal source operations must bind existing Native tools')
        self.assertEqual(context['session']['war_state'], world)
        self.assertEqual(context['session']['turn_count'], world['history_replay']['cursor'])
        self.assertNotIn('turn_preview', context)
        from backend import afsim_state
        observed = afsim_state.observation(copy.deepcopy(context['session']), {'limit': 1})
        self.assertEqual(observed['history_replay']['cursor'], world['history_replay']['cursor'])
        self.assertEqual(observed['history_replay']['dataset_hash'], world['history_replay']['dataset_hash'])
        self.assertTrue(all(not u['available'] and not u['actions'] for u in observed['units']))
        return context

    def test_normal_commentary_binds_target_frame_and_original_role(self):
        s = self.main._SESSIONS[self.sid]
        s['persist_roles'] = True
        for cursor, endpoint in ((0, '/init'), (1, '/next')):
            response = self.client.post(self.url + endpoint, json={} if not cursor else {'expected_turn': 0})
            self.assertEqual(response.status_code, 200, response.text)
            self.assert_source_call(s['war_state'], 'chat', self.main._brain_role_id(s, 'chat'))
            self.assertEqual(s['war_state']['history_replay']['cursor'], cursor)

    def test_source_chat_uses_history_prompt_and_same_role_for_both_executors(self):
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        s = self.main._SESSIONS[self.sid]
        s['persist_roles'] = True
        before = copy.deepcopy(s['war_state'])
        trajectory = copy.deepcopy(s['trajectory'])
        for engine in ('narrative', 'afsim'):
            with self.subTest(engine=engine):
                s['execution_backend'] = engine
                response = self.client.post(self.url + '/chat', json={'message': '核对当前史料节点，不改世界。'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assert_source_call(before, 'chat', self.main._brain_role_id(s, 'chat'))
                self.assertEqual(s['war_state'], before)
                self.assertEqual(s['trajectory'], trajectory)

    def test_source_review_has_native_tools_and_preserves_strategist_role(self):
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        s = self.main._SESSIONS[self.sid]
        s['persist_roles'] = True
        before = copy.deepcopy(s['war_state'])
        for engine in ('narrative', 'afsim'):
            with self.subTest(engine=engine), patch.object(self.h, 'get_role_session'), \
                    patch.object(self.main, '_amnesia_prefix', return_value=''):
                s['execution_backend'] = engine
                response = self.client.post(self.url + '/review')
                self.assertEqual(response.status_code, 200, response.text)
                self.assert_source_call(before, 'strategist', self.main._brain_role_id(s, 'strategist'))
                self.assertEqual(s['war_state'], before)

    def test_reinitialize_uses_new_epoch_during_analysis_without_old_trajectory(self):
        s = self.main._SESSIONS[self.sid]
        s['persist_roles'] = True
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        self.assertEqual(self.client.post(self.url + '/next', json={'expected_turn': 0}).status_code, 200)
        previous_role = self.model.call_args.args[1]
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        context = self.assert_source_call(s['war_state'], 'chat', self.main._brain_role_id(s, 'chat'))
        self.assertEqual(context['session']['role_epoch'], 1)
        self.assertNotEqual(self.model.call_args.args[1], previous_role)
        self.assertEqual(context['session']['history'], [])
        self.assertEqual(context['session']['trajectory'], [])

    def test_source_context_cannot_read_another_frame(self):
        from backend import afsim_state
        from gentactix import history_replay
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        s = self.main._SESSIONS[self.sid]
        wrong = afsim_state.operation_context({**s, 'war_state': history_replay.frame_for_session(s, 1), 'turn_count': 1})
        self.model.reset_mock()
        for operation in ('chat', 'review'):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, '目标帧'):
                if operation == 'chat':
                    self.h.ask_xuanji([], s['war_state'], [], '核对', native_context=wrong)
                else:
                    self.h.get_strategic_review([], s['war_state'], native_context=wrong)
        self.model.assert_not_called()

    def test_prompt_explains_tool_lookup_and_rejects_unattributed_directions(self):
        from gentactix import history_replay
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        world = self.main._SESSIONS[self.sid]['war_state']
        prompt = history_replay.analysis_prompt(world, '这个位置在南偏东、敌军东进吗？', tools_available=True)
        for text in ('get_afsim_observation', 'retrieve_history', '方位', '行军方向', '分析推断', '未载'):
            self.assertIn(text, prompt)
        self.assertNotIn('source_snapshot', prompt)
        self.assertLess(len(prompt), 16000)

    def test_legacy_runtime_does_not_claim_native_tools_are_available(self):
        from backend import afsim_state
        self.assertEqual(self.client.post(self.url + '/init').status_code, 200)
        s = self.main._SESSIONS[self.sid]
        with patch.object(self.h, 'NATIVE_RUNTIME', False):
            self.h.ask_xuanji([], s['war_state'], [], '只读核对', native_context=afsim_state.operation_context(s))
        self.assertNotIn('本轮已提供只读工具', self.model.call_args.args[0])


class SourceToolPolicyTests(unittest.TestCase):
    def test_source_reference_ids_resolve_without_duplicate_rows_or_fake_deployment(self):
        from backend import afsim_state
        from gentactix import history_replay
        world = history_replay.frame_pinned(history_replay.pin(
            '红军长征-湘江战役-1934.11.25至1934.12.01', version='1.2.0'), 8)
        session = {'id': 'source-id-compatibility', 'war_state': world, 'turn_count': 8,
                   'time_step': '30分钟', 'history': [], 'trajectory': []}
        before = copy.deepcopy(session)
        full = afsim_state.observation(copy.deepcopy(session), {'limit': 2})
        first, second = full['units']
        requested = [first['historical_unit_id'], first['id'], second['historical_unit_id'], 'unknown-source-id']
        for offset, expected in ((0, first), (1, second)):
            observed = afsim_state.observation(copy.deepcopy(session), {'ids': requested, 'limit': 1, 'offset': offset})
            self.assertEqual(len(observed['units']), 1)
            self.assertEqual(observed['units'][0]['id'], expected['id'])
            self.assertEqual(observed['units'][0]['historical_unit_id'], expected['historical_unit_id'])
            self.assertEqual(observed['unknown_ids'], ['unknown-source-id'])
            self.assertEqual(observed['next_offset'], 1 if offset == 0 else None)
            self.assertIsNone(observed['units'][0]['position'])
            self.assertFalse(observed['units'][0]['available'])
            self.assertEqual(observed['units'][0]['actions'], [])
        self.assertEqual(session, before)

    def test_open_world_still_requires_registered_ids(self):
        from backend import afsim_state
        session = {'id': 'open-id-contract', 'time_step': '30分钟', 'turn_count': 0,
            'war_state': {'current_time': '1938-09-17 00:00', 'red_units': [{
                'name': '教学编组', 'historical_unit_id': 'source.ref', 'type': '步兵',
                'hp': 100, 'lat': 31.7, 'lng': 115.7}], 'blue_units': []}}
        observed = afsim_state.observation(copy.deepcopy(session), {'ids': ['source.ref']})
        self.assertEqual(observed['units'], [])
        self.assertEqual(observed['unknown_ids'], ['source.ref'])

    def test_native_runtime_only_exposes_source_readers_and_keeps_world_unchanged(self):
        from backend import harness_engine as h, runtime_bridge, main, afsim_state
        from gentactix import history_replay
        world = history_replay.frame('红军长征-湘江战役-1934.11.25至1934.12.01', 0)
        for engine in ('narrative', 'afsim'):
            for role in ('chat', 'strategist'):
                with self.subTest(engine=engine, role=role):
                    session = {'id': 'readonly-source-test', 'war_state': copy.deepcopy(world),
                        'turn_count': 0, 'execution_backend': engine, 'product_mode': 'analysis',
                        'simulation_mode': 'replay', 'history': [], 'trajectory': []}
                    before = copy.deepcopy(session)
                    sid = 'readonly-source-test-' + engine + '-' + role
                    def fake_run(role_id, prompt, **kwargs):
                        policy = h._run_policies[role_id]
                        self.assertEqual(set(policy['allowed_tools']), {
                            'get_afsim_observation', 'get_afsim_changes', 'get_observation', 'retrieve_history'})
                        context = runtime_bridge._contexts[role_id]
                        result = main._native_tool_dispatch(context, {'tool': 'get_afsim_observation', 'args': {'limit': 1}})
                        self.assertEqual(result['history_replay']['cursor'], 0)
                        return SimpleNamespace(final_response='来源核对完成。', finish_reason='completed', events=[])
                    with patch.object(h, 'run_role', side_effect=fake_run):
                        h._run_brain('只读来源核对', sid, role=role, native_context=afsim_state.operation_context(session))
                    self.assertEqual(session, before)
                    self.assertNotIn(sid, runtime_bridge._contexts)
                    self.assertNotIn(sid, h._run_policies)

    def test_normal_analysis_keeps_existing_dry_run_tools(self):
        from backend import harness_engine as h
        for engine in (False, True):
            self.assertIn('evaluate_action', h.role_policy('chat', tools=True, external=engine)['allowed_tools'])


if __name__=='__main__':unittest.main()
