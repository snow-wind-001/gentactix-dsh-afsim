"""Pinned historical identity must survive source revisions and runtime reloads."""
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gentactix import historical_initial as initial, history_replay as replay

WUHAN = '抗日战争-武汉会战-1938.06至1938.10'


class PinnedReplayTests(unittest.TestCase):
    def test_new_frame_contains_sourced_unit_identity_and_unknown_live_state(self):
        pinned = replay.pin(WUHAN)
        world = replay.frame_pinned(pinned, 0)
        self.assertEqual(world['history_replay']['version'], 'strict-history-2')
        self.assertEqual(len(world['red_units']) + len(world['blue_units']), 118)
        self.assertIn('第九战区司令部', [u['name'] for u in world['red_units']])
        self.assertTrue(replay.validate(world))
        for unit in world['red_units'] + world['blue_units']:
            self.assertIsNone(unit['lat'])
            self.assertIsNone(unit['personnel']['current'])
            self.assertIn('参战参考', unit['frame_evidence_status'])
            self.assertNotIn('hp', unit)

    def test_frozen_replay_and_advance_do_not_read_latest_sources(self):
        pinned = replay.pin(WUHAN)
        before = replay.frame_pinned(pinned, 0)
        session = {'battle_choice': WUHAN, 'source_replay_snapshot': pinned, 'war_state': before}
        with patch.object(replay, 'dataset', side_effect=AssertionError('No latest data')), \
             patch.object(initial, 'DATA_ROOT', initial.DATA_ROOT / 'unavailable'):
            self.assertTrue(replay.validate(before))
            after = replay.frame_for_session(session, 1)
            self.assertEqual(after['history_replay']['cursor'], 1)
            self.assertEqual(before['historical_initial'], after['historical_initial'])
            self.assertTrue(replay.validate(after))

    def test_frame_identity_binds_both_sources_and_historical_units(self):
        pinned = replay.pin(WUHAN)
        world = replay.frame_pinned(pinned, 0)
        for kind in ('name', 'parent', 'position', 'frame_event', 'source_snapshot'):
            value = copy.deepcopy(world)
            if kind == 'name': value['red_units'][0]['name'] = '教学替身'
            if kind == 'parent': value['red_units'][0]['parent_id'] = 'missing'
            if kind == 'position': value['red_units'][0]['lat'] = 30
            if kind == 'frame_event': value['history_replay']['event']['event'] = '不同的历史'
            if kind == 'source_snapshot': value['history_replay']['source_snapshot']['events'][0]['event'] = '不同的来源'
            with self.subTest(kind=kind), self.assertRaises(ValueError): replay.validate(value)

    def test_units_never_gain_live_counts_from_a_campaign_aggregate(self):
        pinned = replay.pin(WUHAN)
        fact = pinned['initial']['definition']['units'][0]['facts']['personnel']
        fact.update(value=3000, evidence=copy.deepcopy(pinned['initial']['definition']['units'][0]['evidence']))
        pinned['initial']['definition_hash'] = initial.digest(pinned['initial']['definition'])
        world = replay.frame_pinned(pinned, 1)
        self.assertIsNone(world['red_units'][0]['personnel']['current'])
        self.assertEqual(world['red_units'][0]['historical_facts']['personnel']['value'], 3000)

    def test_bounded_commentary_excludes_full_definition_and_source_history(self):
        world = replay.frame_pinned(replay.pin(WUHAN), 0)
        observation = replay.observation(world, limit=8)
        text = json.dumps(observation, ensure_ascii=False)
        self.assertEqual(observation['roster_total'], 118)
        self.assertLessEqual(len(observation['units']), 8)
        self.assertNotIn('definition', text)
        self.assertNotIn('source_snapshot', text)
        self.assertLess(len(text), 12000)
        self.assertTrue(observation['readonly'])

    def test_legacy_frames_keep_the_original_contract(self):
        world = replay.frame(WUHAN, 0)
        self.assertEqual(world['red_units'], [])
        self.assertEqual(world['history_replay']['version'], 'strict-history-1')
        self.assertTrue(replay.validate(world))

    def test_dsh_chat_and_review_do_not_send_frozen_archives_or_trust_warm_memory(self):
        from backend import harness_engine as h
        world = replay.frame_pinned(replay.pin(WUHAN), 1)
        result = SimpleNamespace(events=[], final_response='来源分析')
        with patch.object(h, '_run_brain', return_value=result) as run, \
             patch.object(h, '_role_is_warm', return_value=True):
            h.ask_xuanji(['UNBOUNDED_HISTORY' * 5000], world, [], '当前节点是什么？', role_id='warm-role')
            prompt = run.call_args.args[0]
            self.assertIn(world['history_replay']['event']['event'], prompt)
            self.assertNotIn('UNBOUNDED_HISTORY', prompt)
            self.assertNotIn('source_snapshot', prompt)
            self.assertNotIn('definition', prompt)
            self.assertLess(len(prompt), 13000)
            h.get_strategic_review(['UNBOUNDED_HISTORY' * 5000], world)
            prompt = run.call_args.args[0]
            self.assertNotIn('UNBOUNDED_HISTORY', prompt)
            self.assertNotIn('source_snapshot', prompt)
            self.assertLess(len(prompt), 13000)


class HistoricalInitialApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend import main, harness_engine
        self.main, self.h = main, harness_engine
        self.folder = tempfile.TemporaryDirectory()
        self.patches = [patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': self.folder.name + '/sessions',
            'GENTACTIX_TRACE_DIR': self.folder.name + '/traces'}),
            patch.object(self.h, 'ask_xuanji', return_value=('', '依据给定来源讲解，不补写未知。'))]
        for handle in self.patches: handle.start()
        self.client = TestClient(main.app)
        self.created = []

    def tearDown(self):
        for sid in self.created: self.main._SESSIONS.pop(sid, None)
        for handle in reversed(self.patches): handle.stop()
        self.folder.cleanup()

    def create(self, engine='narrative'):
        response = self.client.post('/api/sessions', json={'scenario': '真实番号回溯', 'battle': WUHAN,
            'product_mode': 'analysis', 'simulation_mode': 'replay', 'execution_backend': engine, 'persist_roles': False})
        self.assertEqual(response.status_code, 200, response.text)
        sid = response.json()['session_id']; self.created.append(sid)
        return sid

    def test_preview_is_readonly_and_reports_unprofiled_battles(self):
        before = len(self.main._SESSIONS)
        response = self.client.get('/api/historical-initial', params={'battle': WUHAN})
        self.assertEqual(response.status_code, 200, response.text)
        value = response.json()
        self.assertEqual(value['status'], 'partial')
        self.assertEqual(value['readiness']['roster_count'], 118)
        self.assertFalse(value['readiness']['ready_for_process_simulation'])
        self.assertEqual(len(self.main._SESSIONS), before)
        response = self.client.get('/api/historical-initial', params={'battle': '长平之战'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'partial')
        self.assertIsNotNone(response.json()['initial'])
        self.assertFalse(response.json()['readiness']['ready_for_process_simulation'])
        self.assertEqual(self.client.get('/api/historical-initial', params={'battle': 'unknown'}).status_code, 404)

    def test_create_pins_profile_then_init_advance_and_restore_are_self_contained(self):
        from backend import session_store
        sid = self.create(); url = '/api/sessions/' + sid
        with patch.object(replay, 'dataset', side_effect=AssertionError('Do not reload source')), \
             patch.object(initial, 'DATA_ROOT', initial.DATA_ROOT / 'unavailable'):
            response = self.client.post(url + '/init')
            self.assertEqual(response.status_code, 200, response.text)
            world = response.json()['war_state']
            self.assertEqual(len(world['red_units']) + len(world['blue_units']), 118)
            response = self.client.post(url + '/next', json={'expected_turn': 0})
            self.assertEqual(response.status_code, 200, response.text)
            loaded, errors = session_store.load_all()
            self.assertFalse(errors)
            self.assertEqual(loaded[sid]['war_state'], response.json()['war_state'])
            self.assertEqual(loaded[sid]['source_replay_snapshot'], self.main._SESSIONS[sid]['source_replay_snapshot'])

    def test_afsim_receipt_distinguishes_geographic_entities_and_roster_records(self):
        from backend import afsim_history
        pinned = replay.pin(WUHAN)
        def run(_session, scene, *_args):
            return {}, {'history_token': scene['history_token'], 'entity_count': len(scene['entities'])}
        with patch('backend.afsim_world.run_scene', side_effect=run):
            world = afsim_history.execute({'battle_choice': WUHAN, 'source_replay_snapshot': pinned}, 0)
        receipt = world['afsim']
        self.assertEqual(receipt['historical_roster_count'], 118)
        self.assertEqual(receipt['combat_entity_count'], 0)
        self.assertEqual(receipt['geographic_reference_count'], receipt['entity_count'])
        self.assertFalse(receipt['battlefield_initialized'])

    def test_native_observation_has_no_command_capabilities_for_roster_reference(self):
        from backend import afsim_state
        world = replay.frame_pinned(replay.pin(WUHAN), 0)
        session = {'id': 'abcdef123456', 'war_state': world, 'turn_count': 0, 'time_step': '1天',
                   'simulation_mode': 'replay', 'execution_backend': 'afsim'}
        observation = afsim_state.observation(session, {'limit': 8})
        self.assertEqual(observation['history_replay']['roster_total'], 118)
        for unit in observation['units']:
            self.assertEqual(unit['actions'], [])
            self.assertFalse(unit['available'])
        self.assertNotIn('source_snapshot', json.dumps(observation, ensure_ascii=False))
        self.assertNotIn('historical_facts', json.dumps(observation, ensure_ascii=False))

    def test_import_and_source_bindings_cannot_be_swapped_between_sessions(self):
        from backend import session_store
        sid = self.create(); path = '/api/sessions/' + sid
        self.assertEqual(self.client.post(path + '/init').status_code, 200)
        session = session_store.serializable(self.main._SESSIONS[sid])
        other = replay.pin('抗日战争-徐州会战总览-1938.01至1938.05')
        session['source_replay_snapshot'] = other
        with self.assertRaises(ValueError): session_store.validate(session)
        session = session_store.serializable(self.main._SESSIONS[sid])
        session.pop('source_replay_snapshot')
        with self.assertRaises(ValueError): session_store.validate(session)

    def test_failed_source_step_preserves_roster_and_source_snapshot(self):
        sid = self.create(); path = '/api/sessions/' + sid
        self.assertEqual(self.client.post(path + '/init').status_code, 200)
        session = self.main._SESSIONS[sid]
        before = copy.deepcopy(session['war_state'])
        snapshot = copy.deepcopy(session['source_replay_snapshot'])
        with patch.object(self.h, 'ask_xuanji', side_effect=RuntimeError('model unavailable')):
            response = self.client.post(path + '/next', json={'expected_turn': 0})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(session['war_state'], before)
        self.assertEqual(session['source_replay_snapshot'], snapshot)
        self.assertEqual(session['turn_count'], 0)

    def test_user_cancel_during_explanation_is_a_conflict_and_never_commits(self):
        sid = self.create(); path = '/api/sessions/' + sid
        self.assertEqual(self.client.post(path + '/init').status_code, 200)
        session = self.main._SESSIONS[sid]
        before = copy.deepcopy(session['war_state'])
        def cancel(*_args, **_kwargs):
            session['cancel_requested'] = True
            return '', '取消后的结果不应提交'
        with patch.object(self.h, 'ask_xuanji', side_effect=cancel):
            response = self.client.post(path + '/next', json={'expected_turn': 0})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(session['war_state'], before)
        self.assertEqual(session['turn_count'], 0)


if __name__ == '__main__': unittest.main()
