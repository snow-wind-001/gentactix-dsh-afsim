"""Strict source replay never calls a generative or combat executor."""
import copy
import unittest
import os
import tempfile
from unittest.mock import patch

from gentactix import adjudication_lib, history_replay
from backend import afsim_history


class HistoricalReplayTests(unittest.TestCase):
    def setUp(self):
        self.battle = '红军长征-湘江战役-1934.11.25至1934.12.01'

    def test_every_battle_has_sourced_frames(self):
        for battle in adjudication_lib.list_battles():
            pack = history_replay.dataset(battle)
            self.assertTrue(pack['events'], battle)
            for event in pack['events']:
                self.assertTrue(event['sources'], battle)
                self.assertTrue(event['precision'])

    def test_unknown_deployment_and_losses_stay_unknown(self):
        world = history_replay.frame(self.battle, 0)
        self.assertEqual(world['red_units'], [])
        self.assertEqual(world['blue_units'], [])
        self.assertNotIn('simulation_clock', world)
        self.assertNotIn('mission', world)
        self.assertNotIn('personnel', world)
        self.assertIn('未载钟点', world['current_time'])

    def test_restore_rejects_edited_event_and_synthetic_units(self):
        world = history_replay.frame(self.battle, 0)
        history_replay.validate(world)
        for edit in ('event', 'unit', 'cursor', 'extra'):
            value = copy.deepcopy(world)
            if edit == 'event': value['history_replay']['event']['event'] = '模型改写'
            if edit == 'unit': value['red_units'] = [{'name': '虚构兵团'}]
            if edit == 'cursor': value['history_replay']['cursor'] = 999
            if edit == 'extra': value['personnel'] = {'casualties': 0}
            with self.assertRaises(ValueError): history_replay.validate(value)

    def test_scene_is_static_source_replay_without_weapons(self):
        world = history_replay.frame(self.battle, 0)
        scene = afsim_history.compile_scene(world)
        self.assertIn('GTXHISTORY|', scene['script'])
        self.assertNotIn('WSF_GROUND_MOVER', scene['script'])
        self.assertNotIn('native_model', scene)
        self.assertEqual(scene['seconds'], 1)

    def test_native_failure_or_cancel_cannot_advance_original(self):
        world = history_replay.frame(self.battle, 0)
        session = {'battle_choice': self.battle, 'war_state': world}
        saved = copy.deepcopy(session)
        with patch('backend.afsim_world.run_scene', side_effect=RuntimeError('AFSIM unavailable')):
            with self.assertRaises(RuntimeError): afsim_history.execute(session, 1)
        self.assertEqual(session, saved)

    def test_open_prompts_do_not_force_historical_outcome(self):
        from gentactix import prompts
        self.assertIn('允许偏离历史', prompts.mode_instruction('open'))
        self.assertNotIn('未载细节标明推演', prompts.mode_instruction('replay'))


class ReplayApiTests(unittest.TestCase):
    def setUp(self):
        from backend import main, harness_engine as h
        from fastapi.testclient import TestClient
        self.main, self.h = main, h
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': self.temp.name + '/sessions',
            'GENTACTIX_TRACE_DIR': self.temp.name + '/traces'}),
            patch('tools.afsim.launch.status', return_value={'available': True}),
            patch.object(h, 'enable_afsim_runtime'), patch.object(h, 'NATIVE_RUNTIME', True),
            patch.object(h, 'get_ai_response', side_effect=AssertionError('Planner must not run')),
            patch.object(h, 'get_ai_response_with_retry', side_effect=AssertionError('Generator must not run')),
            patch('backend.afsim_world.run_scene', side_effect=self.execute)]
        for p in self.patches: p.start()
        main._SESSIONS.clear()
        self.client = TestClient(main.app)
        self.request = {'scenario': '严格湘江史料回放', 'battle': '红军长征-湘江战役-1934.11.25至1934.12.01',
                        'execution_backend': 'afsim', 'simulation_mode': 'replay', 'time_step': '30分钟'}

    def tearDown(self):
        self.main._SESSIONS.clear()
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    def execute(self, session, scene, *_args):
        return {}, {'source': 'test_fixture', 'history_token': scene['history_token'],
                    'status': 'completed', 'returncode': 0, 'entity_count': len(scene['entities'])}

    def create(self):
        response = self.client.post('/api/sessions', json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['session_id']

    def test_historical_only_native_route_and_source_frames(self):
        self.assertEqual(self.client.post('/api/sessions', json={**self.request, 'execution_backend': 'narrative'}).status_code, 422)
        sid = self.create()
        url = '/api/sessions/' + sid
        result = self.client.post(url + '/init')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['war_state']['red_units'], [])
        self.assertIn('严格史料事件重现', result.json()['scenario'])
        total = result.json()['war_state']['history_replay']['total']
        for i in range(total - 1):
            result = self.client.post(url + '/next', json={'expected_turn': i})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['war_state']['history_replay']['cursor'], i + 1)
        result = self.client.post(url + '/next', json={'expected_turn': total - 1})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.main._SESSIONS[sid]['turn_count'], total - 1)

    def test_commands_stale_clicks_and_counterfactual_cannot_rewrite_history(self):
        sid = self.create(); url = '/api/sessions/' + sid
        self.assertEqual(self.client.post(url + '/init').status_code, 200)
        saved = copy.deepcopy(self.main._SESSIONS[sid]['war_state'])
        self.assertEqual(self.client.post(url + '/next', json={'expected_turn': 0, 'instruction': '改为全歼敌军'}).status_code, 422)
        self.assertEqual(self.client.post(url + '/next', json={'expected_turn': 1}).status_code, 409)
        self.assertEqual(self.client.post(url + '/counterfactual', json={'turn': 1}).status_code, 409)
        self.assertEqual(self.main._SESSIONS[sid]['war_state'], saved)
        self.assertEqual(self.client.post(url + '/next', json={'expected_turn': 0}).status_code, 200)
        self.assertEqual(self.client.post(url + '/next', json={'expected_turn': 0}).status_code, 409)

    def test_native_failure_is_atomic(self):
        sid = self.create(); url = '/api/sessions/' + sid
        self.assertEqual(self.client.post(url + '/init').status_code, 200)
        saved = copy.deepcopy(self.main._SESSIONS[sid]['war_state'])
        with patch('backend.afsim_world.run_scene', side_effect=RuntimeError('failed')):
            self.assertEqual(self.client.post(url + '/next', json={'expected_turn': 0}).status_code, 502)
        self.assertEqual(self.main._SESSIONS[sid]['war_state'], saved)


if __name__ == '__main__':
    unittest.main()
