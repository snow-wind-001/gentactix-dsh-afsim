"""World/AFSIM boundary checks; these do not pretend to run the external engine."""
import copy
import unittest


def world():
    return {'current_time': '1935-05-29 06:00', 'red_units': [
        {'name': '甲', 'type': '步兵', 'lat': 29.91, 'lng': 102.23, 'hp': 100,
         'personnel': {'current': None, 'committed': None}, 'equipment': [], 'logistics': {'ammo': None}}],
        'blue_units': [{'name': '乙', 'type': '步兵', 'lat': 29.92, 'lng': 102.24, 'hp': 100}],
        'terrain_features': [{'name': 'original'}], 'engagements': []}


class AfsimWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend import afsim_world
        cls.a = afsim_world

    def test_compiler_does_not_mutate_or_inline_untrusted_names(self):
        before = world(); before['red_units'][0]['name'] = '甲\ninclude bad.afsim'
        saved = copy.deepcopy(before)
        scene = self.a.compile_scene(before, [], 900)
        self.assertEqual(before, saved)
        self.assertNotIn('include bad', scene['script'])
        self.assertEqual(len(scene['entities']), 2)

    def test_unknown_position_is_carried_and_not_invented(self):
        before = world(); before['blue_units'][0]['lat'] = None
        scene = self.a.compile_scene(before, [], 900)
        self.assertEqual(len(scene['entities']), 1)
        self.assertEqual(len(scene['excluded']), 1)

    def test_move_must_identify_a_known_unit_and_finite_position(self):
        for order in ({'unit': '不存在', 'action': 'move', 'lat': 0, 'lng': 0},
                      {'unit': '甲', 'action': 'move', 'lat': float('nan'), 'lng': 0}):
            with self.assertRaises(ValueError): self.a.compile_scene(world(), [order], 900)

    def test_observation_precision_and_authoritative_ledger_are_preserved(self):
        before = world(); scene = self.a.compile_scene(before, [{'unit': '甲', 'action': 'move', 'lat': 29.911, 'lng': 102.23}], 900)
        lines = ['GTXCLOCK|900']
        for identity, entity in scene['entities'].items():
            target = entity['target']; lat, lng = target['lat'], target['lng']
            lines.append(f'GTXPOS|{identity}|{int(lat)}|{round((lat-int(lat))*1e8)}|{int(lng)}|{round((lng-int(lng))*1e8)}')
        observations = self.a.parse_observations('\n'.join(lines), scene)
        after = self.a.apply_observations(before, observations, scene)
        self.assertAlmostEqual(after['red_units'][0]['lat'], 29.911, places=7)
        for field in ('personnel', 'equipment', 'logistics'):
            self.assertEqual(after['red_units'][0][field], before['red_units'][0][field])
        self.assertEqual(after['terrain_features'], before['terrain_features'])

    def test_missing_duplicate_or_wrong_clock_is_rejected(self):
        scene = self.a.compile_scene(world(), [], 900)
        for text in ('GTXCLOCK|901', 'GTXCLOCK|900', 'GTXCLOCK|900\nGTXCLOCK|900'):
            with self.assertRaises(ValueError): self.a.parse_observations(text, scene)

    def test_wrong_runtime_position_is_not_silently_snapped(self):
        scene = self.a.compile_scene(world(), [], 900)
        lines = ['GTXCLOCK|900'] + [f'GTXPOS|{identity}|0|0|0|0' for identity in scene['entities']]
        with self.assertRaises(ValueError): self.a.parse_observations('\n'.join(lines), scene)

    def test_compact_observation_does_not_reinject_history_or_full_ledger(self):
        from backend import afsim_state
        session = {'id': '123456789abc', 'war_state': world(), 'time_step': '15分钟', 'turn_count': 0,
                   'scenario_input': '教学', 'history': ['DO-NOT-PROMPT' * 10000],
                   'trajectory': [{'secret_full_state': 'DO-NOT-PROMPT'}]}
        value = afsim_state.observation(session, {'limit': 1})
        self.assertEqual(len(value['units']), 1)
        self.assertEqual(value['next_offset'], 1)
        # Force strength is necessary for planning unequal custom formations;
        # expose four bounded counts without the full ledger/source document.
        self.assertEqual(set(value['units'][0]['personnel']),
                         {'committed','current','casualties','noncombat_losses'})
        self.assertIsNone(value['units'][0]['personnel']['current'])
        self.assertNotIn('DO-NOT-PROMPT', str(value))
        detailed = afsim_state.observation(session, {'ids': [value['units'][0]['id']], 'detail': True})
        self.assertIsNone(detailed['units'][0]['personnel']['current'])

    def test_observation_rejects_unbounded_reads(self):
        from backend import afsim_state
        session = {'id': '123456789abc', 'war_state': world(), 'time_step': '15分钟', 'turn_count': 0}
        for args in ({'limit': 1000}, {'offset': -1}, {'ids': ['x'] * 17}):
            with self.assertRaises(ValueError): afsim_state.observation(session, args)

    def test_teaching_observation_contains_computable_goal_and_effect_provenance(self):
        from backend import afsim_state
        from gentactix import missions
        spec = missions.catalog()[0]
        initial = missions.initial(spec['id'])
        session = {'id':'123456789abc','war_state':initial,'time_step':'30分钟','turn_count':0,'execution_backend':'afsim'}
        value = afsim_state.observation(session)
        self.assertEqual(value['mission']['objective'], initial['mission']['definition']['objective'])
        self.assertEqual(value['mission']['deadline_turn'], 4)
        self.assertEqual(value['mission']['progress'], initial['mission']['progress'])
        self.assertEqual(value['effects']['ledger'], 'teaching-rules-1')
        self.assertFalse(value['execution']['verified'])

    def test_initial_view_includes_both_teams_and_explains_sampling(self):
        from backend import afsim_state
        value = world()
        for key in ('red_units', 'blue_units'):
            value[key] = [dict(value[key][0], name=key + str(i)) for i in range(12)]
        session = {'id':'123456789abc','war_state':value,'time_step':'15分钟','turn_count':0}
        view = afsim_state.initial_observation(session)
        self.assertEqual(len(view['units']), 8)
        self.assertEqual({row['team'] for row in view['units']}, {'red','blue'})
        self.assertIn('offset=0', view['paging_note'])
        self.assertFalse(view['registered_list_complete'])

    def test_small_initial_view_is_not_mislabeled_as_a_partial_roster(self):
        from backend import afsim_state
        session={'id':'123456789abc','war_state':world(),'time_step':'15分钟','turn_count':0}
        view=afsim_state.initial_observation(session)
        self.assertTrue(view['registered_list_complete'])
        self.assertEqual(len(view['units']),view['total_units'])
        self.assertIn('全部已登记',view['paging_note'])
        self.assertNotIn('不能推定只存在这些单位',view['paging_note'])
        self.assertTrue(afsim_state.observation(session)['registered_list_complete'])
        self.assertFalse(afsim_state.observation(session,{'ids':[view['units'][0]['id']]})['registered_list_complete'])

    def test_analysis_prompt_does_not_restore_full_world_or_old_transcripts(self):
        from backend import afsim_state
        value = world(); value['afsim'] = {'source':'dsh_native_mcp_controller','status':'completed',
            'returncode':0,'process_id':'real-process','seconds':900}
        session = {'id':'123456789abc','war_state':value,'time_step':'15分钟','turn_count':2,
            'history':['FULL-HISTORY'*20000], 'trajectory':[]}
        text = afsim_state.analysis_prompt(session, '最新位置？')
        self.assertNotIn('FULL-HISTORY', text)
        self.assertIn('real-process', text)
        self.assertIn('not_modeled', text)

    def test_large_change_keeps_observed_motion_when_field_details_are_truncated(self):
        from backend import afsim_state
        session={'id':'a123456789ab','turn_count':1,'trajectory':[{'turn':1,'changes':[{'name':'甲','team':'red','moved_km':.1,
            'before_position':[1,2],'after_position':[1,2.001], 'fields':{'personnel':{'source':'x'*5000}}}]}]}
        row=afsim_state.changes(session)['changes'][0]['change']
        self.assertEqual(row['moved_km'],.1)
        self.assertEqual(row['after_position'],[1,2.001])

    def test_underground_goal_does_not_advertise_reception_rules(self):
        from backend import afsim_state
        from gentactix import missions
        world=missions.initial('AJ15-local-v1')
        context=afsim_state.mission_context(world)
        self.assertNotIn('ceasefire_turn',context)
        self.assertNotIn('accepted',context)
        self.assertNotIn('accept',context['order_guidance'])
        self.assertIn('conceal',context['order_guidance'])

    def test_reception_menu_matches_current_ceasefire_window(self):
        from gentactix import missions
        spec=next(m for m in missions.catalog() if m['profile']=='reception')
        world=missions.initial(spec['id'])
        self.assertNotIn('accept',missions.available_actions(world))
        self.assertIn('fire',missions.available_actions(world))
        world['mission']['turn']=world['mission']['definition']['ceasefire_turn']
        self.assertIn('accept',missions.available_actions(world))
        self.assertNotIn('fire',missions.available_actions(world))


if __name__ == '__main__':
    unittest.main()
