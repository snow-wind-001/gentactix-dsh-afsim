"""Sourced Korean campaign phases, attendance and calculation contracts."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_operations as ho, history_replay


CASES = {
    'KW02-second': ('抗美援朝-第二次战役-1950.11.07至1950.12.24','samsori_blocking'),
    'KW03-third': ('抗美援朝-第三次战役-1950.12.31至1951.01.08','corps40_breakthrough'),
    'KW04-fourth': ('抗美援朝-第四次战役-1951.01.25至1951.04.21','chipyong_second_night'),
    'KW05-fifth': ('抗美援朝-第五次战役-1951.04.22至1951.06.10','gloster_final_morning'),
    'KW06-autumn1951': ('抗美援朝-夏秋季防御战役-1951.08.18至1951.10.22','maryang_oct5'),
    'KW07-counter1952': ('抗美援朝-秋季战术反击作战-1952.09.18至1952.10.31','koyangdae_sep18'),
    'KW08-sangganling': ('抗美援朝-上甘岭战役-1952.10.14至1952.11.25','triangle_oct14'),
    'KW09-summer1953': ('抗美援朝-夏季反击战役含金城战役-1953.05.13至1953.07.27','white_tiger_july13'),
}


class KoreanSeriesTests(unittest.TestCase):
    def snapshot(self,key,phase=None):
        battle,default=CASES[key]
        return hi.initial(battle,phase or default)['historical_initial']

    def test_all_nine_catalog_battles_have_partial_sourced_rosters(self):
        rows=[r for r in hi.catalog() if r['battle'].startswith('抗美援朝-')]
        self.assertEqual(len(rows),9);self.assertTrue(all(r['status']=='profiled' for r in rows))
        for identity,(battle,_) in CASES.items():
            with self.subTest(battle=battle):
                value=hi.definition(battle);self.assertEqual(value['id'],identity);hi.validate_definition(value)
                self.assertFalse(any(value['coverage'][k] for k in ('strength_complete','order_of_battle_complete','opening_deployment_complete')))
                self.assertGreaterEqual(len(value['sources']),2)
                self.assertTrue(all(not s['original_archive_examined'] for s in value['sources'].values()))

    def test_supported_phase_templates_use_actual_ids_and_keep_numeric_facts_unknown(self):
        for key in CASES:
            with self.subTest(key=key):
                snapshot=self.snapshot(key);ids=ho.partition(snapshot);template=ho.configuration_template(snapshot)
                self.assertGreaterEqual(len(ids),2);self.assertEqual(set(ids),set(template['actors']))
                self.assertEqual(template['rules']['era'],'korea')
                self.assertTrue(all(a['personnel'] is None and a['position']=={'lat':None,'lng':None} for a in template['actors'].values()))
                source={u['id']:u for u in snapshot['definition']['units']}
                self.assertEqual({source[i]['team'] for i in ids},{'red','blue'})
                self.assertTrue(all(source[i]['role'] in ('formation','support') for i in ids))

    def test_whole_campaign_reference_cannot_be_mistaken_for_simultaneous_deployment(self):
        for battle,_ in CASES.values():
            snapshot=hi.initial(battle)['historical_initial']
            self.assertEqual(snapshot['phase_id'],'campaign_reference')
            with self.assertRaises(ValueError):ho.partition(snapshot)

    def test_sources_and_freeze_are_purpose_and_executor_independent(self):
        for key,(battle,phase) in CASES.items():
            baseline=hi.initial(battle,phase)
            for purpose in ('analysis','historical','synthetic'):
                for engine in ('afsim','narrative'):
                    self.assertEqual(hi.initial(battle,phase,purpose=purpose,engine=engine),baseline)
            with patch.object(hi,'definition',side_effect=AssertionError('Do not consult current corpus')):
                self.assertEqual(hi.restore(copy.deepcopy(baseline['historical_initial'])),baseline)

    def test_chosin_and_western_front_are_separate_and_corps26_is_not_early(self):
        west=set(ho.partition(self.snapshot('KW02-second')))
        east=set(ho.partition(self.snapshot('KW02-second','chosin_east_nov30')))
        self.assertEqual(west,{'kw.cn.division113','kw.us.cavalry_division1'})
        self.assertEqual(east,{'kw.cn.division80','kw.cn.division81','kw.us.regiment31.task_force'})
        units={u['id']:u for u in self.snapshot('KW02-second')['definition']['units']}
        status=next(p['status'] for p in units['kw.cn.corps26']['presence'] if p['phase_id']=='chosin_east_nov30')
        self.assertEqual(status,'later_participant')

    def test_third_campaign_only_binds_the_selected_corps40_axis(self):
        self.assertEqual(set(ho.partition(self.snapshot('KW03-third'))),
            {'kw.cn.division118','kw.cn.division119','kw.rok.division6'})

    def test_chipyong_keeps_actual_partial_divisions_and_separate_french_support(self):
        ids=set(ho.partition(self.snapshot('KW04-fourth')))
        self.assertEqual(ids,{'kw.cn.division119','kw.cn.division115.chipyong_elements',
            'kw.cn.division126.chipyong_elements','kw.us.infantry_regiment23','kw.fr.battalion','kw.us.artillery37'})
        self.assertNotIn('kw.us.cavalry_regiment5',ids)

    def test_gloster_phase_does_not_double_count_the_parent_division(self):
        ids=set(ho.partition(self.snapshot('KW05-fifth')))
        self.assertEqual(ids,{'kw.cn.regiment560','kw.uk.gloucestershire.battalion1','kw.uk.mortar170.troop_c'})
        self.assertNotIn('kw.cn.division187',ids)

    def test_maryang_october_does_not_import_the_november_recapture(self):
        snapshot=self.snapshot('KW06-autumn1951')
        self.assertEqual(set(ho.partition(snapshot)),{'kw.cn.regiment571','kw.au.rar3'})
        phase=next(p for p in snapshot['definition']['phases'] if p['id']==snapshot['phase_id'])
        self.assertEqual(phase['date']['label'],'1951-10-05')
        self.assertTrue(phase['execution_window']['end'].startswith('1951-10-'))

    def test_koyangdae_guard_report_is_not_600_opening_troops_or_forced_casualties(self):
        snapshot=self.snapshot('KW07-counter1952');ids=set(ho.partition(snapshot))
        self.assertEqual(ids,{'kw.cn.regiment348.battalion2','kw.us.division3.koyangdae_garrison'})
        guard=next(u for u in snapshot['definition']['units'] if u['id']=='kw.us.division3.koyangdae_garrison')
        self.assertIsNone(guard['facts']['personnel']['value'])
        self.assertIn('135',guard['facts']['personnel']['scope'])

    def test_triangle_first_day_does_not_import_next_day_battalions_or_ocr_regiments(self):
        self.assertEqual(set(ho.partition(self.snapshot('KW08-sangganling'))),
            {'kw.cn.regiment135.triangle_elements','kw.us.regiment31.battalion1','kw.us.regiment31.battalion3'})
        names=[u['name'] for u in self.snapshot('KW08-sangganling')['definition']['units']]
        self.assertFalse(any('235团' in n for n in names))
        self.assertNotIn('kw.us.regiment32.battalion1',ho.partition(self.snapshot('KW08-sangganling')))

    def test_white_tiger_raid_retains_the_actual_small_raiding_units(self):
        self.assertEqual(set(ho.partition(self.snapshot('KW09-summer1953'))),
            {'kw.cn.regiment609.battalion2','kw.cn.regiment607.recon_squad','kw.rok.capital.regiment1'})

    def test_all_authored_phases_can_bind_explicit_estimates_without_ca_templates(self):
        from tools.qa.korean_series_fixture import inputs
        for key in CASES:
            phases=hi.definition(CASES[key][0])['phases'][1:]
            for phase in phases:
                with self.subTest(key=key,phase=phase['id']),patch('gentactix.combined_arms.definition',side_effect=AssertionError('No CA seed')):
                    snapshot,parameters=inputs(key,phase['id']);old=copy.deepcopy(snapshot)
                    world=ho.initial(snapshot,parameters)
                    self.assertEqual(world['historical_initial'],old)
                    self.assertEqual(len(world['red_units'])+len(world['blue_units']),len(ho.partition(snapshot)))
                    bad=copy.deepcopy(parameters);bad['clock']['start']='1950-01-01 00:00'
                    with self.assertRaises(ValueError):ho.initial(snapshot,bad)


if __name__=='__main__':unittest.main()
