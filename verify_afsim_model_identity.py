"""Counterfactuals must bind all versioned native dynamics before execution."""
import copy
import unittest
from unittest.mock import patch

from backend import afsim_combined, afsim_comparison, afsim_world
from gentactix import combat_effects, historical_operations, missions
from tools.qa.historical_operational_fixture import inputs


class NativeModelIdentityTests(unittest.TestCase):
    def setUp(self):
        before = historical_operations.initial(*inputs())
        self.orders = [dict(unit=u['name'], action='hold') for _, u in missions.units(before)]
        after = copy.deepcopy(before)
        after['afsim'] = dict(motion_revision=afsim_world.motion_revision(before),
            combat_revision=combat_effects.reference(before)['combat_revision'],
            combat_profile=combat_effects.reference(before),
            command_control_revision=afsim_combined.COMMAND_CONTROL_REVISION,
            supply_control_revision=afsim_combined.SUPPLY_CONTROL_REVISION,
            intelligence_revision=afsim_combined.INTELLIGENCE_REVISION,
            formation_fire_control_revision=afsim_combined.FORMATION_FIRE_CONTROL_REVISION,
            legacy_support_revision=afsim_combined.LEGACY_SUPPORT_REVISION)
        self.record = dict(before=before, after=after, time_step='30分钟')
        self.session = dict(id='readonly-model-identity', war_state=copy.deepcopy(after))

    def rejected(self, field, value, *, missing=False):
        if missing:
            self.record['after']['afsim'].pop(field)
        else:
            self.record['after']['afsim'][field] = value
        frozen = copy.deepcopy((self.session, self.record, self.orders))
        with patch.object(afsim_world, 'run_scene', side_effect=AssertionError('Native must not start')) as native:
            with self.assertRaisesRegex(ValueError, '执行版本|版本证据'):
                afsim_comparison.compare(self.session, self.record, self.orders)
            native.assert_not_called()
        self.assertEqual((self.session, self.record, self.orders), frozen)

    def test_changed_formation_fire_control_is_not_a_decision_effect(self):
        self.rejected('formation_fire_control_revision', afsim_combined.FORMATION_FIRE_CONTROL_REVISION + 1)

    def test_changed_intelligence_decay_is_not_a_decision_effect(self):
        self.rejected('intelligence_revision', afsim_combined.INTELLIGENCE_REVISION + 1)

    def test_changed_frame_support_is_not_a_decision_effect(self):
        self.rejected('legacy_support_revision', afsim_combined.LEGACY_SUPPORT_REVISION + 1)

    def test_missing_version_is_not_assumed_to_be_current(self):
        for field in ('formation_fire_control_revision', 'intelligence_revision', 'legacy_support_revision'):
            with self.subTest(field=field):
                self.setUp()
                self.rejected(field, None, missing=True)

    def test_noninteger_revision_is_rejected_before_execution(self):
        for field in ('formation_fire_control_revision', 'intelligence_revision', 'legacy_support_revision'):
            for value in (True, float(getattr(afsim_combined, field.upper())), str(getattr(afsim_combined, field.upper()))):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    self.rejected(field, value)

    def test_matching_native_versions_reach_the_existing_executor(self):
        frozen = copy.deepcopy((self.session, self.record, self.orders))
        with patch.object(afsim_world, 'run_scene', side_effect=RuntimeError('native-start')) as native:
            with self.assertRaisesRegex(RuntimeError, 'native-start'):
                afsim_comparison.compare(self.session, self.record, self.orders)
            native.assert_called_once()
        self.assertEqual((self.session, self.record, self.orders), frozen)


if __name__ == '__main__':
    unittest.main(verbosity=2)
