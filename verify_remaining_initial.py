"""The final nine catalog entries need source-bound, bounded local inputs."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_operations as ho, sim_clock

IDS = {'LM03-chishui', 'LM05-dadu', 'LM06-maogong', 'LM08-lazikou',
       'LM09-red25', 'LM11-baizhang', 'LM12-wumeng', 'LM15-reunion', 'CP01-changping'}


class RemainingInitialTests(unittest.TestCase):
    def test_catalog_has_no_missing_profiles_but_does_not_claim_complete_facts(self):
        rows = hi.catalog()
        self.assertEqual(len(rows), 45)
        self.assertTrue(all(r['status'] == 'profiled' for r in rows))
        found = set()
        for row in rows:
            d = hi.definition(row['battle'])
            if d['id'] not in IDS:
                continue
            found.add(d['id'])
            self.assertFalse(d['coverage']['opening_deployment_complete'])
            self.assertFalse(d['coverage']['strength_complete'])
            self.assertTrue(hi.validate_definition(d))
            for u in d['units']:
                self.assertIsNone(u['facts']['position']['value'])
                self.assertIsNone(u['facts']['personnel']['value'])
        self.assertEqual(found, IDS)

    def test_local_phases_have_goals_sources_and_identical_three_mode_facts(self):
        from backend.scenario_builder import historical_basis
        for row in hi.catalog():
            d = hi.definition(row['battle'])
            if d['id'] not in IDS:
                continue
            basis = historical_basis(row['battle'])
            self.assertTrue(basis['ready'], basis['error'])
            for phase in d['phases']:
                if phase['id'] == 'campaign_reference':
                    continue
                with self.subTest(profile=d['id'], phase=phase['id']):
                    w = hi.initial(row['battle'], phase['id'])
                    s = w['historical_initial']
                    self.assertTrue(ho.partition(s))
                    self.assertTrue(ho.objective_guidance(s)['not_covered'])
                    for purpose in ('analysis', 'historical', 'synthetic'):
                        for engine in ('afsim', 'narrative'):
                            self.assertEqual(hi.initial(row['battle'], phase['id'], purpose=purpose, engine=engine), w)
                    self.assertEqual(hi.restore(copy.deepcopy(s)), w)

    def test_explicit_estimates_are_executable_and_preserve_facts(self):
        from tools.qa.remaining_initial_fixture import cases, inputs
        from gentactix import missions
        for battle, phase in cases():
            with self.subTest(battle=battle, phase=phase):
                s, p = inputs(battle, phase)
                frozen = copy.deepcopy((s, p))
                world = ho.initial(s, p)
                self.assertTrue(missions.validate(world))
                self.assertEqual((s, p), frozen)
                self.assertEqual(world['historical_initial'], s)
                self.assertEqual(len(list(missions.units(world))), len(p['actors']))

    def test_bce_uses_relative_clock_without_fabricating_a_gregorian_date(self):
        from tools.qa.remaining_initial_fixture import inputs
        s, p = inputs('长平之战', 'encirclement')
        world = ho.initial(s, p)
        sim_clock.initialize(world)
        label, clock = sim_clock.target(world, '30分钟')
        self.assertIsNone(clock['origin_iso'])
        self.assertEqual(clock['elapsed_seconds'], 1800)
        self.assertIn('公元前260年', label)
        bad = copy.deepcopy(p)
        bad['clock']['start'] = '0260-09-01 06:00'
        with self.assertRaises(ValueError):
            ho.initial(s, bad)


if __name__ == '__main__':
    unittest.main()
