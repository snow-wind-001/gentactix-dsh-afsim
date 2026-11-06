"""Explicitly revise a failed Native configuration without reopening its final stage."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import scenario_assembly as assembly, scenario_builder as builder
from backend import scenario_checkpoints as checkpoints
from gentactix import missions, scenario_constraints
from tools.qa.historical_operational_fixture import BATTLE
from verify_personnel_rations import parameters


class FailedConfigurationRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(builder, 'directory', return_value=Path(self.tmp.name)).start()
        self.snapshot, self.params = parameters()
        self.basis = builder.historical_basis(BATTLE, 'taierzhuang', time_step=self.params['clock']['time_step'])
        self.params['goal']['team'] = self.basis['configuration_template']['goal']['team']
        for actor in self.params['actors'].values():
            actor['formation'].setdefault('motorized', True)
        self.identity = next(iter(self.params['actors']))
        assembly.prepare_required_models(self.basis, ['personnel-rations-1'])
        scenario_constraints.prepare(self.basis, [
            {'path': ['actors', self.identity, 'personnel'],
             'value': self.params['actors'][self.identity]['personnel']}])
        draft = assembly.create(self.basis)
        self.addCleanup(assembly.close, draft.id)
        result = draft.tool('globals', 'update_scenario_configuration', {
            'revision': draft.revision,
            'patch': {k: v for k, v in self.params.items() if k not in ('format', 'phase_id', 'actors')}})
        self.assertTrue(result['updated'], result)
        for part in draft.parts:
            result = draft.tool(part, 'update_scenario_configuration', {
                'revision': draft.revision,
                'patch': {'actors': {i: self.params['actors'][i] for i in draft.assigned(part)}}})
            self.assertTrue(result['updated'], result)
        work = checkpoints.new_work('QA: 保留原生成过程，显式修订初粮', 'narrative')
        sid = 'gentactix-unit-scenario-' + draft.id + '-parent'
        work['bindings'][sid] = {'session_id': sid}
        work['coordinator'] = sid
        work['stages'] = [{**row, 'session_id': sid} for row in draft.audit]
        work.update(status='interrupted', failed_part='final', last_error='QA: 初粮携行容量超载')
        self.record = checkpoints.save(draft, work)
        assembly.close(draft.id)
        # Explicit legacy fixture: the previous validator accepted this write;
        # today's restore must still reject it. This is not a production bypass.
        state = self.record['state']
        state['configuration']['actors'][self.identity]['logistics']['food'] = 25
        digest = missions.digest(state['configuration'])
        state['audit'][-1]['configuration_hash'] = digest
        self.record['work']['stages'][-1]['configuration_hash'] = digest
        self.persist()
        self.path = Path(self.tmp.name) / (draft.id + '.json')
        self.original = (self.path.read_bytes(), self.path.stat().st_mtime_ns)
        self.url = '/api/historical-scenarios/assemblies/' + draft.id + '/revision'
        app = FastAPI()
        app.include_router(builder.build_router(lambda fn: fn))
        self.client = TestClient(app)

    def persist(self):
        self.record.pop('checkpoint_hash', None)
        self.record['checkpoint_hash'] = missions.digest(self.record)
        builder._save_draft(self.record, None)

    def assert_original(self):
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), self.original)

    def request(self, params=None, **changes):
        payload = dict(parent_draft_id=self.record['id'], parameters=params or self.params,
                       required_models=['personnel-rations-1'], execution_backend='narrative')
        return self.client.post('/api/historical-scenarios/validate', json={**payload, **changes})

    def test_existing_resume_stays_strict_but_readonly_revision_exposes_unvalidated_inputs(self):
        with self.assertRaisesRegex(ValueError, '携行容量'):
            checkpoints.restore(self.record['id'])
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertTrue(data['requires_validation'])
        self.assertEqual(data['parameters'], self.record['state']['configuration'])
        self.assertEqual(data['checkpoint_hash'], self.record['checkpoint_hash'])
        self.assertIn('携行容量', data['validation_error'])
        self.assertEqual(data['food_loading_errors'][0]['unit'], self.identity)
        self.assertEqual(data['food_loading_errors'][0]['capacity_work'], 24)
        self.assertNotIn('preview_world', data)
        self.assertNotIn('runs', data)
        self.assert_original()

    def test_invalid_revision_is_rejected_without_new_draft_or_original_changes(self):
        before = sorted(Path(self.tmp.name).glob('*.json'))
        result = self.request(self.record['state']['configuration'])
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('携行容量', result.text)
        self.assertEqual(sorted(Path(self.tmp.name).glob('*.json')), before)
        self.assert_original()

    def test_corrected_revision_uses_existing_validator_creates_new_draft_and_keeps_native_provenance(self):
        with patch.object(builder.h, 'unit_run') as model:
            result = self.request()
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertNotEqual(data['id'], self.record['id'])
        self.assertEqual(data['parent_id'], self.record['id'])
        self.assertEqual(data['initial'], self.basis['initial'])
        self.assertEqual(data['parameters']['actors'], self.params['actors'])
        self.assertTrue(data['construction']['manual_revision'])
        self.assertEqual(data['construction']['revision_base']['checkpoint_hash'], self.record['checkpoint_hash'])
        self.assertEqual(data['construction']['stages'], self.record['work']['stages'])
        self.assertNotIn('assembly_checkpoint_id', data['construction'])
        model.assert_not_called()
        self.assert_original()

    def test_revision_keeps_original_fixed_inputs_and_required_models(self):
        changed = copy.deepcopy(self.params)
        changed['actors'][self.identity]['personnel'] += 1
        result = self.request(changed)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('固定', result.text)
        result = self.request(required_models=[])
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('模型', result.text)
        result = self.request(fixed_parameters=[])
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('固定', result.text)
        self.assert_original()

    def test_revision_cannot_switch_clock_scope_or_engine(self):
        changed = copy.deepcopy(self.params)
        changed['phase_id'] = 'forged'
        self.assertEqual(self.request(changed).status_code, 422)
        changed = copy.deepcopy(self.params)
        changed['clock']['time_step'] = '1小时'
        result = self.request(changed)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('跨度', result.text)
        changed = copy.deepcopy(self.params)
        changed['campaign_scope'] = {'forged': True}
        result = self.request(changed)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('范围', result.text)
        result = self.request(execution_backend='afsim')
        self.assertEqual(result.status_code, 422, result.text)
        self.assert_original()

    def test_active_checkpoint_cannot_be_read_or_revised(self):
        self.record['work']['operation_id'] = 'qa-revision-active'
        self.persist()
        with patch.dict(builder._active, {'qa-revision-active': object()}):
            self.assertEqual(self.client.get(self.url).status_code, 422)
            self.assertEqual(self.request().status_code, 422)

    def test_tampered_stage_or_unsealed_prefix_never_qualifies(self):
        for defect in ('stage_hash', 'missing_stage', 'unfilled', 'loaded', 'not_final'):
            with self.subTest(defect=defect):
                before = copy.deepcopy(self.record)
                if defect == 'stage_hash': self.record['work']['stages'][-1]['configuration_hash'] = '0' * 64
                if defect == 'missing_stage': self.record['work']['stages'].pop()
                if defect == 'unfilled': self.record['state']['filled'].pop()
                if defect == 'loaded': self.record['work']['loaded_draft_id'] = 'a' * 32
                if defect == 'not_final': self.record['work']['failed_part'] = 'actors:0'
                self.persist()
                self.assertEqual(self.client.get(self.url).status_code, 422)
                self.assertEqual(self.request().status_code, 422)
                self.record = before
                self.persist()


if __name__ == '__main__':
    unittest.main()
