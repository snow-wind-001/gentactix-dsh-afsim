"""Scoped Wuhan northern-front sources and dated Wanjialing force statistics."""
import json
from pathlib import Path
import unittest

from gentactix import historical_initial as hi, historical_operations as ho, campaign_windows as cw
from backend import scenario_builder

WH='抗日战争-武汉会战-1938.06至1938.10'
WJL='抗日战争-万家岭战役-1938.09下旬至1938.10'
WINDOW='WH-northern-sep17-18'


class NorthernCampaignTests(unittest.TestCase):
    def test_northern_details_remain_retrievable_without_truncating_required_init_scope(self):
        from gentactix import rag
        hits=rag.search('武汉北线 第71军 第59军',battle=WH,top_k=30)
        self.assertTrue(any(r['section']=='北线分期参战单位与指挥参考'and'第71军'in r['text']and'第59军'in r['text']for r in hits))
        initial=rag.select_passages(rag.search(WH,battle=WH,phase='init',top_k=8),3200)
        required=[r for r in initial if r.get('required')]
        self.assertEqual({r['section']for r in required},{'时间与地点','双方兵力与指挥','争议与待考'})
        self.assertTrue(all(not r['excerpted']for r in required))

    def test_operator_can_explicitly_fix_unknown_convoy_distance_without_filling_actors(self):
        from gentactix import scenario_constraints as constraints
        basis=scenario_builder.historical_basis(WH,'northern_sep17_18',version='1.2.0',force_scope='campaign',
            campaign_window_id=WINDOW,campaign_window_version='1.1.0',termination_mode='objectives',time_step='1小时')
        path=['rules','convoy_km_per_turn']
        self.assertIsNone(basis['configuration_template']['rules']['convoy_km_per_turn'])
        self.assertTrue(any(r['path']==path for r in basis['fixed_parameter_fields']))
        constraints.prepare(basis,[dict(path=path,value=0)])
        self.assertEqual(basis['configuration_template']['rules']['convoy_km_per_turn'],0)
        self.assertTrue(all(r['personnel']is None for r in basis['configuration_template']['actors'].values()))

    def test_new_goal_regions_are_explicit_estimates_visible_before_global_generation(self):
        from backend.scenario_assembly import HistoricalAssembly
        old=cw.load(WINDOW,'1.0.0');new=cw.load(WINDOW,'1.1.0')
        self.assertNotIn('goal_regions',old['parameter_estimates'])
        bounds=new['parameter_estimates']['goal_regions']
        self.assertEqual(set(bounds),{'red_mountain','red_plain','blue_mountain','blue_plain'})
        self.assertGreater(bounds['red_mountain']['center']['lng'],115.5)
        self.assertLess(bounds['red_plain']['center']['lng'],115.5)
        basis=scenario_builder.historical_basis(WH,'northern_sep17_18',version='1.2.0',force_scope='campaign',
            campaign_window_id=WINDOW,campaign_window_version='1.1.0',termination_mode='objectives',time_step='1小时')
        draft=HistoricalAssembly(basis);view=draft.tool('globals','get_scenario_basis',{})
        self.assertEqual(view['readonly_campaign_window']['parameter_estimates']['goal_regions'],bounds)
        self.assertTrue(all(a['personnel']is None for a in draft.configuration['actors'].values()))

    def test_northern_details_precede_the_final_wuhan_withdrawal_in_source_replay(self):
        from gentactix import history_replay
        pack=history_replay.pin(WH)['pack']
        positions={r.get('event_key'):i for i,r in enumerate(pack['events'])if r.get('event_key')}
        withdrawal=next(i for i,r in enumerate(pack['events'])if r['date_label'].startswith('1938-10-25'))
        order=[positions[k]for k in ['WH-Fujin-deployment','WH-Huangchuan-flank','WH-N17-mountain','WH-Shawo-later-contact']]
        self.assertEqual(order,sorted(order))
        self.assertLess(order[-1],withdrawal,'September details must not play after the final October withdrawal')

    def test_missing_convoy_number_identifies_its_path_without_defaulting_to_zero(self):
        from tools.qa.wanjialing_estimate_fixture import inputs
        initial,parameters=inputs();parameters['rules']['convoy_km_per_turn']=None
        with self.assertRaisesRegex(ValueError,r'rules.convoy_km_per_turn.*收到None'):
            ho.initial(initial,parameters)
        self.assertIsNone(parameters['rules']['convoy_km_per_turn'])
        parameters['rules']['convoy_km_per_turn']=0
        self.assertIsNotNone(ho.initial(initial,parameters)['mission'])

    def test_canonical_army_figures_keep_their_dates_and_loss_classes(self):
        records=json.loads(Path('data/anti_japanese_war/scenarios.json').read_text())['scenarios']
        s=next(s for s in records if s['id']=='AJ07')
        figures={r.get('figure_key'):r for r in s['figures']}
        for key,number,date in [('WJL-M-66-participants',8815,'1938-10-07'),
                                ('WJL-M-66-casualties',3613,'1938-10-12'),
                                ('WJL-M-74-participants',18998,'1938-09-30'),
                                ('WJL-M-74-losses',9504,'1938-10-15')]:
            self.assertIn(key,figures)
            self.assertEqual(figures[key]['value'],number)
            self.assertIn(date,figures[key]['scope'])
            self.assertIn('A_WJL_GUO',figures[key]['source_locator'])
            self.assertIn('不是',figures[key]['note'])
        self.assertIn('生死不明',figures['WJL-M-74-losses']['metric'])
        self.assertNotIn('阵亡',figures['WJL-M-74-losses']['metric'])

    def test_canonical_northern_events_have_the_same_sources_and_reference_roles(self):
        records=json.loads(Path('data/anti_japanese_war/scenarios.json').read_text())['scenarios']
        s=next(s for s in records if s['id']=='AJ06')
        d=hi.definition(WH,'1.2.0')
        events={r.get('event_key'):r for r in s['events']}
        for p in d['phases']:
            for operation in p.get('operations',[]):
                if not operation['id'].startswith('WH-'):continue
                self.assertIn(operation['id'],events)
                self.assertEqual(events[operation['id']]['event'],operation['description'])
                self.assertTrue(events[operation['id']]['source_locator'])
        refs={r.get('historical_unit_id'):r for r in s['forces']}
        self.assertIn('指挥',refs['ww2.cn.group2']['description'])
        self.assertIn('未知',refs['ww2.cn.division61']['description'])
        sources=json.loads(Path('data/anti_japanese_war/sources.json').read_text())['sources']
        for key,issue in [('WH_ZX_DABIE7','第7期'),('WH_ZX_DABIE8','第8期')]:
            self.assertIn(issue,sources[key]['publisher'])
            self.assertFalse(sources[key]['original_archive_examined'])

    def test_wanjialing_dated_army_reports_do_not_become_opening_unit_strength(self):
        d=hi.definition(WJL,'1.5.0')
        rows={r['id']:r for p in d['phases'] for r in p.get('measurements',[])}
        expected={'WJL-M-66-participants':8815,'WJL-M-66-casualties':3613,
                  'WJL-M-74-participants':18998,'WJL-M-74-losses':9504}
        for identity,value in expected.items():
            self.assertEqual(rows[identity]['quantity']['lower'],value)
            self.assertEqual(rows[identity]['quantity']['upper'],value)
            self.assertEqual(rows[identity]['date']['precision'],'range')
        self.assertEqual(rows['WJL-M-66-participants']['unit_ids'],['ww2.cn.army66'])
        self.assertEqual(rows['WJL-M-74-participants']['unit_ids'],['ww2.cn.army74'])
        self.assertIn('生死不明',rows['WJL-M-74-losses']['population'])
        self.assertIn('1938-10-07',rows['WJL-M-66-participants']['date']['label'])
        self.assertIn('1938-10-15',rows['WJL-M-74-participants']['date']['label'])
        self.assertTrue(all(u['facts']['personnel']['value'] is None for u in d['units']))

    def test_wuhan_north_records_actual_armies_and_detachments_separately(self):
        d=hi.definition(WH,'1.2.0');units={u['id']:u for u in d['units']}
        for name in ['ww2.cn.army71','ww2.cn.army59','ww2.cn.army30','ww2.cn.army42','ww2.cn.army51',
                     'ww2.cn.division38','ww2.cn.division180','ww2.jp.division16',
                     'ww2.jp.shinohara_detachment','ww2.jp.okada_detachment']:
            self.assertIn(name,units)
        self.assertEqual(units['ww2.jp.shinohara_detachment']['parent_id'],'ww2.jp.division16')
        self.assertEqual(units['ww2.jp.okada_detachment']['parent_id'],'ww2.jp.division10')
        self.assertIsNone(units['ww2.cn.division61']['parent_id'])
        self.assertIsNone(units['ww2.cn.division113']['parent_id'])
        self.assertTrue(all(u['facts']['personnel']['value'] is None for u in units.values()))

    def test_northern_window_selects_two_directions_without_headquarters_or_double_counts(self):
        basis=scenario_builder.historical_basis(WH,'northern_sep17_18',version='1.2.0',
            force_scope='campaign',campaign_window_id=WINDOW,campaign_window_version='1.0.0',
            termination_mode='objectives',time_step='1小时')
        self.assertTrue(basis['ready'],basis.get('error'))
        ids=set(basis['configuration_template']['actors'])
        self.assertEqual(ids,{'ww2.cn.army71','ww2.cn.army30','ww2.cn.army42','ww2.cn.army51',
                             'ww2.cn.division38','ww2.cn.division180','ww2.jp.division10','ww2.jp.shinohara_detachment'})
        self.assertNotIn('ww2.cn.army59',ids)
        self.assertNotIn('ww2.jp.division16',ids)
        self.assertNotIn('ww2.jp.okada_detachment',ids)
        self.assertTrue(all(r['personnel'] is None for r in basis['configuration_template']['actors'].values()))
        goals=basis['configuration_template']['campaign_plan']['nodes']
        self.assertEqual(len(goals),5)
        self.assertEqual({g['team'] for g in goals},{'red','blue'})
        self.assertTrue(all(g['condition']['region']['center']['lat'] is None for g in goals if 'region'in g['condition']))
        self.assertEqual(len(basis['campaign_window']['definition']['sectors']),2)

    def test_northern_source_and_window_leave_old_versions_and_default_frozen(self):
        self.assertEqual(hi.definition(WH)['version'],'1.0.0')
        old=hi.definition(WH,'1.1.0');self.assertNotIn('ww2.cn.army59',{u['id']for u in old['units']})
        new=hi.definition(WH,'1.2.0')
        self.assertEqual(new['sources']['WH_ZX_DABIE7']['evidence_kind'],'published_secondary')
        self.assertIn('第7期',new['sources']['WH_ZX_DABIE7']['publisher'])
        self.assertIn('第8期',new['sources']['WH_ZX_DABIE8']['publisher'])
        w=cw.load(WINDOW)
        self.assertEqual(w['historical_initial']['definition_hash'],hi.digest(new))
        self.assertEqual(cw.load('WJL-oct6-10','1.5.0')['historical_initial']['version'],'1.4.0')
        self.assertEqual(cw.load('WJL-oct6-10','1.6.0')['historical_initial']['version'],'1.5.0')

    def test_temporal_statistics_and_earlier_units_are_not_silent_arrivals(self):
        d=hi.definition(WH,'1.2.0');units={u['id']:u for u in d['units']}
        p=next(p for p in d['phases']if p['id']=='northern_sep17_18')
        self.assertEqual(p['date']['precision'],'range')
        self.assertTrue(all(r['status']!='reported_present'for r in units['ww2.cn.division113']['presence']if r['phase_id']==p['id']))
        w=cw.load(WINDOW)
        self.assertEqual(w['units']['ww2.cn.division113']['representation'],'outside_window')
        self.assertTrue(all(m['policy']=='reference_only'for m in w['milestones']))
        self.assertFalse(d['coverage']['strength_complete'])

    def test_new_versions_have_their_own_goal_source_pins(self):
        for battle,version,phase in [(WH,'1.2.0','northern_sep17_18'),(WJL,'1.5.0','oct7_attack')]:
            source=hi._materialize(hi.definition(battle,version),phase)['historical_initial']
            guidance=ho.objective_guidance(source)
            self.assertIsNotNone(guidance)
            self.assertEqual(guidance['binding']['initial_version'],version)
            self.assertEqual(guidance['binding']['initial_definition_hash'],source['definition_hash'])


if __name__=='__main__':unittest.main(verbosity=2)
