"""Explicit suppression carry: native receipts, old rules and model boundaries."""
import copy
import unittest

from backend import afsim_world, scenario_assembly
from gentactix import combat_effects, historical_operations as ho, missions
from tools.qa.historical_operational_fixture import inputs, NOTE

CONFIG = {'version': 'live-footprint-density-2', 'assumption': NOTE}


def world(selected=True, **rule_changes):
    s, p = inputs()
    p['fire_dynamics'] = copy.deepcopy(CONFIG if selected else {
        'version': 'live-footprint-density-1', 'assumption': NOTE})
    p['rules'].update(rule_changes)
    return ho.initial(s, p)


class ContinuousSuppressionTests(unittest.TestCase):
    def test_new_selection_is_frozen_without_migrating_the_previous_version(self):
        from gentactix import suppression_state as ss
        old = world(False); saved = copy.deepcopy(old); new = world()
        profile = combat_effects.reference(new)
        self.assertEqual(profile['version'], 'aggregate-fire-cycles-2.6')
        self.assertEqual(profile['combat_revision'], 5)
        self.assertEqual(profile['suppression_state'], ss.CONFIG)
        self.assertNotIn('suppression_state', combat_effects.reference(old))
        self.assertEqual(old, saved)

    def test_native_program_has_endpoint_decay_and_complete_carry_receipts(self):
        new = afsim_world.compile_scene(world(), [], 1800, native_rules=True)
        old = afsim_world.compile_scene(world(False), [], 1800, native_rules=True)
        self.assertIn('GtxSuppressionDecay', new['script'])
        self.assertEqual(new['script'].count('writeln("GTXSUPPRESSION|'), len(new['entities']))
        self.assertNotIn('GTXSUPPRESSION', old['script'])
        self.assertIn('GtxSuppressionDecay(p0,1800)', new['script'])

    def test_new_required_model_cannot_silently_downgrade(self):
        s, p = inputs(); p['fire_dynamics'] = copy.deepcopy(CONFIG)
        scenario_assembly.validate_required_models(p, [CONFIG['version']])
        p['fire_dynamics']['version'] = 'live-footprint-density-1'
        with self.assertRaisesRegex(ValueError, '版本|选择'):
            scenario_assembly.validate_required_models(p, [CONFIG['version']])

    def test_profile_cannot_inject_carry_into_old_rules(self):
        from gentactix import suppression_state as ss
        profile = combat_effects.reference(world(False))
        profile['suppression_state'] = copy.deepcopy(ss.CONFIG)
        with self.assertRaises(ValueError): combat_effects.validate_profile(profile)

    def test_runtime_component_is_not_mutable_after_freezing(self):
        w = world(); w['combat_reference'] = combat_effects.reference(w)
        w['combat_reference']['suppression_state']['units_per_point'] += 1
        with self.assertRaises(ValueError): missions.validate(w)

    def test_carry_has_integer_bounds_and_cannot_exceed_full_suppression(self):
        from gentactix import suppression_state as ss
        for points, carry in [(0, -1), (0, True), (0, 1.5), (0, ss.SCALE), (100, 1)]:
            u = copy.deepcopy(world()['red_units'][0])
            u['formation'].update(suppression=points, suppression_carry_ticks=carry)
            with self.subTest(points=points, carry=carry), self.assertRaises(ValueError):
                ss.validate_unit(u)

    def native_rows(self):
        from gentactix import suppression_state as ss
        w = world(); scene = afsim_world.compile_scene(w, [], 1800, native_rules=True)
        rows = {i: dict(points=0, carry_ticks=ss.SCALE-1, at_ms=1800000) for i in scene['entities']}
        units = {i: dict(suppression=0) for i in scene['entities']}
        return rows, scene['native_model'], scene, units

    def test_valid_receipts_are_readonly_and_cover_every_entity(self):
        from backend import afsim_suppression as native
        rows, model, scene, units = self.native_rows(); saved = copy.deepcopy((rows, model, scene, units))
        native.validate_receipts(rows, model, scene, units)
        self.assertEqual((rows, model, scene, units), saved)

    def test_missing_duplicate_identity_or_wrong_endpoint_is_rejected(self):
        from backend import afsim_suppression as native
        for kind in ('missing', 'unknown', 'future', 'wrong_point', 'fractional'):
            rows, model, scene, units = self.native_rows(); identity = next(iter(rows))
            if kind == 'missing': rows.pop(identity)
            elif kind == 'unknown': rows['unknown'] = copy.deepcopy(rows[identity])
            elif kind == 'future': rows[identity]['at_ms'] += 1
            elif kind == 'wrong_point': rows[identity]['points'] = 1
            else: rows[identity]['carry_ticks'] = .5
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                native.validate_receipts(rows, model, scene, units)

    def test_old_world_rejects_new_native_state(self):
        from backend import afsim_suppression as native
        rows, _, _, units = self.native_rows()
        scene = afsim_world.compile_scene(world(False), [], 1800, native_rules=True)
        with self.assertRaises(ValueError): native.validate_receipts(rows, scene['native_model'], scene, units)

    def test_split_preserves_intensive_state_and_merge_chooses_the_same_worst_pair(self):
        from gentactix import formation_conversion as fc, suppression_state as ss
        from verify_formation_conversion import ConversionTests, damaged
        unit = damaged(); unit['formation'].update(suppression=8, suppression_carry_ticks=ss.SCALE-1)
        proposal = ConversionTests().split(unit)
        self.assertTrue(all(u['formation']['suppression_carry_ticks'] == ss.SCALE-1 for u in proposal['after']))
        a, b = proposal['after']; a['formation'].update(suppression=9, suppression_carry_ticks=1)
        merged = fc.merge_current([a, b], assumption=NOTE, operation_id='e'*32)['after'][0]
        self.assertEqual((merged['formation']['suppression'], merged['formation']['suppression_carry_ticks']), (9, 1))

    def test_model_must_supply_selected_state_and_old_model_cannot_inject_it(self):
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        from gentactix import suppression_state as ss
        new = world(); result = model_result(new)
        with self.assertRaisesRegex(ValueError, '压制|余量'):
            dsh_simulation.apply(new, result, '30分钟')
        old = world(False); result = model_result(old)
        result['unit_updates'][0]['formation']['suppression_carry_ticks'] = 1
        with self.assertRaisesRegex(ValueError, '压制|余量'):
            dsh_simulation.apply(old, result, '30分钟')

    def test_model_declared_unopposed_decay_is_checked_without_writing_effects(self):
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        from gentactix import suppression_state as ss
        w = world()
        for _, u in missions.units(w): u['formation'].update(suppression=30, suppression_carry_ticks=17)
        result = model_result(w)
        for row in result['unit_updates']: row['formation'].update(suppression=20, suppression_carry_ticks=17)
        saved = copy.deepcopy((w, result))
        after = dsh_simulation.apply(w, result, '30分钟')
        self.assertEqual((w, result), saved)
        self.assertEqual([ss.load(u) for _, u in missions.units(after)], [20*ss.SCALE+17]*3)
        self.assertEqual(after['dsh_execution']['effects_source'], 'dsh_model_estimate')
        self.assertNotIn('afsim', after)
        result['unit_updates'][0]['formation'][ss.FIELD] = 18
        with self.assertRaisesRegex(ValueError, '时间衰减'): dsh_simulation.apply(w, result, '30分钟')

    def test_first_model_frame_registers_the_new_counter_even_when_zero_is_implicit(self):
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        from gentactix import suppression_state as ss
        w = world()
        for _, u in missions.units(w): u['formation'].pop(ss.FIELD, None)
        result = model_result(w)
        for row in result['unit_updates']: row['formation'].update(suppression=0, suppression_carry_ticks=0)
        saved = copy.deepcopy((w, result))
        after = dsh_simulation.apply(w, result, '30分钟')
        self.assertEqual((w, result), saved)
        self.assertTrue(all(u['formation'][ss.FIELD] == 0 for _, u in missions.units(after)))

    def test_normal_public_preview_accepts_the_first_complete_model_candidate(self):
        import os, tempfile
        from unittest.mock import patch
        from backend import turn_preview
        from gentactix import fire_process, suppression_state as ss
        from verify_dsh_resources import model_result
        w = world()
        for _, u in missions.units(w): u['formation'].pop(ss.FIELD, None)
        value = model_result(w)
        for row in value['unit_updates']: row['formation'].update(suppression=0, suppression_carry_ticks=0)
        value['fire_ledger'] = {'version': fire_process.VERSION, 'units': []}
        s = dict(id='ss-preview-qa', war_state=w, turn_count=0, time_step='30分钟',
                 execution_backend='narrative', agent_mode='native', product_mode='historical', role_epoch=0)
        saved = copy.deepcopy(w)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'GENTACTIX_SESSION_DIR': tmp+'/sessions', 'GENTACTIX_TRACE_DIR': tmp+'/traces',
                'GENTACTIX_ROLE_INDEX': tmp+'/roles.json'}):
            ctx = turn_preview.context(s, None, operation_id='f'*32)
            result = turn_preview.execute(ctx, {'tool': turn_preview.TOOL, 'args': {'candidate': value}})
        self.assertTrue(result['ok'], result)
        self.assertEqual(w, saved)

    def test_new_units_register_zero_at_birth_and_committed_state_cannot_drop_it(self):
        from gentactix import suppression_state as ss
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        w = world(); self.assertTrue(all(u['formation'][ss.FIELD] == 0 for _, u in missions.units(w)))
        self.assertTrue(all(ss.FIELD not in u['formation'] for _, u in missions.units(world(False))))
        value = model_result(w)
        for row in value['unit_updates']: row['formation'].update(suppression=0, suppression_carry_ticks=0)
        after = dsh_simulation.apply(w, value, '30分钟')
        after['red_units'][0]['formation'].pop(ss.FIELD)
        with self.assertRaisesRegex(ValueError, '压制余量缺失'): missions.validate(after)

    def test_observation_exposes_precision_and_current_fraction_for_model_reading(self):
        from backend import afsim_state
        from gentactix import suppression_state as ss
        w = world(); w['red_units'][0]['formation'][ss.FIELD] = 17
        page = afsim_state.observation({'id': 'suppression-observation-qa', 'war_state': w, 'turn_count': 0,
            'time_step': '30分钟', 'product_mode': 'historical', 'execution_backend': 'afsim'}, {'limit': 16})
        unit = next(u for u in page['units'] if u['name'] == w['red_units'][0]['name'])
        self.assertEqual(unit['formation'][ss.FIELD], 17)
        self.assertEqual(unit['suppression_state'], ss.CONFIG)

    def test_requested_version_overrides_only_the_new_template_and_rejects_conflicts(self):
        basis = {'configuration_template': {'fire_dynamics': {'version': 'live-footprint-density-1', 'assumption': NOTE}}}
        saved = copy.deepcopy(basis)
        scenario_assembly.prepare_required_models(basis, [CONFIG['version']])
        self.assertEqual(basis['configuration_template']['fire_dynamics']['version'], CONFIG['version'])
        self.assertEqual(saved['configuration_template']['fire_dynamics']['version'], 'live-footprint-density-1')
        with self.assertRaisesRegex(ValueError, '版本'):
            scenario_assembly.prepare_required_models(basis, [CONFIG['version'], 'live-footprint-density-1'])

    def test_native_text_parser_rejects_duplicate_rows_and_preserves_large_integers(self):
        from backend import afsim_suppression as native
        from gentactix import suppression_state as ss
        _, _, scene, _ = self.native_rows(); identity = next(iter(scene['entities']))
        parts = ['GTXSUPPRESSION', identity, '0', str(ss.SCALE-1), '1800000']; rows = {}
        native.read_row(parts, rows, scene)
        self.assertEqual(rows[identity]['carry_ticks'], ss.SCALE-1)
        with self.assertRaisesRegex(ValueError, '重复'): native.read_row(parts, rows, scene)

    def test_quiet_validation_keeps_the_fraction_across_the_third_short_frame(self):
        from gentactix import fire_process
        w = world(); u = w['red_units'][0]
        u['formation'].update(suppression=76, suppression_carry_ticks=1200000000000)
        self.assertEqual(fire_process.quiet_suppression_after(w, u, 300), 75)

    def test_surrender_threshold_compares_the_full_value_including_fraction(self):
        from gentactix import campaign, suppression_state as ss
        from tools.qa.campaign_fixture import inputs as campaign_inputs
        from unittest.mock import patch
        s, p = campaign_inputs(); p['fire_dynamics'] = copy.deepcopy(CONFIG)
        p['campaign']['surrender']['suppression_threshold'] = 65.5
        w = ho.initial(s, p); target = w['blue_units'][0]
        target['formation'].update(suppression=65, suppression_carry_ticks=1350000000000)
        order = dict(unit=w['red_units'][0]['name'], action='capture', target=target['name'])
        with patch.object(ss, 'value', side_effect=lambda u: u['formation']['suppression']):
            with self.assertRaisesRegex(ValueError, '受降条件'): campaign.capture_target(w, order)
        self.assertIs(campaign.capture_target(w, order), target)


if __name__ == '__main__': unittest.main(verbosity=2)
