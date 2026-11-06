"""Jialing's concurrent axes must not collapse into one invented deployment."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_operations as ho

BATTLE = '红军长征-嘉陵江战役-1935.03.28至1935.04.21'
PHASES = ('tazishan_opening', 'yuankou_opening', 'jianxikou_langzhong', 'jianmen_apr2')


class JialingInitialTests(unittest.TestCase):
    def snapshot(self, phase=PHASES[0]):
        return hi.initial(BATTLE, phase)['historical_initial']

    def test_distinct_axes_have_sourced_rosters_without_duplicate_parents(self):
        expected = ({'jl.red.reg263', 'jl.red.hq_training', 'jl.red.artillery', 'jl.blue.bn40_2'},
                    {'jl.red.army31', 'jl.blue.huoshaosi'},
                    {'jl.red.army9', 'jl.blue.langzhong'},
                    {'jl.red.div88', 'jl.red.div93', 'jl.red.div91_part', 'jl.blue.jianmen'})
        for phase, actors in zip(PHASES, expected):
            with self.subTest(phase=phase):
                self.assertEqual(set(ho.partition(self.snapshot(phase))), actors)
        with self.assertRaises(ValueError):
            ho.partition(self.snapshot('campaign_reference'))

    def test_estimated_geometry_and_unknown_strength_stay_separate_from_facts(self):
        definition = self.snapshot()['definition']
        self.assertFalse(any(v for k,v in definition['coverage'].items() if k != 'notes'))
        for unit in definition['units']:
            self.assertTrue(all(f['value'] is None for f in unit['facts'].values()))
        self.assertTrue(any('午夜' in n and '21' in n for n in definition['coverage']['notes']))
        self.assertTrue(any('多渡点' in n for n in definition['coverage']['notes']))

    def test_crossing_axes_require_transport_while_jianmen_is_not_a_river(self):
        for phase in PHASES:
            s = self.snapshot(phase)
            template = ho.configuration_template(s)
            self.assertEqual('crossing_model' in template['facility'], phase != PHASES[-1])
            self.assertEqual(template['goal']['profile'], 'assault' if phase == PHASES[-1] else 'crossing')
            self.assertTrue(ho.objective_guidance(s)['not_covered'])
            with self.assertRaises(ValueError):
                ho.initial(s, template)

    def test_three_purposes_and_two_executors_share_source_and_restore(self):
        for phase in PHASES:
            baseline = hi.initial(BATTLE, phase)
            for purpose in ('analysis', 'historical', 'synthetic'):
                for executor in ('afsim', 'narrative'):
                    self.assertEqual(hi.initial(BATTLE, phase, purpose=purpose, engine=executor), baseline)
            self.assertEqual(hi.restore(copy.deepcopy(baseline['historical_initial'])), baseline)

    def test_builder_exposes_local_scope_and_never_selects_campaign_as_single_site(self):
        from backend.scenario_builder import historical_basis
        default = historical_basis(BATTLE, time_step='30分钟')
        self.assertTrue(default['ready'])
        self.assertEqual(default['initial']['phase_id'], PHASES[0])
        for phase in PHASES:
            b = historical_basis(BATTLE, phase_id=phase, time_step='30分钟')
            self.assertTrue(b['ready'])
            self.assertEqual(b['initial']['phase_id'], phase)

    def test_explicit_local_parameters_preserve_facts_and_freeze_independent_sites(self):
        from gentactix import missions
        from tools.qa.jialing_fixture import inputs
        sites = set()
        for phase in PHASES:
            source, p = inputs(phase)
            original = copy.deepcopy((source, p))
            world = ho.initial(source, p)
            missions.validate(world)
            self.assertEqual((source, p), original)
            self.assertEqual(world['historical_initial'], source)
            self.assertEqual({u['historical_unit_id'] for _,u in missions.units(world)}, set(p['actors']))
            sites.add(world['combined_arms']['bridge']['id'])
            self.assertTrue(all(u['parameter_sources']['personnel']['kind'] == 'model_estimate'
                                for _,u in missions.units(world)))
        self.assertEqual(len(sites), 4)

    def test_river_cannot_silently_become_capture_and_future_battle_cannot_start_early(self):
        from tools.qa.jialing_fixture import inputs
        for phase in PHASES[:-1]:
            source, p = inputs(phase)
            p['facility'].pop('crossing_model')
            p['rules']['goal_profile'] = p['goal']['profile'] = 'assault'
            with self.assertRaisesRegex(ValueError, '本阶段主任务'):
                ho.initial(source, p)
        source, p = inputs(PHASES[-1])
        p['clock']['start'] = '1935-03-29 06:00'
        with self.assertRaises(ValueError):
            ho.initial(source, p)

    def test_unavailable_fire_explains_resources_instead_of_claiming_feature_missing(self):
        from gentactix import commands
        from tools.qa.jialing_fixture import inputs
        for kind, text in (('shells','炮弹库存不足'), ('ammo','携行弹药不足'),
                           ('reload','冷却'), ('guns','没有可用炮兵装备')):
            world = ho.initial(*inputs())
            unit = next(u for u in world['red_units'] if u['historical_unit_id'] == 'jl.red.artillery')
            if kind == 'shells': unit['formation']['shells'] = 0
            if kind == 'ammo': unit['logistics']['ammo'] = 0
            if kind == 'reload': unit['formation']['reload_remaining_s'] = 3600
            if kind == 'guns':
                for e in unit['equipment']:
                    if e['category'] == 'artillery': e.update(operational=0, destroyed=e['committed'])
            session = {'id':'jialing-qa', 'turn_count':0, 'time_step':'30分钟',
                       'simulation_mode':'open', 'execution_backend':'afsim', 'war_state':world}
            view = commands.view(session)
            actor = next(u for u in view['units'] if u['name'] == unit['name'])
            enemy = next(u for u in view['units'] if u['team'] == 'blue')
            before = copy.deepcopy(session)
            self.assertNotIn('bombard', actor['capabilities']['actions'])
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, text):
                commands.step_order(session, {'unit_id':actor['id'], 'action':'bombard',
                                             'target_id':enemy['id'], 'duration':'next'})
            self.assertEqual(session, before)


if __name__ == '__main__':
    unittest.main()
