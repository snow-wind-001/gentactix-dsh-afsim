"""Paid work/rest uses one Native fatigue and ration timeline; no state executor."""
import copy
import unittest
from gentactix import support_dynamics as sd, missions
from verify_scheduled_physical import world

class WorkFoodTests(unittest.TestCase):

    def unit(self, personnel=False):
        w = world(personnel=personnel)
        u = copy.deepcopy(missions.units(w)[0][1])
        u['logistics']['food'] = 100
        return (w['mission']['definition']['support_dynamics'], u)

    def test_only_productive_half_hour_gets_extra_food(self):
        (cfg, u) = self.unit()
        before = copy.deepcopy(u)
        base = sd.expected(cfg, u, 'hold', 3600)
        row = sd.expected(cfg, u, 'hold', 3600, working_seconds=1800, work_factor=2)
        self.assertAlmostEqual(row['demand'], base['demand'] * 1.5)
        self.assertEqual(row['consumed'], row['demand'])
        self.assertEqual(row['shortage_hours'], 0)
        self.assertEqual(u, before)

    def test_personnel_ration_keeps_people_mass_and_time_one_factor_each(self):
        (cfg, u) = self.unit(True)
        base = sd.expected(cfg, u, 'hold', 3600)
        full = sd.expected(cfg, u, 'hold', 3600, working_seconds=3600, work_factor=1.5)
        self.assertAlmostEqual(full['demand'], base['demand'] * 1.5)
        u['personnel']['current'] //= 2
        half = sd.expected(cfg, u, 'hold', 3600, working_seconds=3600, work_factor=1.5)
        self.assertAlmostEqual(half['demand'], full['demand'] / 2)

    def test_move_work_and_idle_share_elapsed_time_instead_of_three_base_meals(self):
        (cfg, u) = self.unit()
        base = sd.expected(cfg, u, 'hold', 3600)
        row = sd.expected(cfg, u, 'move', 3600, moving_seconds=1200, working_seconds=1200, work_factor=2)
        factor = 1 + (cfg['move_factor'] - 1) / 3 + 1 / 3
        self.assertAlmostEqual(row['demand'], base['demand'] * factor)

    def test_insufficient_food_updates_one_shortage_clock(self):
        (cfg, u) = self.unit()
        need = sd.expected(cfg, u, 'hold', 3600)['demand'] * 2
        u['logistics']['food'] = need / 2
        row = sd.expected(cfg, u, 'hold', 3600, working_seconds=3600, work_factor=2)
        self.assertEqual(row['consumed'], need / 2)
        self.assertAlmostEqual(row['shortage_hours'], 0.5)

    def test_zero_workers_have_zero_base_and_activity_rations(self):
        (cfg, u) = self.unit()
        u['personnel']['current'] = 0
        r = sd.expected(cfg, u, 'hold', 3600, working_seconds=3600, work_factor=10)
        self.assertEqual(r['demand'], 0)
        self.assertEqual(r['consumed'], 0)

    def test_work_activity_bounds_and_overlapping_time_are_rejected(self):
        (cfg, u) = self.unit()
        for args in [dict(working_seconds=-1, work_factor=2), dict(working_seconds=3601, work_factor=2), dict(working_seconds=True, work_factor=2), dict(working_seconds=1, work_factor=0.5), dict(working_seconds=1, work_factor=11), dict(working_seconds=3000, moving_seconds=1000, work_factor=2)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                sd.expected(cfg, u, 'move', 3600, **args)

    def test_no_work_and_neutral_activity_preserve_existing_ration_results(self):
        (cfg, u) = self.unit()
        old = sd.expected(cfg, u, 'move', 3600, moving_seconds=1200)
        self.assertEqual(sd.expected(cfg, u, 'move', 3600, moving_seconds=1200, working_seconds=0, work_factor=2), old)
        self.assertEqual(sd.expected(cfg, u, 'move', 3600, moving_seconds=1200, working_seconds=1800, work_factor=1), old)
from backend import afsim_continuous_motion as cm, afsim_motion_nutrition as cn
from verify_shared_fortification import control

def inputs():
    c = control()
    i = c['entity_id']
    m = {'work_support_revision': cm.WORK_SUPPORT_VERSION, 'nutrition_revision': cn.VERSION, 'controls': {i: {'formation': {'fatigue': 10, 'fatigue_carry_ticks': 0, 'fuel_liters': 2000, 'fuel_credit_microliters': 0}, 'rest_points_per_second': 2 / 1800}}, 'shared_fortification': {'model': {'controls': [c]}}}
    work = {i: {'intervals': [{'start_ms': 0, 'end_ms': 3600000, 'current': 6000, 'receipt': {'productive_ms': 1800000.0, 'waited_ms': 600000}}]}}
    row = dict(zip(cm.WORK_FIELDS, [0, 3600000, 10000000, 600000, 1800000.0, 1200000.0, 666667, 10000000, 1333333, 18000000]))
    native = 'GTXCMWORK|' + i + '|' + '|'.join((str(row[k]) for k in cm.WORK_FIELDS)) + '\n'
    nutrition = dict(zip(cn.FIELDS, [0, 3600000, 0, 6000, 9, 9, 0, 0, 0, 0, 0]))
    native += 'GTXCNSEG|' + i + '|' + '|'.join((str(nutrition[k]) for k in cn.FIELDS)) + '\n'
    return (m, work, native)

class WorkFatigueTests(unittest.TestCase):

    def test_wait_work_and_post_work_rest_are_sequential_and_conserve_ticks(self):
        (m, w, raw) = inputs()
        before = copy.deepcopy((m, w))
        r = cm.check_work_support(raw, m, w)[next(iter(w))]
        self.assertEqual(r['fatigue_after_ticks'], 18000000)
        self.assertEqual(r['work_gained_ticks'], 10000000)
        self.assertEqual(r['work_rest_recovered_ticks'], 2000000)
        self.assertEqual(r['productive_ms'], 1800000)
        self.assertEqual(r['work_idle_ms'], 1800000)
        self.assertEqual((m, w), before)

    def test_missing_duplicate_or_forged_fatigue_rows_reject(self):
        (m, w, raw) = inputs()
        first = raw.splitlines()[0]
        for bad in [raw.replace(first, ''), raw + '\n' + first, raw.replace('|18000000\n', '|18000001\n')]:
            with self.subTest(bad=bad[-50:]), self.assertRaisesRegex(ValueError, '时段不完整|疲劳账不一致'):
                cm.check_work_support(bad, m, w)

    def test_nutrition_personnel_and_paid_time_must_match_work(self):
        (m, w, raw) = inputs()
        for bad in [raw.replace('|6000|9|9|', '|5000|9|9|'), raw.replace('|1800000.0|1200000.0|', '|1800001.0|1199999.0|')]:
            with self.subTest(bad=bad[-50:]), self.assertRaisesRegex(ValueError, '未绑定实际施工'):
                cm.check_work_support(bad, m, w)
if __name__ == '__main__':
    unittest.main(verbosity=2)
