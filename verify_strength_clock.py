"""Past labour/food intervals must use the people alive during that interval."""
import copy
import unittest

from gentactix import strength_clock as clock


def unit():
    return {'personnel': {'current': 100, 'committed': 100,
                          'casualties': 0, 'noncombat_losses': 0}}


def events():
    return [{'at_ms': 0, 'combat_current': 100},
            {'at_ms': 10000, 'combat_current': 75},
            {'at_ms': 20000, 'combat_current': 60}]


def segments():
    return [{'start_ms': start, 'end_ms': start+10000, 'people': people,
             'noncombat_delta': loss} for start, people, loss in
            [(0, 100, 2), (10000, 73, 1), (20000, 57, 0)]]


class StrengthClockTests(unittest.TestCase):
    def test_only_next_interval_uses_a_death_at_the_boundary(self):
        result = clock.validate(unit(), 30, segments(), events(), final_current=57)
        self.assertEqual(result['person_milliseconds'], '2300000')
        self.assertEqual(result['final_current'], 57)

    def test_clock_at_endpoint_changes_final_people_without_retroactive_work(self):
        e = events()+[{'at_ms': 30000, 'combat_current': 20}]
        r = clock.validate(unit(), 30, segments(), e, final_current=17)
        self.assertEqual(r['person_milliseconds'], '2300000')

    def test_accepted_food_arithmetic_cannot_hide_retroactive_casualties(self):
        s = segments(); s[0]['people'] = 75
        with self.assertRaisesRegex(ValueError, '人数|时钟'):
            clock.validate(unit(), 30, s, events(), final_current=57)

    def test_future_hires_or_alive_dead_labor_are_rejected(self):
        s = segments(); s[1]['people'] = 100
        with self.assertRaises(ValueError):
            clock.validate(unit(), 30, s, events(), final_current=57)

    def test_noncombat_losses_are_applied_after_their_own_interval(self):
        s = segments(); s[0]['people'] = 98
        with self.assertRaises(ValueError):
            clock.validate(unit(), 30, s, events(), final_current=57)

    def test_missing_initial_clock_or_forged_final_accounts_are_rejected(self):
        for e, final in [(events()[1:], 57), (events(), 58)]:
            with self.subTest(e=e, final=final), self.assertRaises(ValueError):
                clock.validate(unit(), 30, segments(), e, final_current=final)

    def test_an_event_inside_a_segment_needs_a_real_segment_boundary(self):
        e = events(); e[1]['at_ms'] = 5000
        with self.assertRaises(ValueError):
            clock.validate(unit(), 30, segments(), e, final_current=57)

    def test_clock_and_intervals_must_cover_one_finite_integer_timeline(self):
        for key, value in [('at_ms', -1), ('at_ms', 10000.5),
                           ('combat_current', True), ('combat_current', float('nan'))]:
            e = events(); e[1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                clock.validate(unit(), 30, segments(), e, final_current=57)
        for e in [events()+[events()[-1]], list(reversed(events())),
                  [dict(events()[0], combat_current=101), *events()[1:]]]:
            with self.subTest(e=e), self.assertRaises(ValueError):
                clock.validate(unit(), 30, segments(), e, final_current=57)

    def test_person_time_uses_exact_decimal_string_beyond_browser_integer_limit(self):
        u = unit(); u['personnel'].update(current=10000000, committed=10000000)
        s = [{'start_ms': 0, 'end_ms': 2678400000,
              'people': 10000000, 'noncombat_delta': 0}]
        r = clock.validate(u, 2678400, s,
                           [{'at_ms': 0, 'combat_current': 10000000}],
                           final_current=10000000)
        self.assertEqual(r['person_milliseconds'], '26784000000000000')

    def test_readonly_summary_never_repairs_receipts_or_world(self):
        u, s, e = unit(), segments(), events(); before = copy.deepcopy((u, s, e))
        result = clock.validate(u, 30, s, e, final_current=57)
        self.assertEqual((u, s, e), before)
        self.assertNotIn('after', result)
        self.assertEqual(result['version'], clock.VERSION)


class NativeStrengthClockTests(unittest.TestCase):
    def setUp(self):
        from backend import afsim_strength_clock
        self.native = afsim_strength_clock
        self.identity = 'g00000000000000000001'
        self.model = {'strength_clock_revision': 1,
                      'units': [('red', {**unit(), 'name': 'QA infantry'})]}
        self.scene = {'seconds': 30, 'entities': {
            self.identity: {'name': 'QA infantry', 'team': 'red'}}}
        self.accounts = {self.identity: {'current': 57}}
        self.segments = {self.identity: segments()}

    def text(self):
        return '\n'.join('GTXSTRENGTH|'+self.identity+'|'+str(e['at_ms'])+'|'+str(e['combat_current'])
                         for e in events())

    def test_native_clock_has_exact_unit_bindings_and_final_accounts(self):
        r = self.native.parse(self.text(), self.model, self.scene,
                              self.accounts, self.segments)
        self.assertEqual(r[self.identity]['person_milliseconds'], '2300000')

    def test_old_models_cannot_claim_new_chronology_receipts(self):
        m = copy.deepcopy(self.model); m.pop('strength_clock_revision')
        with self.assertRaises(ValueError):
            self.native.parse(self.text(), m, self.scene, self.accounts, self.segments)

    def test_combined_parser_cannot_ignore_clock_rows_after_a_model_downgrade(self):
        from backend import afsim_combined
        with self.assertRaisesRegex(ValueError, '兵力时钟'):
            afsim_combined.parse(self.text(), {}, self.scene)

    def test_missing_unknown_duplicate_and_malformed_rows_are_rejected(self):
        for t in ['', self.text()+'\n'+self.text(), self.text().replace(self.identity, 'g'+'2'*20),
                  self.text().replace('|10000|', '|NaN|')]:
            with self.subTest(t=t), self.assertRaises(ValueError):
                self.native.parse(t, self.model, self.scene, self.accounts, self.segments)

    def test_final_loss_ledger_and_all_segment_identities_are_required(self):
        for a, s in [({}, self.segments), (self.accounts, {}),
                     ({self.identity: {'current': 58}}, self.segments)]:
            with self.subTest(a=a, s=s), self.assertRaises(ValueError):
                self.native.parse(self.text(), self.model, self.scene, a, s)

    def test_normal_combined_compiler_requires_shared_clock_for_nutrition(self):
        from verify_scheduled_physical import world
        from verify_continuous_motion_integration import compile_world
        value = world(personnel=True)
        _, _, _, model = compile_world(value, [
            {'unit': u['name'], 'action': 'hold'}
            for side in ('red', 'blue') for u in value[side+'_units']])
        self.assertEqual(model.get('strength_clock_revision'), 1)
        script = model['script']
        self.assertEqual(script.count('script void GtxCombatStrengthRefresh('), 1)
        tick = script.split('execute at_interval_of 10 sec', 1)[1].split('end_execute', 1)[0]
        self.assertLess(tick.index('GtxCMSettle('), tick.index('ca_live_strength_ratio'))
        self.assertGreater(tick.rindex('GtxCombatStrengthRefresh('), tick.index('command_done'))

    def test_legacy_noncontinuous_model_does_not_silently_change_version(self):
        from verify_scheduled_physical import world
        from verify_continuous_motion_integration import compile_world
        from tools.qa.historical_operational_fixture import inputs
        from gentactix import historical_operations
        source, _ = inputs()
        parameters = copy.deepcopy(world()['mission']['definition']['historical_calculation']['parameters'])
        parameters['movement_feedback']['version'] = 'movement-feedback-1'
        value = historical_operations.initial(source, parameters)
        _, _, _, model = compile_world(value, [
            {'unit': u['name'], 'action': 'hold'}
            for side in ('red', 'blue') for u in value[side+'_units']])
        self.assertNotIn('strength_clock_revision', model)
        self.assertNotIn('GtxCombatStrengthRefresh(', model['script'])


if __name__ == '__main__':
    unittest.main()
