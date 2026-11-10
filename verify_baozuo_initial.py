"""Baozuo source roster, delayed reinforcements and explicit modelling limits."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_operations as ho

BATTLE='红军长征-包座战役-1935.08.29至1935.09.01'
PHASE='baozuo_core'


class BaozuoInitialTests(unittest.TestCase):
    def test_immediate_teaching_mode_preserves_estimated_schedule_and_releases_units(self):
        from gentactix import campaign, commands
        from tools.qa.baozuo_fixture import inputs
        source, parameters = inputs()
        legacy = ho.initial(source, parameters)
        later = next(u for u in legacy['blue_units'] if campaign.release_seconds(legacy, u) > 0)
        original_time = campaign.scheduled_time(campaign.definition(legacy), later, world=legacy)
        parameters = copy.deepcopy(parameters)
        parameters['campaign']['availability_mode'] = 'immediate'
        world = ho.initial(source, parameters)
        unit = next(u for u in world['blue_units'] if u['name'] == later['name'])
        self.assertEqual(campaign.release_seconds(world, unit), 0)
        self.assertTrue(world['campaign']['actors'][unit['name']]['active'])
        self.assertEqual(campaign.scheduled_time(campaign.definition(world), unit, world=world), original_time)
        session = {'id':'a123456789ab','war_state':world,'turn_count':0,'time_step':'1小时','execution_backend':'afsim'}
        capability = commands.capabilities(session, unit, 'blue')
        self.assertIn('move', capability['actions'])
        self.assertGreater(capability['move_km'], 0)
        self.assertEqual(capability['arrival']['availability_mode'], 'immediate')
        self.assertGreater(campaign.release_seconds(legacy, later), 0)

    def snapshot(self):return hi.initial(BATTLE,PHASE)['historical_initial']

    def test_named_roster_has_no_double_counted_armies_or_early_reserves(self):
        s=self.snapshot();actors=ho.partition(s)
        self.assertEqual(len(actors),12)
        self.assertEqual(sum(i.startswith('lm.red.') for i in actors),7)
        self.assertNotIn('lm.red.army30',actors)
        self.assertNotIn('lm.blue.division49',actors)
        self.assertNotIn('lm.red.army1',actors)
        self.assertNotIn('lm.blue.li_tiejun',actors)
        unit=next(u for u in s['definition']['units'] if u['id']=='lm.red.regiment264')
        self.assertEqual(unit['parent_id'],'lm.red.army30')

    def test_source_gaps_and_disagreements_are_not_numeric_certainty(self):
        d=self.snapshot()['definition']
        self.assertFalse(any(v for k,v in d['coverage'].items() if k!='notes'))
        self.assertTrue(any('异文' in x for x in d['coverage']['notes']))
        for u in d['units']:
            for f in u['facts'].values():self.assertIsNone(f['value'])
        t=ho.configuration_template(self.snapshot())
        self.assertTrue(all(a['personnel'] is None for a in t['actors'].values()))

    def test_three_purposes_and_two_engines_share_the_frozen_roster(self):
        baseline=hi.initial(BATTLE,PHASE)
        for purpose in ('analysis','historical','synthetic'):
            for engine in ('afsim','narrative'):
                self.assertEqual(hi.initial(BATTLE,PHASE,purpose=purpose,engine=engine),baseline)
        with patch.object(hi,'definition',side_effect=AssertionError('Do not reread mutable index')):
            self.assertEqual(hi.restore(copy.deepcopy(baseline['historical_initial'])),baseline)

    def test_default_builder_selects_supported_process_and_keeps_arrival_references(self):
        from backend.scenario_builder import historical_basis
        b=historical_basis(BATTLE,time_step='1小时')
        self.assertTrue(b['ready']);self.assertEqual(b['initial']['phase_id'],PHASE)
        refs=b['input_constraints']['entries']
        self.assertEqual({r['unit_id'] for r in refs},{'lm.blue.regiment289','lm.blue.regiment291','lm.blue.regiment294'})
        self.assertTrue(all(r['earliest']>'1935-08-29T18:00' for r in refs))
        guidance=ho.objective_guidance(b['initial'])
        self.assertEqual((guidance['team'],guidance['profile']),('red','assault'))
        self.assertTrue(guidance['not_covered'])

    def test_bound_estimates_preserve_unknown_facts_and_do_not_duplicate_parents(self):
        from tools.qa.baozuo_fixture import inputs
        from gentactix import missions
        source,parameters=inputs();before=copy.deepcopy((source,parameters))
        world=ho.initial(source,parameters);missions.validate(world)
        self.assertEqual((source,parameters),before)
        self.assertEqual(world['historical_initial'],source)
        self.assertEqual({u['historical_unit_id'] for _,u in missions.units(world)},set(parameters['actors']))
        self.assertEqual(len(world['red_units'])+len(world['blue_units']),12)
        self.assertEqual(sum(not a['active'] for a in world['campaign']['actors'].values()),3)
        self.assertFalse(world['mission']['definition']['combined_rules']['motorized'])
        self.assertTrue(all(u['parameter_sources']['personnel']['kind']=='model_estimate' for _,u in missions.units(world)))

    def test_reinforcement_binding_rejects_early_unreferenced_or_remote_front_entries(self):
        from tools.qa.baozuo_fixture import inputs
        source,parameters=inputs();identity='lm.blue.regiment291'
        for error in ('early','wrong-reference','remote'):
            p=copy.deepcopy(parameters)
            if error=='early':p['campaign']['arrivals'][identity]['not_before']='1935-08-29T18:00'
            elif error=='wrong-reference':p['campaign']['arrivals'][identity]['reference_id']='bz49-reg289-entry'
            else:p['actors'][identity]['position']={'lat':33.55,'lng':103.36714}
            with self.subTest(error=error),self.assertRaises(ValueError):ho.initial(source,p)
        p=copy.deepcopy(parameters)
        p['campaign']['arrivals'][identity]['not_before']='1935-08-31T02:00'
        self.assertEqual(ho.initial(source,p)['historical_initial'],source)

    def test_unfilled_source_template_never_silently_becomes_a_teaching_seed(self):
        source=self.snapshot()
        with self.assertRaises(ValueError):ho.initial(source,ho.configuration_template(source))

    def test_northern_corridor_control_does_not_require_annihilating_qiuji_garrison(self):
        from tools.qa.baozuo_fixture import inputs
        from gentactix import campaign
        source,parameters=inputs();world=ho.initial(source,parameters)
        region=parameters['campaign']['objective']['relief_regions'][1]
        unit=next(u for u in world['red_units'] if u['historical_unit_id']=='lm.red.division10')
        unit.update(region['center'])
        # Read-only objective projection over a hypothetical disposition. The
        # separate native test moves this unit without fabricating telemetry.
        self.assertTrue(campaign.assess(world)['relief_denied'])
        defender=next(u for u in world['blue_units'] if u['historical_unit_id']=='lm.blue.qiuji_garrison')
        self.assertEqual(defender['personnel']['current'],defender['personnel']['committed'])


if __name__=='__main__':unittest.main()
