"""Disjoint historical calculation parts: conserved inputs, identity and totals."""
import copy
import unittest

from gentactix import historical_operations as ho, missions
from tools.qa.historical_crossing_fixture import inputs


def partition_input(parameters):
    parent = parameters['actors']['lm.red.cmc_column']
    resources = ('fuel_liters', 'spares', 'materials', 'shells', 'aa_rounds')
    return {'version': 'formation-partitions-1', 'groups': {'lm.red.cmc_column': {
        'assumption': 'QA互斥计算划分，5人不是军委纵队历史先遣人数。',
        'parts': [
            {'id': 'main', 'label': '主队', 'personnel': parent['personnel'] - 5,
             'position': copy.deepcopy(parent['position']), 'equipment': copy.deepcopy(parent['equipment']),
             'resources': {k: parent['formation'][k] for k in resources}, 'dispersion_km2': 2,
             'assumption': 'QA主队估计位置与装备配发。'},
            {'id': 'advance', 'label': '先遣分队', 'personnel': 5,
             'position': {'lat': 27.3158, 'lng': 107.402},
             'equipment': {k: 0 for k in parent['equipment']},
             'resources': {k: 0 for k in resources}, 'dispersion_km2': .01,
             'assumption': 'QA五人位置与展开估计，不是历史渡口坐标。'},
        ]}}}


class FormationPartTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.params = inputs()
        self.params['partitions'] = partition_input(self.params)

    def world(self):
        return ho.initial(self.snapshot, self.params)

    def test_same_parent_has_two_positions_but_only_one_conserved_force(self):
        before = copy.deepcopy(self.snapshot)
        w = self.world()
        from gentactix import formation_parts
        rows = [u for u in w['red_units'] if u.get('formation_part')]
        self.assertEqual([u['personnel']['current'] for u in rows], [1595, 5])
        self.assertEqual(len({u['calculation_unit_id'] for u in rows}), 2)
        self.assertEqual({u['historical_unit_id'] for u in rows}, {'lm.red.cmc_column'})
        self.assertTrue(all('计算分队' in u['name'] for u in rows))
        summary = formation_parts.observation(w)['groups'][0]
        self.assertEqual(summary['personnel']['committed'], 1600)
        self.assertEqual(summary['personnel']['current'], 1600)
        self.assertEqual(summary['equipment']['transport']['committed'], 4)
        self.assertAlmostEqual(summary['normalized_stock_equivalent']['food'], 80)
        self.assertEqual(self.snapshot, before)
        self.assertEqual(sum(u['personnel']['committed'] for u in w['red_units']), 4600)

    def test_invalid_or_duplicated_allocations_cannot_create_people_gear_or_resources(self):
        for kind in ('personnel', 'equipment', 'resources', 'id', 'unknown_parent', 'outside', 'single'):
            p = copy.deepcopy(self.params)
            g = p['partitions']['groups']['lm.red.cmc_column']
            if kind == 'personnel': g['parts'][1]['personnel'] += 1
            if kind == 'equipment': g['parts'][1]['equipment']['transport'] = 1
            if kind == 'resources': g['parts'][1]['resources']['shells'] = 1
            if kind == 'id': g['parts'][1]['id'] = 'main'
            if kind == 'unknown_parent': p['partitions']['groups']['invented'] = p['partitions']['groups'].pop('lm.red.cmc_column')
            if kind == 'outside': g['parts'][1]['position']['lat'] = 0
            if kind == 'single': g['parts'] = g['parts'][:1]
            with self.subTest(kind=kind), self.assertRaises(ValueError): ho.initial(self.snapshot, p)

    def test_live_state_cannot_reassign_identity_or_detach_a_part_from_its_group(self):
        w = self.world()
        for kind in ('group', 'weight', 'identity', 'member'):
            value = copy.deepcopy(w)
            if kind == 'group': value.pop('formation_groups')
            if kind == 'weight': value['red_units'][0]['formation_part']['denominator'] += 1
            if kind == 'identity': value['red_units'][0]['calculation_unit_id'] += '-other'
            if kind == 'member': value['formation_groups']['groups'][0]['members'].pop()
            with self.subTest(kind=kind), self.assertRaises(ValueError): missions.validate(value)

    def test_split_counts_as_one_parent_for_goals_and_requires_all_live_parts_to_break_out(self):
        from gentactix import formation_parts
        w = self.world()
        self.assertEqual(formation_parts.count(w, 'red', lambda u: True), 2)
        self.assertEqual(formation_parts.count(w, 'red', lambda u: bool(u.get('formation_part'))), 1)
        self.assertEqual(formation_parts.count(w, 'red', lambda u: u['lat'] > 27.315, whole=True), 0)

    def test_old_configuration_and_world_do_not_get_partition_fields(self):
        self.params.pop('partitions')
        w = self.world()
        self.assertNotIn('formation_groups', w)
        self.assertTrue(all('formation_part' not in u for _, u in missions.units(w)))

    def test_dsh_accounts_use_parent_equivalents_without_doubling_normalized_rations(self):
        from gentactix import formation_parts
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        w = self.world()
        candidate = model_result(w)
        for (_, unit), row in zip(missions.units(w), candidate['resource_ledger']['units']):
            row['food_spent'] *= formation_parts.scale(unit)
        after = dsh_simulation.apply(w, candidate, '30分钟')
        self.assertAlmostEqual(formation_parts.observation(after)['groups'][0]['normalized_stock_equivalent']['food'], 78)
        grouped = {u['name'] for u in w['red_units'] if u.get('formation_part')}
        self.assertAlmostEqual(sum(r['food_spent'] for r in after['mission']['ledger'] if r['unit'] in grouped), 2)

    def test_observation_and_analysis_explain_coverage_versus_parent_equivalent_debits(self):
        from gentactix import formation_parts
        from backend import afsim_state
        world = self.world()
        frozen = copy.deepcopy(world)
        observation = formation_parts.observation(world)
        rule = observation['resource_accounting']
        self.assertIn('food_after', rule)
        self.assertIn('/scale', rule)
        self.assertIn('初始人员占比', rule)
        prompt = afsim_state.analysis_prompt({'id': 'qa-weighted-observation', 'war_state': world,
            'turn_count': 0, 'time_step': '1分钟', 'execution_backend': 'afsim'}, '只读核对粮食')
        self.assertIn('normalized_resource_scale', prompt)
        self.assertIn('不是差额缺载', prompt)
        self.assertEqual(world, frozen)

    def test_program_breakout_cannot_count_two_fragments_as_two_historical_formations(self):
        p = self.params
        p['goal'].update(profile='breakout', exit={'lat': 27.324, 'lng': 107.402}, required_survivors=2)
        p['rules'].update(goal_profile='breakout', required_survivors=2)
        for part in p['partitions']['groups']['lm.red.cmc_column']['parts']:
            part['position'] = copy.deepcopy(p['goal']['exit'])
        w = self.world()
        missions.evaluate(w)
        self.assertEqual(w['mission']['progress'], 0)

    def test_native_compilation_preserves_fractional_depot_receipts_and_parent_goal_counts(self):
        from backend import afsim_world
        w = self.world()
        scene = afsim_world.compile_scene(w, [], 1800, native_rules=True)
        self.assertEqual(scene['motion_revision'], 8)
        self.assertIn('ca_ammo_cycle', scene['script'])
        self.assertIn('Format.Fixed(depot', scene['script'])
        self.assertIn('gtx_parent_goal', scene['script'])

    def test_synthetic_default_keeps_parts_and_explicit_edits_rebind_exercise_totals(self):
        from gentactix import synthetic_history, formation_parts
        base = ho.definition(self.snapshot, self.params)
        binding = base['historical_calculation']
        seed = synthetic_history.seed(binding)
        ids = [r['basis_id'] for rows in seed['configuration']['teams'].values() for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        default = missions.from_definition(synthetic_history.definition(binding, seed['configuration']))
        self.assertEqual(default['formation_groups'], base['initial_state']['formation_groups'])
        for unit, original in zip(default['red_units'], base['initial_state']['red_units']):
            for key in ('name', 'calculation_unit_id', 'lat', 'lng', 'logistics', 'formation_part'):
                self.assertEqual(unit.get(key), original.get(key))
            self.assertEqual(unit['personnel']['current'], original['personnel']['current'])
        changed = copy.deepcopy(seed['configuration'])
        changed['teams']['red'][0]['personnel'] += 5
        edited = missions.from_definition(synthetic_history.definition(binding, changed))
        self.assertEqual(formation_parts.observation(edited)['groups'][0]['personnel']['committed'], 1605)
        self.assertEqual(edited['historical_initial'], self.snapshot)


if __name__ == '__main__':
    unittest.main()
