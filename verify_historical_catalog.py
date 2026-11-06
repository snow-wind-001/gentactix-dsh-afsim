"""Source-bound local phases for the previously missing WW2 catalog entries."""
import unittest

from gentactix import historical_initial as history, historical_operations as operations


EXPECTED = {
    'AJ01-shanghai': 'city_aug13',
    'AJ02-taiyuan': 'xinkou_oct13',
    'AJ08-changsha1': 'xinqiang_sep18',
    'AJ09-changsha2': 'dayun_sep7',
    'AJ10-changsha3': 'city_jan1',
    'AJ11-kunlun': 'kunlun_dec18',
    'AJ12-ichigo': 'hengyang_june28',
    'AJ13-hengyang': 'zhangjiashan_june28',
    'AJ14-hundred': 'shinaoshan_aug21',
    'AJ16-counter1944': 'gaogou_apr19',
    'AJ17-cheqiao': 'cheqiao_mar5',
    'AJ19-burma': 'songshan_june4',
    'AJ20-reception': 'zhangjiakou_aug20',
}


def records():
    return {r['profile_id']: r['battle'] for r in history.catalog()
            if r['status'] == 'profiled' and r['profile_id'] in EXPECTED}


class HistoricalCatalogTests(unittest.TestCase):
    def test_all_twenty_ww2_entries_have_a_source_roster(self):
        rows = [r for r in history.catalog() if r['battle'].startswith('抗日战争-')]
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(r['status'] == 'profiled' for r in rows))
        self.assertEqual(set(records()), set(EXPECTED))

    def test_each_new_slice_has_both_sides_and_explicit_model_limits(self):
        by_id = records()
        self.assertEqual(len(by_id), 13)
        for identity, phase_id in EXPECTED.items():
            with self.subTest(profile=identity):
                snapshot = history.initial(by_id[identity], phase_id)['historical_initial']
                selected = operations.partition(snapshot)
                units = {u['id']: u for u in snapshot['definition']['units']}
                self.assertEqual({units[u]['team'] for u in selected}, {'red', 'blue'})
                phase = next(p for p in snapshot['definition']['phases'] if p['id'] == phase_id)
                self.assertEqual(phase['execution_window']['kind'], 'model_scope_limit')
                self.assertIn('假设', phase['execution_window']['note'])
                self.assertEqual(phase['geographic_scope']['kind'], 'model_scope_limit')
                self.assertFalse(snapshot['definition']['coverage']['order_of_battle_complete'])

    def test_unknown_counts_equipment_and_positions_remain_unknown(self):
        self.assertEqual(len(records()), 13)
        for battle in records().values():
            definition = history.definition(battle)
            self.assertTrue(history.validate_definition(definition))
            for unit in definition['units']:
                self.assertTrue(unit['evidence'])
                self.assertTrue(all(f['value'] is None for f in unit['facts'].values()))
            self.assertTrue(all(not s['original_archive_examined'] for s in definition['sources'].values()))

    def test_later_reinforcements_and_remote_actions_are_not_opening_actors(self):
        checks = {
            'AJ01-shanghai': {'ww2.cn.division36', 'ww2.jp.division3', 'ww2.jp.division11'},
            'AJ02-taiyuan': {'ww2.cn.regiment769'},
            'AJ08-changsha1': {'ww2.jp.division33', 'ww2.jp.division101'},
            'AJ11-kunlun': {'ww2.cn.division159'},
            'AJ17-cheqiao': {'ww2.cn.regiment52'},
            'AJ19-burma': {'ww2.cn.corps8'},
        }
        by_id = records()
        for identity, excluded in checks.items():
            with self.subTest(profile=identity):
                snapshot = history.initial(by_id[identity], EXPECTED[identity])['historical_initial']
                self.assertTrue(excluded.isdisjoint(operations.partition(snapshot)))
                self.assertTrue(excluded <= {u['id'] for u in snapshot['definition']['units']})

    def test_anonymous_garrisons_do_not_receive_invented_regiment_numbers(self):
        by_id = records()
        for identity, name in [('AJ13-hengyang', '日军张家山攻击部队（下级番号未核）'),
                               ('AJ19-burma', '日军松山守备队（下级番号未核）')]:
            definition = history.definition(by_id[identity])
            self.assertIn(name, {u['name'] for u in definition['units']})
        shanghai = history.definition(by_id['AJ01-shanghai'])
        marine = next(u for u in shanghai['units'] if u['id'] == 'ww2.jp.shanghai_marines')
        self.assertEqual(marine['role'], 'formation')

    def test_year_conflict_is_recorded_instead_of_silently_used_as_an_order(self):
        definition = history.definition(records()['AJ16-counter1944'])
        notes = ' '.join(definition['coverage']['notes'])
        self.assertIn('1943', notes)
        self.assertIn('1944', notes)
        self.assertIn('冲突', notes)
        phase = next(p for p in definition['phases'] if p['id'] == 'gaogou_apr19')
        self.assertEqual(phase['date']['label'], '1944-04-19')

    def test_changsha_source_precision_does_not_turn_detachments_into_whole_divisions(self):
        by_id = records()
        first = history.initial(by_id['AJ08-changsha1'], 'xinqiang_sep18')['historical_initial']
        self.assertNotIn('ww2.jp.division13', operations.partition(first))
        self.assertIn('奈良', ' '.join(first['definition']['coverage']['notes']))
        second = history.initial(by_id['AJ09-changsha2'], 'dayun_sep7')['historical_initial']
        self.assertIn('ww2.cn.corps4.dayun', operations.partition(second))
        self.assertNotIn('ww2.cn.corps40', operations.partition(second))
        self.assertTrue(any('tjpress.com' in s['url'] for s in second['definition']['sources'].values()))

    def test_same_source_roster_for_three_purposes_and_two_engines(self):
        self.assertEqual(len(records()), 13)
        for identity, battle in records().items():
            expected = history.initial(battle, EXPECTED[identity])
            for purpose in ('analysis', 'historical', 'synthetic'):
                for engine in ('narrative', 'afsim'):
                    self.assertEqual(history.initial(battle, EXPECTED[identity], purpose=purpose, engine=engine), expected)

    def test_builder_exposes_real_units_and_task_guidance_without_teaching_seed(self):
        from backend.scenario_builder import historical_basis
        for identity, battle in records().items():
            with self.subTest(profile=identity):
                basis = historical_basis(battle, EXPECTED[identity])
                self.assertTrue(basis['ready'], basis['error'])
                template = basis['configuration_template']
                self.assertTrue(all(u['personnel'] is None for u in template['actors'].values()))
                guidance = operations.objective_guidance(basis['initial'])
                self.assertIsNotNone(guidance)
                self.assertTrue(guidance['sources'])
                self.assertTrue(guidance['not_covered'])


if __name__ == '__main__':
    unittest.main()
