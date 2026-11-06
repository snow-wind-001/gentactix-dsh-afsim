"""A source-declared solo transfer must use actual multi-unit goal conditions."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_operations as ho, campaign_plan as goals, missions
from tools.qa.transfer_campaign_fixture import inputs, step


class TransferCampaignTests(unittest.TestCase):
    def test_missing_enemy_does_not_complete_a_transfer(self):
        world = ho.initial(*inputs())
        before = copy.deepcopy(world)
        after = step(world)
        self.assertEqual(after['mission']['status'], 'active')
        self.assertEqual(after['campaign_plan']['outcomes'], {'red':False,'blue':False})
        self.assertEqual(after['campaign_plan']['side_progress'], {'red':0,'blue':0})
        for key in ('red_units','blue_units','supply_nodes','combined_arms'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(world, before)

    def test_all_four_axes_and_consecutive_observations_are_required(self):
        world = ho.initial(*inputs())
        after = step(world, ['reach0'])
        self.assertEqual(after['campaign_plan']['nodes']['reach0']['status'], 'completed')
        self.assertEqual(after['mission']['status'], 'active')
        after = step(after, ['reach1','reach2','reach3'])
        self.assertTrue(after['campaign_plan']['outcomes']['red'])
        self.assertFalse(after['campaign_plan']['outcomes']['blue'])
        self.assertEqual(after['mission']['status'], 'active')
        after = step(after)
        self.assertEqual(after['mission']['winner'], 'red')
        self.assertEqual(after['mission']['status'], 'completed')
        goals.validate_state(after)

    def test_total_transfer_loss_does_not_award_a_fictitious_enemy(self):
        after = step(ho.initial(*inputs()), destroy=True)
        self.assertEqual(after['mission']['status'], 'completed')
        self.assertIsNone(after['mission']['winner'])
        self.assertIn('转移', after['mission']['reason'])
        self.assertFalse(after['campaign_plan']['outcomes']['blue'])

    def test_inactive_team_has_no_goals_but_active_team_cannot_have_empty_outcomes(self):
        for team in ('red','blue'):
            snapshot, params = inputs()
            if team == 'red': params['campaign_plan']['outcomes']['red']['node_ids'] = []
            else: params['campaign_plan']['outcomes']['blue']['node_ids'] = ['preserve']
            with self.subTest(team=team), self.assertRaises(ValueError): ho.initial(snapshot, params)

    def test_single_side_without_source_declaration_remains_rejected(self):
        from tools.qa.campaign_plan_fixture import world as combat_world
        world = combat_world()
        world['blue_units'] = []
        value = copy.deepcopy(world['mission']['definition']['campaign_plan'])
        value['nodes'] = [n for n in value['nodes'] if n['team']=='red']
        value['outcomes']['blue']['node_ids'] = []
        with self.assertRaises(ValueError): goals.validate_config(value, world)

    def test_source_hash_cannot_be_bypassed_by_editing_interaction_metadata(self):
        world = ho.initial(*inputs())
        world['historical_initial']['definition']['phases'][1]['interaction']['active_teams'] = ['blue']
        with self.assertRaises(ValueError): goals.validate_config(goals.definition(world), world)

    def test_sourced_transfer_cannot_hide_a_physically_present_enemy(self):
        world = ho.initial(*inputs())
        row = copy.deepcopy(world['red_units'][0]); row['historical_unit_id'] = 'invented.enemy'
        world['blue_units'].append(row)
        with self.assertRaises(ValueError): goals.validate_config(goals.definition(world), world)

    def test_readonly_goal_observation_discloses_the_single_active_team(self):
        world = ho.initial(*inputs())
        observation = goals.observation(world, limit=2)
        self.assertEqual(observation['active_teams'], ['red'])
        self.assertEqual(observation['total'], 5)
        self.assertTrue(observation['next_args'])

    def test_window_admission_reuses_source_scope_without_inventing_an_opponent(self):
        from tools.upgrade_long_march_transfer import build, window, PHASE
        from gentactix import campaign_windows as cw
        source = build(); snapshot = hi._materialize(source, PHASE)['historical_initial']
        value = window(source)
        self.assertEqual(cw.validate_definition(value, snapshot), [u['id'] for u in source['units'] if u['role']=='formation'])
        self.assertEqual(len(value['units']),7)
        self.assertTrue(all(u['role']=='command' for u in source['units'][4:]))
        self.assertTrue(all(f['value'] is None for u in source['units'] for f in u['facts'].values()))

    def test_noncontact_window_cannot_span_a_combat_or_undeclared_phase(self):
        from tools.upgrade_long_march_transfer import build, window, PHASE
        from gentactix import campaign_windows as cw
        source = build(); value = window(source)
        extra = copy.deepcopy(source['phases'][1]); extra['id']='later_combat'; extra.pop('interaction')
        source['phases'].append(extra)
        # Keep the operation identity schema valid; only phase interaction differs.
        extra.pop('operations'); extra.pop('relations')
        enemy=copy.deepcopy(source['units'][0]);enemy.update(id='qa.enemy',team='blue',name='QA later enemy',parent_id=None)
        enemy['presence']=[dict(phase_id=p['id'],status='reported_present' if p['id']=='later_combat' else 'outside_scope',evidence=p['evidence']) for p in source['phases']]
        source['units'].append(enemy)
        value['units'][enemy['id']]={**copy.deepcopy(value['units']['mg.red.army1']),
            'representation':'after_window','operational_reference':None,'operation_ids':[]}
        value['phase_ids'].append('later_combat');value['historical_initial']['definition_hash']=hi.digest(source)
        snapshot=hi._materialize(source, PHASE)['historical_initial']
        with self.assertRaisesRegex(ValueError,'非接敌|阵营'):cw.validate_definition(value,snapshot)

    def test_registered_campaign_has_four_ground_actors_and_three_nonphysical_references(self):
        from tools.qa.transfer_campaign_fixture import campaign_inputs
        world=ho.initial(*campaign_inputs())
        self.assertEqual(len(world['red_units']),4);self.assertEqual(world['blue_units'],[])
        self.assertEqual(len(world['historical_initial']['definition']['units']),7)
        self.assertEqual({n['team'] for n in world['supply_nodes']},{'red'})
        self.assertEqual(world['mission']['definition']['campaign_definition']['objective']['relief_regions'],[])
        self.assertFalse(world['mission']['definition']['campaign_definition']['surrender']['enabled'])
        self.assertNotIn('蓝方',world['mission']['definition']['goal'])
        self.assertNotIn('双方同时',world['mission']['definition']['goal'])
        self.assertEqual(ho.from_binding(world['mission']['definition']['historical_calculation']),world['mission']['definition'])
        missions.validate(world)

    def test_registered_window_basis_offers_unfilled_transport_goals_and_keeps_default(self):
        from backend.scenario_builder import historical_basis
        from tools.upgrade_long_march_transfer import BATTLE, WINDOW
        result=historical_basis(BATTLE,force_scope='campaign',campaign_window_id=WINDOW,termination_mode='objectives')
        self.assertTrue(result['ready'],result['error']);self.assertEqual(result['initial']['version'],'1.1.0')
        self.assertEqual(hi.initial(BATTLE)['historical_initial']['version'],'1.0.0')
        template=result['configuration_template'];self.assertEqual(len(template['campaign_plan']['nodes']),6)
        self.assertTrue(all(u['personnel'] is None for u in template['actors'].values()))
        self.assertTrue(all(n['condition']['region']['center']['lat'] is None for n in template['campaign_plan']['nodes'] if n['condition']['kind']=='reach'))
        self.assertEqual(template['campaign_plan']['outcomes']['blue']['node_ids'],[])
        self.assertTrue(result['available_campaign_windows'])
        guidance=ho.objective_guidance(result['initial'])
        self.assertIn('巴西',guidance['objective_label'])
        self.assertNotIn('班佑',guidance['objective_label'])
        self.assertIn('8月27日',guidance['sources'][0]['locator'])

    def test_transfer_cannot_replace_goal_graph_with_combat_surrender_or_fake_blocking_area(self):
        from tools.qa.transfer_campaign_fixture import campaign_inputs
        for edit in ('drop','surrender','region','deadline'):
            s,p=campaign_inputs()
            if edit=='drop':p.pop('campaign_plan')
            elif edit=='surrender':p['campaign']['surrender']['enabled']=True
            elif edit=='region':p['campaign']['objective']['relief_regions']=[{'center':p['area']['center'],'radius_km':1}]
            else:p['goal']['termination_mode']='deadline'
            with self.subTest(edit=edit),self.assertRaisesRegex(ValueError,'非接敌'):ho.initial(s,p)

    def test_campaign_arrival_and_resources_still_constrain_goal_completion(self):
        from tools.qa.transfer_campaign_fixture import campaign_inputs
        s,p=campaign_inputs();key=next(reversed(p['actors']))
        p['campaign']['arrivals'][key]['not_before']='1935-08-21T01:00'
        p['actors'][key]['logistics']['food']=0
        world=ho.initial(s,p);reached=['transfer-'+str(n+1) for n in range(4)]
        one=step(world,reached)
        self.assertEqual(one['mission']['status'],'active')
        self.assertEqual(one['campaign_plan']['nodes']['transfer-4']['status'],'waiting_arrival')
        two=step(one)
        self.assertEqual(two['campaign_plan']['nodes']['transfer-4']['status'],'completed')
        self.assertFalse(two['campaign_plan']['nodes']['transfer-resources']['condition'])
        self.assertEqual(two['mission']['status'],'active')
        self.assertEqual(world['red_units'][-1]['logistics']['food'],0)

    def test_original_cumulative_both_sides_guard_is_not_relaxed(self):
        from gentactix import campaign_scope
        snapshot,_=inputs()
        with self.assertRaisesRegex(ValueError,'双方'):campaign_scope.select(snapshot)

    def test_source_declared_blue_transfer_is_not_hard_coded_to_red(self):
        snapshot,p=inputs();snapshot=copy.deepcopy(snapshot)
        for u in snapshot['definition']['units']:u['team']='blue'
        snapshot['definition']['phases'][1]['interaction']['active_teams']=['blue']
        snapshot['definition_hash']=hi.digest(snapshot['definition'])
        p['goal']['team']='blue'
        for n in p['campaign_plan']['nodes']:n['team']='blue'
        p['campaign_plan']['outcomes']={team:dict(mode='all',node_ids=['preserve'] if team=='blue' else []) for team in ('red','blue')}
        world=ho.initial(snapshot,p)
        after=step(step(world,['reach0','reach1','reach2','reach3']))
        self.assertEqual(after['mission']['winner'],'blue')
        self.assertEqual(goals.observation(after)['active_teams'],['blue'])

    def test_inactive_team_state_cannot_be_sealed_as_a_winner(self):
        world=ho.initial(*inputs());world['campaign_plan']['outcomes']['blue']=True
        goals._seal(world['campaign_plan'])
        with self.assertRaisesRegex(ValueError,'范围外'):goals.validate_state(world)

    def test_existing_native_staged_builder_accepts_all_four_armies_without_an_extra_executor(self):
        from backend import scenario_builder as sb, scenario_assembly as sa
        from tools.qa.transfer_campaign_fixture import campaign_inputs
        from tools.upgrade_long_march_transfer import WINDOW
        s,p=campaign_inputs()
        basis=sb.historical_basis(s['definition']['battle'],force_scope='campaign',campaign_window_id=WINDOW,termination_mode='objectives')
        assembly=sa.create(basis);self.addCleanup(sa.close,assembly.id)
        global_params={k:copy.deepcopy(v) for k,v in p.items() if k not in ('format','phase_id','actors')}
        global_params['campaign_scope'].pop('window')
        response=assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':global_params})
        self.assertTrue(response['updated'],response)
        for part in assembly.parts:
            response=assembly.tool(part,'update_scenario_configuration',{'revision':assembly.revision,
                'patch':{'actors':{i:p['actors'][i] for i in assembly.assigned(part)}}})
            self.assertTrue(response['updated'],response)
        response=assembly.tool('final','validate_scenario_configuration',{})
        self.assertTrue(response['valid'],response)
        world=ho.initial(s,assembly.configuration)
        self.assertEqual(len(world['red_units']),4)
        self.assertEqual(world['blue_units'],[])

    def test_afsim_scene_contains_only_four_real_army_entities_and_no_command_infantry(self):
        from backend import afsim_world
        from tools.qa.transfer_campaign_fixture import campaign_inputs
        world=ho.initial(*campaign_inputs())
        scene=afsim_world.compile_scene(world,[{'unit':u['name'],'action':'hold'} for u in world['red_units']],1800,native_rules=True)
        self.assertEqual(len(scene['entities']),4)
        self.assertEqual({r['team'] for r in scene['entities'].values()},{'red'})
        self.assertFalse(any('指挥参考' in r['name'] for r in scene['entities'].values()))
        self.assertNotRegex(scene['script'],r'bool\s+\w+\s*=\s*;')
        self.assertIn('bool campaignRelief=false;',scene['script'])


if __name__ == '__main__': unittest.main()
