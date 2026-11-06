"""Dedicated WWII battle entries must bind sourced, phase-specific forces."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_operations as ho
from backend import scenario_builder

TAIERZHUANG = '抗日战争-台儿庄战役-1938.03.23至1938.04.07'
WANJIALING = '抗日战争-万家岭战役-1938.09下旬至1938.10'


class WWIIInitialTests(unittest.TestCase):
    def test_dedicated_taierzhuang_entry_has_an_executable_opening_phase(self):
        basis = scenario_builder.historical_basis(TAIERZHUANG)
        self.assertTrue(basis['ready'], basis['error'])
        self.assertEqual({u['id'] for u in basis['actors']},
                         {'ww2.cn.division31','ww2.jp.seya_detachment'})
        self.assertEqual(basis['initial']['definition']['battle'], TAIERZHUANG)
        self.assertNotEqual(basis['initial']['profile_id'], 'AJ04-xuzhou')

    def test_taierzhuang_keeps_late_relief_outside_initial_city_contact(self):
        value = hi.definition(TAIERZHUANG)
        snapshot = hi.initial(TAIERZHUANG, 'urban_opening')['historical_initial']
        row = next(u for u in value['units'] if u['id']=='ww2.jp.sakamoto_detachment')
        self.assertEqual(next(p['status'] for p in row['presence'] if p['phase_id']==snapshot['phase_id']), 'later_participant')
        self.assertNotIn(row['id'], ho.partition(snapshot))
        # Historical facts retain the same canonical identities in the parent
        # campaign without forcing the parent to use the child's date/window.
        parent = hi.definition('抗日战争-徐州会战总览-1938.01至1938.05')
        self.assertTrue({u['id'] for u in value['units']} <= {u['id'] for u in parent['units']})

    def test_wanjialing_attack_does_not_merge_relief_and_encircled_forces(self):
        basis = scenario_builder.historical_basis(WANJIALING)
        self.assertTrue(basis['ready'], basis['error'])
        self.assertEqual({u['id'] for u in basis['actors']},
                         {'ww2.cn.army4','ww2.cn.army66','ww2.cn.army74','ww2.jp.division106'})
        self.assertTrue({'ww2.cn.army32','ww2.jp.division27'} <= {u['id'] for u in basis['excluded_references']})
        self.assertEqual(basis['phase']['date']['label'], '1938-10-07')

    def test_both_profiles_leave_unknown_numbers_unknown_and_freeze_sources(self):
        for battle in (TAIERZHUANG, WANJIALING):
            with self.subTest(battle=battle):
                record = hi.definition(battle)
                self.assertTrue(hi.validate_definition(record))
                self.assertFalse(record['coverage']['order_of_battle_complete'])
                self.assertTrue(all(f['value'] is None for u in record['units'] for f in u['facts'].values()))
                world = hi.initial(battle)
                with patch.object(hi,'definition',side_effect=AssertionError('latest data must not replace the frozen snapshot')):
                    self.assertEqual(hi.restore(copy.deepcopy(world['historical_initial'])), world)

    def test_default_phase_scopes_have_explicit_model_windows_and_regions(self):
        from gentactix import anchors
        for battle, node in ((TAIERZHUANG,'抗日战争-台儿庄'), (WANJIALING,'抗日战争-磨溪乡')):
            definition = hi.definition(battle)
            p = scenario_builder.historical_basis(battle)['phase']
            self.assertEqual(p['execution_window']['kind'], 'model_scope_limit')
            self.assertIn('假设', p['execution_window']['note'])
            self.assertEqual(p['geographic_scope']['kind'], 'model_scope_limit')
            self.assertIn('参考', p['geographic_scope']['note'])
            self.assertEqual(definition['sources']['GEO']['url'], anchors.node_metadata(node)['source_url'])
            self.assertEqual(list(p['geographic_scope']['center'].values()), anchors.node_metadata(node)['coordinates'])

    def test_wanjialing_reference_does_not_place_the_battle_at_the_county_memorial(self):
        basis = scenario_builder.historical_basis(WANJIALING)
        self.assertEqual(basis['geographic_scope']['center'], {'lat':29.365246,'lng':115.581335})
        self.assertLess(basis['geographic_scope']['radius_km'], 16)
        self.assertTrue(any(p['name']=='抗日战争-磨溪乡' for p in basis['geo_references']))
        self.assertIn('非战术阵地', next(p['metadata']['kind'] for p in basis['geo_references'] if p['name']=='抗日战争-磨溪乡'))

    def test_all_purposes_and_executors_use_the_same_source_identity_graph(self):
        for battle in (TAIERZHUANG, WANJIALING):
            expected = hi.initial(battle)
            for purpose in ('analysis','historical','synthetic'):
                for engine in ('narrative','afsim'):
                    self.assertEqual(hi.initial(battle,purpose=purpose,engine=engine), expected)

    def test_reference_factory_keeps_campaign_scope_and_builder_explains_selected_local_phase(self):
        for battle in (TAIERZHUANG, WANJIALING):
            self.assertEqual(hi.initial(battle)['historical_initial']['phase_id'], 'campaign_reference')
            basis = scenario_builder.historical_basis(battle)
            self.assertTrue(basis['ready'])
            self.assertNotEqual(basis['initial']['phase_id'], 'campaign_reference')
            self.assertIn('默认选择', basis['scope'])
            self.assertFalse(scenario_builder.historical_basis(battle, 'campaign_reference')['ready'])


if __name__=='__main__':
    unittest.main()
