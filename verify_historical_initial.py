"""Historical OOB identity, provenance and version-pinned baseline contracts."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class HistoricalInitialTests(unittest.TestCase):
    ZHILUO = '红军长征-直罗镇战役-1935.11.20至1935.11.24'

    def test_zhiluo_has_sourced_corps_and_divisions_without_invented_strength(self):
        from gentactix import historical_initial as h
        value = h.definition(self.ZHILUO)
        self.assertTrue(h.validate_definition(value))
        self.assertFalse(any(value['coverage'][k] for k in ('order_of_battle_complete', 'opening_deployment_complete', 'strength_complete')))
        self.assertTrue({'红1军团', '红15军团', '东北军第109师', '东北军第106师', '东北军第111师', '东北军第117师'} <= {u['name'] for u in value['units']})
        self.assertTrue(all(f['value'] is None for u in value['units'] for f in u['facts'].values()))

    def test_zhiluo_first_attack_does_not_deploy_relief_forces_early(self):
        from gentactix import historical_initial as h, historical_operations as o
        snapshot = h.initial(self.ZHILUO, 'first_attack')['historical_initial']
        self.assertEqual(set(o.partition(snapshot)), {'lm.red.corps1', 'lm.red.corps15', 'lm.ne.division109'})
        for unit in snapshot['definition']['units']:
            if unit['id'] in {'lm.ne.division106', 'lm.ne.division111', 'lm.ne.division117'}:
                self.assertEqual(next(p['status'] for p in unit['presence'] if p['phase_id']=='first_attack'), 'later_participant')
        template = o.configuration_template(snapshot)
        self.assertEqual(template['rules']['era'], 'long_march')
        self.assertTrue(all(u['personnel'] is None for u in template['actors'].values()))

    def test_zhiluo_window_and_region_are_model_limits_not_exact_historical_points(self):
        from gentactix import historical_initial as h
        phase = next(p for p in h.definition(self.ZHILUO)['phases'] if p['id']=='first_attack')
        self.assertEqual(phase['date']['label'], '1935-11-21')
        self.assertEqual(phase['execution_window']['kind'], 'model_scope_limit')
        self.assertIn('假设', phase['execution_window']['note'])
        self.assertEqual(phase['geographic_scope']['kind'], 'model_scope_limit')
        self.assertIn('参考', phase['geographic_scope']['note'])

    def test_zhiluo_facts_are_the_same_for_every_purpose_and_executor(self):
        from gentactix import historical_initial as h
        expected = h.initial(self.ZHILUO, 'first_attack')
        for purpose in ('analysis','historical','synthetic'):
            for engine in ('narrative','afsim'):
                self.assertEqual(h.initial(self.ZHILUO, 'first_attack', purpose=purpose, engine=engine), expected)
        self.assertFalse(h.readiness(expected)['ready_for_process_simulation'])

    def test_wuhan_is_a_sourced_historical_structure_not_two_teaching_proxies(self):
        from gentactix import historical_initial as h
        value=h.definition('抗日战争-武汉会战-1938.06至1938.10')
        names={u['name'] for u in value['units']}
        self.assertTrue({'第五战区司令部','第九战区司令部','日军第2军','日军第11军'}<=names)
        self.assertNotIn('武汉外围中国陆军与中苏航空力量',names)
        self.assertFalse(value['coverage']['order_of_battle_complete'])
        self.assertTrue(all(u['evidence'] for u in value['units']))

    def test_unknown_strength_and_positions_are_not_filled_with_teaching_values(self):
        from gentactix import historical_initial as h
        value=h.initial('抗日战争-武汉会战-1938.06至1938.10')
        self.assertNotIn('mission',value);self.assertNotIn('combined_arms',value)
        for u in value['red_units']+value['blue_units']:
            self.assertIsNone(u['personnel']['current'])
            self.assertIsNone(u['lat']);self.assertIsNone(u['lng'])
            self.assertNotIn('hp',u)
            self.assertTrue(u['historical_unit_id'])

    def test_baseline_is_independent_of_purpose_and_execution_engine(self):
        from gentactix import historical_initial as h
        values=[h.initial('抗日战争-武汉会战-1938.06至1938.10',purpose=p,engine=e)
            for p in ('analysis','historical','synthetic') for e in ('narrative','afsim')]
        self.assertTrue(all(v==values[0] for v in values))

    def test_invalid_identity_parentage_and_unsourced_facts_are_rejected(self):
        from gentactix import historical_initial as h
        original=h.definition('抗日战争-武汉会战-1938.06至1938.10')
        for kind in ('duplicate','parent_cycle','fake_strength','unknown_source'):
            value=copy.deepcopy(original)
            if kind=='duplicate':value['units'].append(copy.deepcopy(value['units'][0]))
            if kind=='parent_cycle':value['units'][0]['parent_id']=value['units'][0]['id']
            if kind=='fake_strength':value['units'][0]['facts']['personnel']={'value':3000,'evidence':[]}
            if kind=='unknown_source':value['units'][0]['evidence']=[{'source_id':'invented','locator':'x'}]
            with self.subTest(kind=kind),self.assertRaises(ValueError):h.validate_definition(value)

    def test_frozen_definition_is_self_contained_and_tamper_evident(self):
        from gentactix import historical_initial as h
        world=h.initial('抗日战争-武汉会战-1938.06至1938.10');h.validate_initial(world)
        changed=copy.deepcopy(world);changed['red_units'][0]['name']='替换成教学部队'
        with self.assertRaises(ValueError):h.validate_initial(changed)
        with tempfile.TemporaryDirectory() as folder:
            prior=h.DATA_ROOT
            try:
                h.DATA_ROOT=Path(folder)
                h.validate_initial(world)
            finally:h.DATA_ROOT=prior

    def test_jizhong_units_are_individually_identified_with_sourced_parentage(self):
        from gentactix import historical_initial as h
        record=h.definition('抗日战争-冀中五一反扫荡-1942.05.01至1942.06.20')
        units={u['id']:u for u in record['units']};names={u['name']:u for u in units.values()}
        self.assertIn('冀中军区第7军分区第22团',names)
        unit=names['冀中军区第7军分区第22团']
        self.assertEqual(units[unit['parent_id']]['name'],'冀中军区第7军分区')
        self.assertGreater(len(units),20)

    def test_catalog_reports_all_battles_without_claiming_missing_profiles_complete(self):
        from gentactix import adjudication_lib, historical_initial as h
        rows=h.catalog()
        self.assertEqual({r['battle'] for r in rows},set(adjudication_lib.list_battles()))
        self.assertEqual(len(rows),45)
        self.assertTrue(all(r['status']=='profiled' for r in rows))
        self.assertTrue(any(not h.definition(r['battle'])['coverage']['strength_complete'] for r in rows))
        for row in rows:
            if row['status']=='profiled':
                self.assertTrue(h.validate_definition(h.definition(row['battle'])))

    def test_march_participants_are_not_asserted_present_in_january(self):
        from gentactix import historical_initial as h
        battle='抗日战争-徐州会战总览-1938.01至1938.05'
        january=h.initial(battle)
        march=h.initial(battle,'taierzhuang')
        self.assertEqual([u['historical_unit_id'] for u in january['red_units']],
                         [u['historical_unit_id'] for u in march['red_units']])
        self.assertTrue(all(u['historical_presence']=='unverified' for u in january['red_units']))
        self.assertEqual(next(u for u in march['red_units'] if u['name']=='第31师')['historical_presence'],'reported_present')

    def test_date_resolution_cannot_create_a_precise_hour(self):
        from gentactix import historical_initial as h
        world=h.initial('抗日战争-武汉会战-1938.06至1938.10')
        self.assertEqual(world['current_time'],'1938年6月')
        self.assertNotIn('08:00',world['current_time'])

    def test_missing_phase_and_unsupported_modes_are_rejected(self):
        from gentactix import historical_initial as h
        battle='抗日战争-武汉会战-1938.06至1938.10'
        for kwargs in ({'phase_id':'invented'},{'purpose':'open'},{'engine':'other'},{'version':'../index'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                h.initial(battle,**kwargs)

    def test_corrupt_index_cannot_escape_data_directory_or_hide_duplicates(self):
        import json
        from gentactix import historical_initial as h
        battle='抗日战争-武汉会战-1938.06至1938.10'
        original={'battle':battle,'id':'AJ06-wuhan','default_version':'1.0.0'}
        with tempfile.TemporaryDirectory() as folder, patch.object(h,'DATA_ROOT',Path(folder)):
            for rows in ([{**original,'id':'../private'}],[original,original],[{**original,'battle':'invented'}]):
                (Path(folder)/'index.json').write_text(json.dumps({'profiles':rows}))
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    h.catalog()

    def test_invalid_types_nonfinite_coordinates_and_cross_side_parent_are_rejected(self):
        from gentactix import historical_initial as h
        original=h.definition('抗日战争-武汉会战-1938.06至1938.10')
        for kind in ('cross_side','bool_count','nan_position','source_type','invalid_phase_id'):
            value=copy.deepcopy(original)
            if kind=='cross_side':value['units'][0]['parent_id']=next(u['id'] for u in value['units'] if u['team']=='blue')
            if kind=='bool_count':value['units'][0]['facts']['personnel']['value']=True
            if kind=='nan_position':
                fact=value['units'][0]['facts']['position']
                fact['value']={'kind':'unit_position','lat':float('nan'),'lng':114,'uncertainty_km':0,'phase_id':value['phases'][0]['id']}
                fact['evidence']=copy.deepcopy(value['units'][0]['evidence'])
            if kind=='source_type':next(iter(value['sources'].values()))['title']=3
            if kind=='invalid_phase_id':value['phases'][0]['id']=[]
            with self.subTest(kind=kind), self.assertRaises(ValueError):h.validate_definition(value)

    def test_readiness_separates_roster_facts_from_simulatable_units(self):
        from gentactix import historical_initial as h
        report=h.readiness(h.initial('抗日战争-冀中五一反扫荡-1942.05.01至1942.06.20'))
        self.assertGreater(report['roster_count'],20)
        self.assertEqual(report['located_unit_count'],0)
        self.assertEqual(report['unknown_position_count'],report['roster_count'])
        self.assertFalse(report['ready_for_process_simulation'])
        self.assertIn('缺少本阶段可核部署',report['missing'])


if __name__=='__main__':unittest.main()
