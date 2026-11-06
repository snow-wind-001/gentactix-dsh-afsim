"""Dated reported strength and replacement plans never become a live roster."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_links as links
from gentactix import historical_operations as ho, campaign_scope
from verify_historical_measurements import fixture, session

BATTLE='红军长征-湘江战役-1934.11.25至1934.12.01'
VERSION='1.1.0'
PHASE='oct8_strength_reference'
STATISTICS={'reported_existing_strength','planned_replacement','reported_strength_including_plan'}
ROWS={
    'lm.red.corps1':(17280,2600,19880),
    'lm.red.corps3':(15205,2600,17805),
    'lm.red.corps5':(10868,1300,12168),
    'lm.red.corps8':(9022,1900,10922),
    'lm.red.corps9':(10238,1300,11538),
    'lm.red.cmc_column1':(4693,None,4693),
    'lm.red.cmc_column2':(9853,None,9853),
}


class DatedStrengthSchemaTests(unittest.TestCase):
    def test_three_personnel_statistics_keep_distinct_meanings(self):
        for statistic in STATISTICS:
            d,p,row=fixture();row['statistic']=statistic
            with self.subTest(statistic=statistic):
                self.assertTrue(hi.validate_definition(d))
                reply=links.observation(session(d),dict(kind='measurements'))
                self.assertEqual(reply['measurements'][0]['statistic'],statistic)
                self.assertIn(statistic,reply['statistic_notes'])
                self.assertIn('不是本局',reply['scope'])

    def test_plans_remain_integer_people_and_cannot_be_cast_as_equipment(self):
        for statistic in STATISTICS:
            for bad_metric,bad_value in [('artillery',2700),('personnel',True),('personnel',2700.5)]:
                d,p,row=fixture();row.update(statistic=statistic,metric=bad_metric)
                row['quantity'].update(unit=links.MEASUREMENT_UNITS[bad_metric],lower=bad_value,upper=bad_value)
                with self.subTest(statistic=statistic,metric=bad_metric,value=bad_value),self.assertRaises(ValueError):
                    hi.validate_definition(d)


class LongMarchDatedStrengthTests(unittest.TestCase):
    def definition(self):return hi.definition(BATTLE,VERSION)

    def measurements(self):
        return next(p for p in self.definition()['phases']if p['id']==PHASE)['measurements']

    def test_source_is_public_typeset_table_and_does_not_claim_archival_original(self):
        d=self.definition();self.assertTrue(hi.validate_definition(d))
        source=d['sources']['XJ_OCT8_SH2026']
        self.assertFalse(source['original_archive_examined'])
        self.assertIn('重排',source['limitations'])
        self.assertIn('ccphistory.org.cn',source['url'])
        self.assertEqual(len(d['units']),26)
        self.assertFalse(any(d['coverage'][k]for k in ('order_of_battle_complete','opening_deployment_complete','strength_complete')))

    def test_seven_reported_rows_distinguish_existing_plan_and_inclusive_subtotal(self):
        rows=self.measurements();self.assertEqual(len(rows),22)
        self.assertTrue(all(r['date']==dict(label='1934-10-08',precision='day')for r in rows))
        for identity,(existing,plan,total)in ROWS.items():
            selected={r['statistic']:r for r in rows if r['unit_ids']==[identity]}
            self.assertEqual(selected['reported_existing_strength']['quantity']['lower'],existing)
            self.assertEqual(selected['reported_strength_including_plan']['quantity']['lower'],total)
            if plan is None:self.assertNotIn('planned_replacement',selected)
            else:self.assertEqual(selected['planned_replacement']['quantity']['lower'],plan)
            self.assertTrue(all(r['metric']=='personnel'and r['quantity']['unit']=='persons'for r in selected.values()))

    def test_reported_totals_overlap_components_and_are_not_additive_reinforcements(self):
        totals={r['statistic']:r for r in self.measurements() if len(r['unit_ids'])>1}
        self.assertEqual({k:r['quantity']['lower']for k,r in totals.items()},
            {'reported_existing_strength':77159,'planned_replacement':9700,'reported_strength_including_plan':86859})
        self.assertTrue(all('重叠'in r['population']and '不'in r['limitations']for r in totals.values()))
        self.assertEqual(set(totals['reported_existing_strength']['unit_ids']),set(ROWS))
        self.assertEqual(set(totals['planned_replacement']['unit_ids']),{i for i,v in ROWS.items()if v[1] is not None})

    def test_old_version_default_and_all_timeless_facts_remain_unknown(self):
        self.assertEqual(hi.definition(BATTLE)['version'],'1.0.0')
        old=hi.definition(BATTLE,'1.0.0')
        self.assertEqual(hi.digest(old),'ce2fc5cc41b6c2337ba07276fbba7c70d30932b7b283fcc13b4c7bec79b9aa7a')
        self.assertTrue(all(fact['value']is None for u in self.definition()['units']for fact in u['facts'].values()))
        current={u['id']:u for u in self.definition()['units']}
        for unit in old['units']:
            for key in unit:
                if key!='presence':self.assertEqual(current[unit['id']][key],unit[key])
            self.assertTrue(all(row in current[unit['id']]['presence']for row in unit['presence']))

    def test_reference_additions_never_enter_november_phases_or_expand_campaign_selection(self):
        old=hi.initial(BATTLE,'xinxu_nov28')['historical_initial']
        new=hi.initial(BATTLE,'xinxu_nov28',version=VERSION)['historical_initial']
        self.assertEqual(ho.partition(new),ho.partition(old))
        self.assertEqual(campaign_scope.select(new),campaign_scope.select(old))
        self.assertEqual(set(ho.configuration_template(new)['actors']),set(ho.configuration_template(old)['actors']))
        reference=hi.initial(BATTLE,PHASE,version=VERSION)['historical_initial']
        with self.assertRaisesRegex(ValueError,'参战尚未核定'):ho.configuration_template(reference)

    def test_unknown_november_inputs_do_not_take_october_reported_or_planned_numbers(self):
        from tools.qa.xiangjiang_fixture import inputs
        _,parameters=inputs();snapshot=hi.initial(BATTLE,'xinxu_nov28',version=VERSION)['historical_initial']
        world=ho.initial(snapshot,parameters)
        for team in ('red','blue'):
            for unit in world[team+'_units']:
                self.assertEqual(unit['personnel']['current'],parameters['actors'][unit['historical_unit_id']]['personnel'])
        self.assertEqual(len(world['red_units'])+len(world['blue_units']),4)
        self.assertEqual(sum(u['personnel']['current']for team in ('red','blue')for u in world[team+'_units']),3750)

    def test_all_three_purposes_and_both_engines_share_the_new_source_snapshot(self):
        baseline=hi.initial(BATTLE,'xinxu_nov28',version=VERSION)
        for purpose in ('analysis','historical','synthetic'):
            for engine in ('afsim','narrative'):
                with self.subTest(purpose=purpose,engine=engine):
                    self.assertEqual(hi.initial(BATTLE,'xinxu_nov28',version=VERSION,purpose=purpose,engine=engine),baseline)

    def test_explicit_reference_paging_preserves_date_version_and_host_world(self):
        d=self.definition();s={'war_state':hi._materialize(d,'xinxu_nov28')};before=copy.deepcopy(s)
        self.assertEqual(links.observation(s,dict(kind='measurements'))['total'],0)
        args=dict(kind='measurements',phase_id=PHASE,limit=4);rows=[];pages=0
        while args:
            response=links.observation(s,args);pages+=1;rows+=response['measurements'];args=response['next_args']
            self.assertEqual(response['phase_id'],PHASE)
            self.assertEqual(response['definition_hash'],hi.digest(d))
        self.assertEqual(pages,6);self.assertEqual(len({r['id']for r in rows}),22)
        self.assertEqual(s,before)
        with self.assertRaisesRegex(ValueError,'版本'):links.observation(s,dict(kind='measurements',phase_id=PHASE,definition_hash='wrong'))

    def test_new_version_guidance_uses_its_own_binding_and_old_local_goals(self):
        for phase in ('xinxu_nov28','guanghuapu_nov30_morning'):
            old=ho.objective_guidance(hi.initial(BATTLE,phase)['historical_initial'])
            snapshot=hi.initial(BATTLE,phase,version=VERSION)['historical_initial'];new=ho.objective_guidance(snapshot)
            self.assertEqual(new['binding']['initial_version'],VERSION)
            self.assertEqual(new['binding']['initial_definition_hash'],snapshot['definition_hash'])
            self.assertEqual((new['team'],new['profile']),(old['team'],old['profile']))
        self.assertIsNone(ho.objective_guidance(hi.initial(BATTLE,PHASE,version=VERSION)['historical_initial']))

    def test_new_statistics_are_retrievable_without_crowding_required_initialization_sections(self):
        from gentactix import rag
        hits=rag.search('10月8日 现有 拟补充77159',battle=BATTLE,top_k=30)
        self.assertTrue(any('出发前统计参考'in r['section']and '拟补充'in r['text']for r in hits))
        initial=rag.select_passages(rag.search(BATTLE,battle=BATTLE,phase='init',top_k=8),3200)
        required=[r for r in initial if r.get('required')]
        self.assertEqual({r['section']for r in required},{'时间与地点','双方兵力与指挥','争议与待考'})
        self.assertTrue(all(not r['excerpted']for r in required))


if __name__=='__main__':unittest.main()
