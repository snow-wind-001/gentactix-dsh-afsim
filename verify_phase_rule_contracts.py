"""A phase change can change objectives, not silently revalue surviving forces."""
import copy
import json
import unittest

from gentactix import missions, phase_continuity, sim_clock
from verify_phase_continuity import checkpoint


class PhaseRuleContractTests(unittest.TestCase):
    def source_and_target(self, **models):
        source, target = checkpoint(**models)
        source['current_time'], source['simulation_clock'] = sim_clock.target(source, '1小时')
        self.assertTrue(missions.validate(source))
        return source, target

    def test_new_continuations_use_the_versioned_physical_rule_contract(self):
        source, target = self.source_and_target()
        self.assertEqual(phase_continuity.bind(source, target)['version'], 'historical-phase-continuity-2')

    def test_legacy_frozen_checkpoint_remains_readable_without_silent_migration(self):
        source, target = self.source_and_target()
        target['parameters']['rules']['transport_tons_per_truck'] = 9
        binding = phase_continuity.bind(source, target)
        binding['version'] = 'historical-phase-continuity-1'
        spec = phase_continuity.definition(binding)
        world = missions.from_definition(spec)
        self.assertEqual(spec['phase_continuation']['version'], binding['version'])
        self.assertEqual(world['phase_handoff']['version'], binding['version'])
        self.assertEqual(world['mission']['definition']['combined_rules']['transport_tons_per_truck'], 9)
        self.assertEqual(world['red_units'][0]['personnel'], source['red_units'][0]['personnel'])

    def reject_changes(self, changes):
        source, target = self.source_and_target()
        saved = copy.deepcopy((source, target))
        for key, value in changes:
            changed = copy.deepcopy(target)
            changed['parameters']['rules'][key] = value
            with self.subTest(rule=key):
                with self.assertRaisesRegex(ValueError, '物理.*规则'):
                    phase_continuity.definition(phase_continuity.bind(source, changed))
        self.assertEqual((source, target), saved)

    def test_transport_capacity_and_classified_exchange_rates_cannot_change(self):
        from gentactix.combined_arms import RULES
        mass = copy.deepcopy(RULES['cargo_mass_tons'])
        mass['shells'] /= 10
        self.reject_changes([('transport_tons_per_truck', 9),
            ('shells_per_supply_unit', 120), ('aa_rounds_per_supply_unit', 80),
            ('ton_per_supply_unit', .001), ('cargo_mass_tons', mass)])

    def test_weapons_cooldown_and_command_rates_cannot_upgrade(self):
        self.reject_changes([('artillery_range_m', 24000), ('reload_turns', 0),
            ('command_base_s', 0), ('fatigue_move_gain', 0)])

    def test_mode_switches_cannot_reinterpret_existing_equipment(self):
        self.reject_changes([('motorized', False), ('bridge_enabled', True)])

    def test_time_granularity_change_requires_explicit_rate_conversion(self):
        source, target = self.source_and_target()
        for step in ('15分钟', '1小时'):
            changed = copy.deepcopy(target)
            changed['parameters']['clock']['time_step'] = step
            with self.subTest(step=step):
                with self.assertRaisesRegex(ValueError, '物理.*规则'):
                    phase_continuity.definition(phase_continuity.bind(source, changed))

    def test_equivalent_clock_labels_keep_the_same_registered_physical_period(self):
        source, target = self.source_and_target()
        target['parameters']['clock']['time_step'] = '0.5小时'
        world = missions.from_definition(phase_continuity.definition(phase_continuity.bind(source, target)))
        self.assertEqual(sim_clock.duration_seconds(world['mission']['definition']['time_step']), 1800)
        self.assertEqual(world['combined_arms']['depots'], source['combined_arms']['depots'])

    def test_new_objective_side_and_survivor_requirement_remain_explicitly_allowed(self):
        source, target = self.source_and_target()
        target['parameters']['rules'].update(goal_profile='breakout', required_survivors=2)
        target['parameters']['goal'].update(profile='breakout', team='blue', required_survivors=2)
        world = missions.from_definition(phase_continuity.definition(phase_continuity.bind(source, target)))
        self.assertEqual(world['mission']['definition']['combined_rules']['goal_profile'], 'breakout')
        self.assertEqual(world['mission']['definition']['combined_rules']['required_survivors'], 2)
        self.assertEqual(world['red_units'][0]['personnel'], source['red_units'][0]['personnel'])
        self.assertEqual(world['combined_arms']['depots'], source['combined_arms']['depots'])

    def test_explicit_phase_terrain_change_does_not_teleport_or_restore_units(self):
        source, target = self.source_and_target()
        target['parameters']['area']['terrain_factor'] = 1.5
        world = missions.from_definition(phase_continuity.definition(phase_continuity.bind(source, target)))
        self.assertEqual(world['mission']['definition']['geometry']['terrain_factor'], 1.5)
        for old, new in zip(source['red_units'] + source['blue_units'], world['red_units'] + world['blue_units']):
            for key in ('lat', 'lng', 'personnel', 'equipment', 'logistics'):
                self.assertEqual(new[key], old[key])

    def test_unchanged_contract_carries_shortage_fraction_and_damage_through_json_restore(self):
        from verify_support_dynamics import config
        source, target = self.source_and_target(support_dynamics=config())
        source['red_units'][0]['sustainment'].update(shortage_hours=3.25, noncombat_remainder=.37)
        binding = json.loads(json.dumps(phase_continuity.bind(source, target)))
        world = missions.from_definition(phase_continuity.definition(binding))
        self.assertEqual(world['red_units'][0]['sustainment'], source['red_units'][0]['sustainment'])
        self.assertEqual(world['red_units'][0]['equipment'], source['red_units'][0]['equipment'])
        self.assertEqual(world['red_units'][0]['formation']['fatigue'], 73)


if __name__ == '__main__':
    unittest.main()
