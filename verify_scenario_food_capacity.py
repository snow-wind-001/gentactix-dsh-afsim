"""Reject impossible initial food loads while their Native actor stage can edit them."""
import copy
import unittest
from unittest.mock import patch

from backend import scenario_assembly, scenario_builder
from gentactix import historical_operations as ho, support_dynamics as sd
from tools.qa.historical_operational_fixture import BATTLE
from verify_personnel_rations import parameters


class ScenarioFoodCapacityTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.params = parameters()
        self.basis = scenario_builder.historical_basis(BATTLE, 'taierzhuang')
        self.params['goal']['team'] = self.basis['configuration_template']['goal']['team']
        for actor in self.params['actors'].values():
            actor['formation'].setdefault('motorized', True)
        self.draft = scenario_assembly.create(self.basis)
        self.addCleanup(scenario_assembly.close, self.draft.id)
        self.identity = next(iter(self.params['actors']))

    def globals(self):
        result = self.draft.tool('globals', 'update_scenario_configuration', {
            'revision': self.draft.revision,
            'patch': {k: v for k, v in self.params.items() if k not in ('format', 'phase_id', 'actors')}})
        self.assertTrue(result['updated'], result)
        return result

    def actors(self):
        return self.draft.tool('actors:0', 'update_scenario_configuration', {
            'revision': self.draft.revision, 'patch': {'actors': self.params['actors']}})

    def test_partial_domain_rejects_capacity_excess_before_final_compilation(self):
        self.params['actors'][self.identity]['logistics']['food'] = 25
        with self.assertRaisesRegex(ValueError, '携行容量'):
            ho._validate(self.snapshot, self.params, actor_ids=[self.identity])

    def test_partial_domain_rejects_capacity_beyond_work_encoding(self):
        self.params['support_dynamics']['carried_kg_per_committed_person'] = 5
        with self.assertRaisesRegex(ValueError, '编码上限'):
            ho._validate(self.snapshot, self.params, actor_ids=[self.identity])

    def test_partial_validation_never_demands_other_unfilled_actor_inputs(self):
        other = next(i for i in self.params['actors'] if i != self.identity)
        self.params['actors'][other]['personnel'] = None
        self.params['actors'][other]['logistics']['food'] = None
        self.assertTrue(ho._validate(self.snapshot, self.params, actor_ids=[self.identity]))

    def test_bad_stage_returns_exact_unit_load_and_preserves_the_editable_draft(self):
        self.globals()
        self.params['actors'][self.identity]['logistics']['food'] = 25
        before = self.draft.export_state()
        result = self.actors()
        self.assertFalse(result['updated'], result)
        self.assertEqual(self.draft.export_state(), before)
        quote = result['food_loading']
        self.assertEqual(quote['unit'], self.identity)
        self.assertEqual(quote['food_work'], 25)
        self.assertEqual(quote['food_mass_kg'], 3125)
        self.assertEqual(quote['capacity_work'], 24)
        self.assertEqual(quote['capacity_kg'], 3000)
        self.assertEqual(quote['food_kg_per_work'], 125)
        self.assertIn('重复', result['instruction'])
        self.params['actors'][self.identity]['logistics']['food'] = 14.4
        result = self.actors()
        self.assertTrue(result['updated'], result)
        final = self.draft.tool('final', 'validate_scenario_configuration', {})
        self.assertTrue(final['valid'], final)
        self.assertEqual(self.draft.finish(final)['actors'][self.identity]['logistics']['food'], 14.4)

    def test_tool_basis_explains_mass_share_is_already_in_food_kg_per_work(self):
        self.globals()
        view = self.draft.tool('actors:0', 'get_scenario_basis', {})
        self.assertEqual(view['food_loading_contract']['food_kg_per_work'], 125)
        self.assertIn('重复', view['food_loading_contract']['instruction'])
        self.assertNotIn('food_loading_contract', self.draft.configuration)

    def test_final_failure_retains_specific_reason_without_issuing_a_validation_receipt(self):
        self.globals()
        result = self.actors()
        self.assertTrue(result['updated'], result)
        before = copy.deepcopy(self.draft.configuration)
        with patch('backend.afsim_world.compile_scene', side_effect=ValueError('QA: 原生模板约束失败')):
            result = self.draft.tool('final', 'validate_scenario_configuration', {})
        self.assertFalse(result['valid'])
        self.assertIsNone(self.draft.validation)
        with self.assertRaisesRegex(ValueError, '原生模板约束失败'):
            self.draft.finish(self.draft.receipt())
        self.assertEqual(self.draft.configuration, before)

    def test_full_runtime_and_actor_stage_use_the_same_mass_capacity_rule(self):
        self.params['actors'][self.identity]['logistics']['food'] = 24
        ho._validate(self.snapshot, self.params, actor_ids=[self.identity])
        world = ho.initial(self.snapshot, self.params)
        unit = next(u for u in world['red_units'] if u['historical_unit_id'] == self.identity)
        self.assertEqual(sd.food_mass(self.params['support_dynamics'], unit), 3000)
        self.assertEqual(sd.food_capacity(self.params['support_dynamics'], unit), 24)


if __name__ == '__main__':
    unittest.main(verbosity=2)
