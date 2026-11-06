"""Korean first-campaign source identities, scope and arrival regressions."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_operations as ho

BATTLE = '抗美援朝-第一次战役-1950.10.25至1950.11.05'


class KoreanInitialTests(unittest.TestCase):
    def test_first_campaign_has_sources_without_claiming_complete_history(self):
        value = hi.definition(BATTLE)
        self.assertEqual(value['id'], 'KW01-first')
        self.assertTrue(hi.validate_definition(value))
        self.assertGreater(len(value['units']), 40)
        self.assertFalse(value['coverage']['order_of_battle_complete'])
        self.assertFalse(value['coverage']['strength_complete'])
        self.assertTrue(all(u['facts']['personnel']['value'] is None for u in value['units']))
        self.assertTrue(all(u['facts']['position']['value'] is None for u in value['units']))

    def test_opening_does_not_import_all_campaign_forces(self):
        snapshot = hi.initial(BATTLE, 'liangshuidong_opening')['historical_initial']
        self.assertEqual(set(ho.partition(snapshot)), {'kw.cn.regiment354', 'kw.rok.regiment2.battalion3'})
        template = ho.configuration_template(snapshot)
        self.assertEqual(template['rules']['era'], 'korea')
        self.assertEqual(set(template['actors']), set(ho.partition(snapshot)))
        self.assertTrue(all(u['personnel'] is None for u in template['actors'].values()))
        for identity in ('kw.cn.regiment353', 'kw.rok.regiment2.battalion1', 'kw.rok.regiment2.battalion2'):
            unit = next(u for u in snapshot['definition']['units'] if u['id'] == identity)
            presence = next(r for r in unit['presence'] if r['phase_id'] == snapshot['phase_id'])
            self.assertEqual(presence['status'], 'later_participant')

    def test_unsan_keeps_real_us_battalions_artillery_and_attached_tanks(self):
        snapshot = hi.initial(BATTLE, 'unsan_evening')['historical_initial']
        selected = set(ho.partition(snapshot))
        self.assertEqual(selected, {'kw.cn.division115', 'kw.cn.division116', 'kw.cn.division117',
            'kw.us.cavalry8.battalion1', 'kw.us.cavalry8.battalion2', 'kw.us.cavalry8.battalion3',
            'kw.rok.regiment15', 'kw.us.artillery99.battery_c', 'kw.us.tank70.company_b.attached_platoon'})
        self.assertNotIn('kw.us.cavalry_regiment8', selected)
        self.assertNotIn('kw.us.cavalry_division1', selected)
        self.assertNotIn('kw.rok.regiment12', selected)
        self.assertIn('70', str(snapshot['definition']['sources']))
        self.assertIn('第9', str(snapshot['definition']['coverage']['notes']))

    def test_whole_campaign_roster_is_not_a_deployed_initial_state(self):
        snapshot = hi.initial(BATTLE)['historical_initial']
        self.assertEqual(snapshot['phase_id'], 'campaign_reference')
        with self.assertRaisesRegex(ValueError, '参战尚未核定'):
            ho.partition(snapshot)

    def test_all_purposes_and_executors_pin_the_same_source_facts(self):
        expected = hi.initial(BATTLE, 'liangshuidong_opening')
        for purpose in ('analysis', 'historical', 'synthetic'):
            for engine in ('narrative', 'afsim'):
                self.assertEqual(hi.initial(BATTLE, 'liangshuidong_opening', purpose=purpose, engine=engine), expected)
        # The fact factory alone does not certify the product's numerical or
        # synthetic initialization path.
        self.assertFalse(hi.readiness(expected)['ready_for_process_simulation'])

    def test_frozen_first_campaign_snapshot_restores_without_latest_catalog(self):
        from unittest.mock import patch
        world = hi.initial(BATTLE, 'unsan_evening')
        with patch.object(hi, 'definition', side_effect=AssertionError('No latest dependency')):
            self.assertEqual(hi.restore(copy.deepcopy(world['historical_initial'])), world)

    def test_opening_cannot_start_before_the_bound_source_window(self):
        from tools.qa.korean_first_fixture import inputs
        snapshot, parameters = inputs()
        self.assertTrue(ho.initial(snapshot, parameters))
        parameters['clock']['start'] = '1950-10-25 09:50'
        with self.assertRaisesRegex(ValueError, '计算窗口'):
            ho.initial(snapshot, parameters)

    def test_optional_window_start_is_validated_without_breaking_old_snapshots(self):
        value = hi.definition(BATTLE)
        phase = next(p for p in value['phases'] if p['id']=='liangshuidong_opening')
        self.assertEqual(phase['execution_window']['start'], '1950-10-25T10:20')
        for start in ('1950-10-25T12:01', '1950-10-25T10:20+08:00', 'not-a-date'):
            bad = copy.deepcopy(value)
            next(p for p in bad['phases'] if p['id']==phase['id'])['execution_window']['start'] = start
            with self.assertRaises(ValueError):
                hi.validate_definition(bad)
        phase['execution_window'].pop('start')
        self.assertTrue(hi.validate_definition(value))
        for window in (None, [], '1950-10-25'):
            bad = copy.deepcopy(value)
            next(p for p in bad['phases'] if p['id']==phase['id'])['execution_window'] = window
            with self.assertRaises(ValueError):
                hi.validate_definition(bad)

    def test_phase_region_prevents_confusing_old_unsan_with_onjong(self):
        from tools.qa.korean_first_fixture import inputs
        from gentactix import anchors
        snapshot, parameters = inputs()
        self.assertTrue(ho.initial(snapshot, parameters))
        # Both locations belong to the campaign; that alone is insufficient
        # to deploy an Onjong engagement at the old Unsan city.
        old_city = anchors.collect_available_nodes(BATTLE,battle=BATTLE)['抗美援朝-西线-云山旧城']
        parameters['area']['center']={'lat':old_city[0],'lng':old_city[1]}
        parameters['area']['radius_km']=40
        with self.assertRaisesRegex(ValueError, '阶段地域'):
            ho.initial(snapshot, parameters)


if __name__ == '__main__':
    unittest.main()
