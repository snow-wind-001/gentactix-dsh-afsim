"""Native coverage counters cannot be presented as physical contact duration."""
import copy
import unittest

from backend import afsim_state
from gentactix import combat_effects, fire_process, historical_operations
from tools.qa.historical_operational_fixture import inputs


class FireTimeScopeTests(unittest.TestCase):
    def setUp(self):
        self.world = historical_operations.initial(*inputs())
        self.session = dict(id='fire-time-scope', war_state=self.world, time_step='30分钟',
                            turn_count=0, execution_backend='afsim', simulation_mode='open')

    def test_observation_qualifies_the_counter_without_manufacturing_a_receipt(self):
        before = copy.deepcopy(self.session)
        value = afsim_state.observation(self.session, {'limit': 1})
        scope = value['native_fire_time_scope']
        self.assertFalse(scope['additive_across_partitions'])
        self.assertFalse(scope['includes_prior_turn_tail'])
        self.assertEqual(scope['metric'], 'new_cycle_window_coverage_seconds')
        self.assertNotIn('last_execution', self.world['red_units'][0]['formation'])
        self.assertEqual(self.session, before)

    def test_model_prior_discloses_turn_start_density_without_claiming_convergence(self):
        before = copy.deepcopy(self.world)
        value = fire_process.observation(self.world)['feedback']
        self.assertEqual(value['indirect_density_sampling'], 'turn_start_shared_footprint')
        self.assertFalse(value['partition_invariance_verified'])
        self.assertEqual(self.world, before)

    def test_readonly_analysis_receives_the_actual_scope(self):
        value = afsim_state.analysis_prompt(self.session, '比较两次不同步长的炮击')
        self.assertIn('不含上轮周期尾段', value)
        self.assertIn('不能据此认定实际接敌时长', value)
        self.assertIn('目标密度在轮初取样', value)

    def test_combat_review_does_not_name_the_clipped_counter_contact_time(self):
        after = copy.deepcopy(self.world)
        after['mission']['turn'] = 1
        review = combat_effects.assess_turn(self.world, after, 1800, [], source='afsim_native')
        self.assertIn('非可加的周期覆盖指标', review['note'])
        self.assertNotIn('接敌时长按', review['note'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
