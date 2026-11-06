"""Explicit budgets expose insufficient sustained fire without inventing stock."""
import copy
import unittest
from gentactix import historical_operations
from tools.qa.historical_operational_fixture import inputs


class ResourceReadinessTests(unittest.TestCase):
    def test_fire_budget_uses_both_work_and_shells_and_never_refills_stock(self):
        from gentactix import resource_readiness
        snapshot, params = inputs()
        world = historical_operations.initial(snapshot, params)
        unit = world['red_units'][0]
        unit['logistics']['ammo'] = 2
        unit['formation']['shells'] = 10000
        before = copy.deepcopy(world)
        row = resource_readiness.assess(world)['units'][0]
        self.assertEqual(row['fire_work_minutes'], 4)
        self.assertLessEqual(row['artillery_minutes'], 4)
        self.assertIn('fire_budget_shorter_than_one_turn', row['warnings'])
        self.assertEqual(world, before)

    def test_missing_time_food_model_stays_unknown(self):
        from gentactix import resource_readiness
        snapshot, params = inputs()
        row = resource_readiness.assess(historical_operations.initial(snapshot, params))['units'][0]
        self.assertIsNone(row['food_hold_hours'])
        self.assertIn('time_food_model_missing', row['warnings'])

    def test_destroyed_formation_has_no_fire_capacity_even_with_unspent_ammo(self):
        from gentactix import resource_readiness
        snapshot,params=inputs();world=historical_operations.initial(snapshot,params)
        world['red_units'][0]['personnel'].update(current=0,casualties=6000)
        row=resource_readiness.assess(world)['units'][0]
        self.assertEqual(row['fire_work_minutes'],0)
        self.assertEqual(row['artillery_minutes'],0)


if __name__ == '__main__': unittest.main()
