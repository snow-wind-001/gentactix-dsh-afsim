"""Goal ownership must match actual native decisions, frozen inputs and observations."""
import copy
import unittest
from unittest.mock import patch
from gentactix import historical_operations as ho, missions, synthetic_history, combined_arms
from tools.qa.historical_operational_fixture import inputs


class ObjectiveTeamTests(unittest.TestCase):
    def world(self,profile='assault',team='blue'):
        snapshot,params=inputs();params['goal'].update(team=team,profile=profile,required_turns=2,deadline_turn=4,required_survivors=1)
        params['rules'].update(goal_profile=profile,required_survivors=1)
        return ho.initial(snapshot,params)

    def position(self,world,team,inside):
        spec=world['mission']['definition']
        for u in world[team+'_units']:
            u.update(lat=spec['objective']['lat']+(.0 if inside else .02),lng=spec['objective']['lng'])

    def test_blue_controls_the_goal_for_two_turns_and_is_the_winner(self):
        w=self.world();self.position(w,'blue',True);self.position(w,'red',False)
        for turn in (1,2):w['mission']['turn']=turn;missions.evaluate(w)
        self.assertEqual(w['mission']['status'],'completed');self.assertEqual(w['mission']['winner'],'blue')
        self.assertTrue(w['mission']['metrics']['condition'])

    def test_contested_control_resets_progress(self):
        w=self.world();self.position(w,'blue',True);self.position(w,'red',False)
        w['mission']['turn']=1;missions.evaluate(w);self.assertEqual(w['mission']['progress'],1)
        self.position(w,'red',True);w['mission']['turn']=2;missions.evaluate(w)
        self.assertEqual(w['mission']['progress'],0);self.assertEqual(w['mission']['status'],'active')

    def test_suppression_prevents_blue_control(self):
        w=self.world();self.position(w,'blue',True);self.position(w,'red',False)
        for u in w['blue_units']:u['formation']['suppression']=100
        w['mission']['turn']=1;missions.evaluate(w)
        self.assertFalse(w['mission']['metrics']['condition'])

    def test_failure_at_the_deadline_awards_red(self):
        w=self.world();self.position(w,'red',True);self.position(w,'blue',False)
        w['mission']['turn']=4;missions.evaluate(w)
        self.assertEqual(w['mission']['winner'],'red')

    def test_only_the_goal_side_elimination_ends_the_mission_early(self):
        for side,terminal in (('red',False),('blue',True)):
            w=self.world();self.position(w,'red',False);self.position(w,'blue',False)
            for u in w[side+'_units']:u['personnel']['current']=0
            w['mission']['turn']=1;missions.evaluate(w)
            self.assertEqual(w['mission']['status']=='completed',terminal)
            if terminal:self.assertEqual(w['mission']['winner'],'red');self.assertIn('蓝方',w['mission']['reason'])

    def test_blue_breakout_uses_blue_units_and_exit(self):
        w=self.world('breakout');exit=w['mission']['definition']['exit']
        for u in w['blue_units']:u.update(exit)
        for turn in (1,2):w['mission']['turn']=turn;missions.evaluate(w)
        self.assertEqual(w['mission']['winner'],'blue')

    def test_blue_delay_checks_red_reaching_its_exit(self):
        w=self.world('delay');exit=w['mission']['definition']['exit']
        for u in w['red_units']:u.update(exit)
        w['mission']['turn']=4;missions.evaluate(w)
        self.assertFalse(w['mission']['metrics']['condition']);self.assertEqual(w['mission']['winner'],'red')

    def test_native_goal_uses_the_same_side_without_a_python_combat_executor(self):
        from backend import afsim_world
        w=self.world()
        with patch.object(missions,'advance',side_effect=AssertionError('No Python execution')):
            scene=afsim_world.compile_scene(w,[],1800,native_rules=True)
        self.assertIn('blueInGoal>0 && redInGoal==0',scene['script'])
        self.assertIn('blueAlive==0',scene['script'])

    def test_blue_survivor_limit_uses_the_blue_roster(self):
        snapshot,params=inputs();params['goal'].update(team='blue',required_survivors=2)
        params['rules']['required_survivors']=2
        world=ho.initial(snapshot,params)
        self.assertEqual(world['mission']['definition']['objective_team'],'blue')
        params['goal']['required_survivors']=3;params['rules']['required_survivors']=3
        with self.assertRaises(ValueError):ho.initial(snapshot,params)

    def test_invalid_side_and_unimplemented_blue_profiles_are_rejected(self):
        snapshot,params=inputs()
        for side,profile in (('green','assault'),(True,'assault'),('blue','underground'),('blue','reception'),('blue','rail')):
            p=copy.deepcopy(params);p['goal'].update(team=side,profile=profile);p['rules']['goal_profile']=profile
            with self.subTest(side=side,profile=profile),self.assertRaises(ValueError):ho.initial(snapshot,p)

    def test_legacy_frozen_inputs_are_not_silently_upgraded(self):
        snapshot,params=inputs();legacy=ho.definition(snapshot,params)
        self.assertNotIn('objective_team',legacy)
        restored=ho.from_binding(legacy['historical_calculation']);self.assertEqual(restored,legacy)
        self.assertNotIn('team',restored['historical_calculation']['parameters']['goal'])

    def test_derived_synthetic_keeps_blue_goal_and_clamps_its_roster(self):
        snapshot,params=inputs();params['goal'].update(team='blue',required_survivors=2)
        params['rules']['required_survivors']=2
        w=ho.initial(snapshot,params);binding=w['mission']['definition']['historical_calculation']
        config=synthetic_history.seed(binding)['configuration']
        world=missions.from_definition(synthetic_history.definition(binding,config))
        self.assertEqual(world['mission']['definition']['objective_team'],'blue')
        self.assertEqual(world['mission']['definition']['combined_rules']['required_survivors'],2)
        self.assertEqual(world['historical_initial'],w['historical_initial'])
        config['teams']['blue'].pop()
        adjusted=synthetic_history.definition(binding,config)
        self.assertEqual(adjusted['combined_rules']['required_survivors'],1)
        self.assertIn('蓝方至少1个',adjusted['goal'])

    def test_new_goals_cannot_demand_more_control_turns_than_the_deadline(self):
        snapshot,params=inputs();params['goal'].update(team='blue',profile='assault',required_turns=4,deadline_turn=2)
        params['rules']['goal_profile']='assault'
        with self.assertRaisesRegex(ValueError,'连续.*截止'):ho.initial(snapshot,params)

    def test_relevant_objective_points_must_be_inside_the_configured_area(self):
        snapshot,params=inputs();params['goal'].update(team='blue',profile='breakout')
        params['rules']['goal_profile']='breakout';params['goal']['exit']={'lat':0,'lng':0}
        with self.assertRaisesRegex(ValueError,'目标|出口'):ho.initial(snapshot,params)

    def test_observation_exposes_owner_result_and_criteria(self):
        from backend import afsim_state
        w=self.world();s={'id':'012345abcdef','war_state':w,'turn_count':0,'time_step':'30分钟'}
        m=afsim_state.mission_context(w)
        self.assertEqual(m['objective_team'],'blue');self.assertIn('winner',m);self.assertIn('metrics',m)
        self.assertIn('蓝方',ho.goal_text(w['mission']['definition']['historical_calculation']['parameters']))

    def test_dsh_only_prompt_knows_the_goal_owner_and_current_progress(self):
        import json
        from backend import dsh_simulation
        text=dsh_simulation.prompt(self.world())
        goal=json.loads(text.split('\n目标：',1)[1].split('\n',1)[0])
        self.assertEqual(goal['objective_team'],'blue')
        self.assertEqual(goal['required_turns'],2)
        self.assertEqual((goal['turn'],goal['progress']),(0,0))

    def test_dsh_only_estimates_still_use_the_program_owned_blue_goal(self):
        from backend import dsh_simulation
        from gentactix import sim_clock
        w=self.world();self.position(w,'blue',True);self.position(w,'red',False)
        w['mission']['turn']=1;w['current_time'],w['simulation_clock']=sim_clock.target(w,'30分钟');missions.evaluate(w)
        from verify_dsh_resources import model_result
        result=model_result(w)
        after=dsh_simulation.apply(w,result,'30分钟')
        self.assertEqual(after['mission']['winner'],'blue')
        self.assertNotIn('afsim',after);self.assertEqual(after['dsh_execution']['effects_source'],'dsh_model_estimate')

    def test_sourced_maryang_guidance_sets_blue_attack_without_rewriting_facts(self):
        from backend import scenario_builder
        from verify_korean_series import CASES
        battle,phase=CASES['KW06-autumn1951'];basis=scenario_builder.historical_basis(battle,phase)
        self.assertEqual(basis['configuration_template']['goal']['team'],'blue')
        self.assertEqual(basis['configuration_template']['goal']['profile'],'assault')
        self.assertTrue(basis['objective_guidance']['sources'])
        self.assertIn('第一线',basis['objective_guidance']['objective_label'])
        self.assertIsNone(basis['configuration_template']['actors']['kw.au.rar3']['personnel'])

    def test_new_native_builder_cannot_drop_the_explicit_goal_owner(self):
        from backend import scenario_builder as b
        from tools.qa.korean_series_fixture import inputs as korea
        snapshot,params=korea('KW06-autumn1951')
        basis=b.historical_basis(snapshot['definition']['battle'],snapshot['phase_id'])
        context={'scenario_composer':{'kind':'historical_operation','initial':snapshot,'basis':basis}}
        self.assertNotIn('team',params['goal'])
        result=b.execute_tool(context,{'tool':'validate_scenario_configuration','args':{'configuration':params}})
        self.assertFalse(result['valid']);self.assertIn('目标方',result['error'])
        params['goal']['team']='blue'
        self.assertTrue(b.execute_tool(context,{'tool':'validate_scenario_configuration','args':{'configuration':params}})['valid'])


if __name__=='__main__':unittest.main()
