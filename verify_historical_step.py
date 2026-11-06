"""Launch selection, native skill constraints and frozen clock must agree."""
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.qa.historical_operational_fixture import BATTLE, inputs


class HistoricalStepTests(unittest.TestCase):
    def setUp(self):
        from backend import main, scenario_builder
        from fastapi.testclient import TestClient
        self.builder = scenario_builder
        self.main = main
        self.client = TestClient(main.app)
        self.snapshot, self.params = inputs()
        self.payload = {'battle': BATTLE, 'phase_id': 'taierzhuang',
                        'time_step': '15分钟', 'execution_backend': 'narrative','termination_mode':'deadline'}

    def native(self, prompt, _, **kwargs):
        context = kwargs['native_context']
        view = self.builder.execute_tool(context, {'tool': 'get_scenario_basis'})
        self.assertEqual(view['time_step_constraint']['seconds'], 900)
        self.assertEqual(view['configuration_template']['clock']['time_step'], '15分钟')
        bad = self.builder.execute_tool(context, {'tool': 'validate_scenario_configuration',
            'args': {'configuration': self.params}})
        self.assertFalse(bad['valid'])
        self.assertIn('回合跨度', bad['error'])
        config = copy.deepcopy(self.params)
        config['clock']['time_step'] = '0.25小时'
        config['goal']['team']=view['configuration_template']['goal']['team']
        config['goal']['termination_mode']=view['configuration_template']['goal']['termination_mode']
        good = self.builder.execute_tool(context, {'tool': 'validate_scenario_configuration',
            'args': {'configuration': config}})
        self.assertTrue(good['valid'], good)
        kwargs['observer'].runs.append({'events': [{'type': 'tool/call', 'name': tool}
            for tool in ('read_scenario_skill', 'get_scenario_basis', 'validate_scenario_configuration')]})
        return SimpleNamespace(final_response=json.dumps({'configuration': config}))

    def test_native_tool_and_final_draft_preserve_selected_duration(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': folder+'/sessions'}), \
             patch.object(self.builder.h, '_run_brain', side_effect=self.native):
            response = self.client.post('/api/historical-scenarios/build', json=self.payload)
            self.assertEqual(response.status_code, 200, response.text)
            draft = response.json()
            self.assertEqual(draft['parameters']['clock']['time_step'], '0.25小时')
            self.assertEqual(draft['preview_world']['mission']['definition']['time_step'], '0.25小时')

    def test_invalid_step_rejected_before_any_native_request(self):
        with patch.object(self.builder.h, '_run_brain', side_effect=AssertionError('No request')):
            for label in ('未知', '0分钟', 'NaN小时'):
                response = self.client.post('/api/historical-scenarios/build', json={**self.payload, 'time_step': label})
                self.assertEqual(response.status_code, 422, response.text)

    def test_step_larger_than_local_window_is_rejected_before_model_generation(self):
        payload = {'battle': '抗日战争-衡阳保卫战-1944.06至1944.08.08',
                   'phase_id': 'zhangjiashan_june28', 'time_step': '1天','termination_mode':'deadline'}
        with patch.object(self.builder.h, '_run_brain', side_effect=AssertionError('No model for infeasible step')) as model:
            for engine in ('afsim', 'narrative'):
                response = self.client.post('/api/historical-scenarios/build', json={**payload, 'execution_backend': engine})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('计算窗口', response.json()['detail'])
            model.assert_not_called()

    def test_local_window_step_check_keeps_the_selected_step_and_allows_exact_fit(self):
        battle = '抗日战争-车桥战役-1944.03.05至1944.03.06'
        for label, seconds in [('15分钟', 900), ('4小时', 14400)]:
            basis = self.builder.historical_basis(battle, 'cheqiao_mar5', time_step=label)
            self.assertTrue(basis['ready'])
            self.assertEqual(basis['time_step_constraint']['seconds'], seconds)
            self.assertEqual(basis['configuration_template']['clock']['time_step'], label)
        with self.assertRaisesRegex(ValueError, '计算窗口'):
            self.builder.historical_basis(battle, 'cheqiao_mar5', time_step='6小时')

    def test_model_cannot_validate_one_clock_and_return_another(self):
        def forged(prompt, session, **kwargs):
            self.native(prompt, session, **kwargs)
            return SimpleNamespace(final_response=json.dumps({'configuration': self.params}))
        with patch.object(self.builder.h, '_run_brain', side_effect=forged), \
             patch.object(self.builder, 'stage_historical', side_effect=AssertionError('No wrong-clock draft')):
            response = self.client.post('/api/historical-scenarios/build', json=self.payload)
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn('回合跨度', response.json()['detail'])

    def test_staged_global_clock_cannot_override_selection_or_commit_invalid_revision(self):
        from backend import scenario_assembly
        basis = self.builder.historical_basis(BATTLE, 'taierzhuang', time_step='15分钟')
        assembly = scenario_assembly.create(basis)
        self.addCleanup(scenario_assembly.close, assembly.id)
        view = assembly.tool('globals', 'get_scenario_basis', {})
        self.assertEqual(view['time_step_constraint']['seconds'], 900)
        old = copy.deepcopy(assembly.configuration)
        patch_ = {k: v for k, v in self.params.items() if k not in ('actors', 'format', 'phase_id')}
        bad = assembly.tool('globals', 'update_scenario_configuration', {'revision': 0, 'patch': patch_})
        self.assertFalse(bad['updated'])
        self.assertIn('回合跨度', bad['error'])
        self.assertEqual(assembly.configuration, old)
        self.assertEqual(assembly.revision, 0)
        patch_['clock']['time_step'] = '15分'
        self.assertTrue(assembly.tool('globals', 'update_scenario_configuration', {'revision': 0, 'patch': patch_})['updated'])

    def test_selected_clock_validation_handles_malformed_native_tool_arguments(self):
        basis = self.builder.historical_basis(BATTLE, 'taierzhuang', time_step='15分钟')
        context = {'scenario_composer': {'kind': 'historical_operation', 'initial': self.snapshot, 'basis': basis}}
        for config in (None, [], ['invalid'], {'clock': []}, {'clock': '15分钟'}, {'clock': {}}):
            result = self.builder.execute_tool(context, {'tool': 'validate_scenario_configuration', 'args': {'configuration': config}})
            self.assertFalse(result['valid'])
            self.assertIn('回合跨度', result['error'])

    def test_creation_rejects_conflicting_explicit_clock_but_accepts_equivalent_or_legacy(self):
        config = copy.deepcopy(self.params); config['clock']['time_step'] = '15分钟'
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': folder+'/sessions'}):
            draft = self.builder.stage_historical(self.snapshot, config,
                construction={'source': 'dsh_native_skill'}, execution_backend='narrative')
            payload = {'scenario': 'selected-clock regression', 'battle': BATTLE, 'product_mode': 'historical',
                'historical_parameters': draft['parameters'], 'scenario_draft_id': draft['id'], 'execution_backend': 'narrative'}
            bad = self.client.post('/api/sessions', json={**payload, 'time_step': '30分钟'})
            self.assertEqual(bad.status_code, 422, bad.text)
            self.assertIn('回合跨度', bad.json()['detail'])
            for extra in ({'time_step': '0.25小时'}, {}):
                response = self.client.post('/api/sessions', json={**payload, **extra})
                self.assertEqual(response.status_code, 200, response.text)
                sid = response.json()['session_id']
                try:
                    self.assertEqual(self.main._SESSIONS[sid]['time_step'], '15分钟')
                finally:
                    self.main._SESSIONS.pop(sid, None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
