"""Historical open simulations finish on goals; legacy clocks remain frozen."""
import copy
import unittest

from gentactix import historical_initial, historical_operations as op, missions
from tools.qa.historical_operational_fixture import inputs, NOTE


def configured(mode='objectives',profile='assault',required=2):
    snapshot,params=inputs()
    params['goal'].update(team='red',termination_mode=mode,profile=profile,deadline_turn=1,
                          required_turns=required,radius_km=2)
    params['rules']['goal_profile']=profile
    return snapshot,params


class ObjectiveCompletionTests(unittest.TestCase):
    def test_unmet_goals_can_continue_beyond_planning_rounds_and_restore(self):
        s,p=configured();w=op.initial(s,p)
        for turn in (1,2,3):
            w['mission']['turn']=turn;missions.evaluate(w)
            self.assertEqual(w['mission']['status'],'active')
            self.assertTrue(missions.validate(w))
        self.assertEqual(op.from_binding(w['mission']['definition']['historical_calculation']),w['mission']['definition'])

    def test_objective_success_still_requires_continuous_control(self):
        s,p=configured();w=op.initial(s,p)
        for u in w['blue_units']:u['lat']+=.1
        for turn in (1,2):
            w['mission']['turn']=turn;missions.evaluate(w)
            self.assertEqual(w['mission']['status'],'completed' if turn==2 else 'active')
        self.assertEqual(w['mission']['winner'],'red')

    def test_objective_owner_elimination_still_ends_battle(self):
        s,p=configured();w=op.initial(s,p)
        for u in w['red_units']:u['personnel']['current']=0
        w['mission']['turn']=1;missions.evaluate(w)
        self.assertEqual(w['mission']['status'],'completed');self.assertEqual(w['mission']['winner'],'blue')

    def test_delay_and_organization_require_sustained_conditions(self):
        for profile in ('delay','underground'):
            with self.subTest(profile=profile):
                s,p=configured(profile=profile,required=3);w=op.initial(s,p)
                for turn in (1,2,3):
                    w['mission']['turn']=turn;missions.evaluate(w)
                    self.assertEqual(w['mission']['status'],'completed' if turn==3 else 'active')

    def test_source_window_limits_initial_time_but_not_open_ending(self):
        s,p=configured(required=1)
        phase=next(v for v in s['definition']['phases'] if v['id']==s['phase_id'])
        phase['execution_window']={'start':'1938-03-31T00:00','end':'1938-03-31T01:00',
            'kind':'model_scope_limit','note':NOTE,'evidence':copy.deepcopy(s['definition']['units'][0]['evidence'])}
        s['definition_hash']=historical_initial.digest(s['definition'])
        p['goal']['deadline_turn']=20
        self.assertTrue(op.initial(s,p)['mission'])
        limited=copy.deepcopy(p);limited['goal']['termination_mode']='deadline'
        with self.assertRaisesRegex(ValueError,'计算窗口'):op.initial(s,limited)
        late=copy.deepcopy(p);late['clock']['start']='1938-03-31 02:00'
        with self.assertRaisesRegex(ValueError,'起点|计算窗口'):op.initial(s,late)

    def test_legacy_and_explicit_deadline_still_expire(self):
        s,p=inputs();legacy=op.definition(s,p)
        self.assertNotIn('termination_mode',legacy)
        w=missions.from_definition(legacy);w['mission']['turn']=2;missions.evaluate(w)
        self.assertEqual(w['mission']['status'],'completed')
        s,p=configured(mode='deadline',required=1);w=op.initial(s,p)
        w['mission']['turn']=1;missions.evaluate(w)
        self.assertEqual(w['mission']['reason'],'截止回合目标未达成')

    def test_native_script_has_no_time_terminal_for_objectives(self):
        from backend import afsim_world
        s,p=configured();w=op.initial(s,p)
        native=afsim_world.compile_scene(w,[],1800,native_rules=True)['native_model']['script']
        terminal=next(line for line in native.splitlines() if 'bool terminal=' in line)
        self.assertNotIn('turn>=',terminal)
        self.assertIn('progress>=2',native)

    def test_builder_binds_selected_termination_before_model_execution(self):
        from backend import scenario_builder as b
        basis=b.historical_basis('抗日战争-万家岭战役-1938.09下旬至1938.10',
            time_step='2天',termination_mode='objectives')
        self.assertEqual(basis['configuration_template']['goal']['termination_mode'],'objectives')
        self.assertIn('连续',basis['goal_semantics']['delay'])
        self.assertNotIn('截止回合',basis['goal_semantics']['delay'])
        with self.assertRaisesRegex(ValueError,'计算窗口'):
            b.historical_basis(basis['battle'],time_step='2天',termination_mode='deadline')

    def test_objective_budget_is_a_rolling_plan_not_zero_after_reference(self):
        from gentactix import sustainment,resource_readiness
        s,p=configured();w=op.initial(s,p);w['mission']['turn']=3
        self.assertGreater(sustainment.assess(w)['remaining_turns'],0)
        r=resource_readiness.assess(w)
        self.assertGreater(r['remaining_hours'],0)
        self.assertEqual(r['horizon_kind'],'rolling_plan')

    def test_joint_goals_finish_on_sustained_control_not_the_planning_round(self):
        from tools.qa.campaign_fixture import inputs as campaign_inputs
        s,p=campaign_inputs();p['goal'].update(termination_mode='objectives',deadline_turn=20,required_turns=2)
        w=op.initial(s,p)
        for turn in (1,2):
            w['mission']['turn']=turn;missions.evaluate(w)
            self.assertEqual(w['mission']['status'],'completed' if turn==2 else 'active')

    def test_builder_does_not_let_model_silently_restore_time_limit(self):
        from backend import scenario_builder,scenario_assembly
        s,p=configured(required=1)
        basis=scenario_builder.historical_basis(s['definition']['battle'],s['phase_id'],termination_mode='objectives')
        p['goal']['termination_mode']='deadline'
        with self.assertRaisesRegex(ValueError,'结束方式'):
            scenario_assembly.validate_build_constraints(p,basis)

    def test_dsh_observation_discloses_objective_based_termination(self):
        from backend import afsim_state,dsh_simulation
        s,p=configured();w=op.initial(s,p)
        context=afsim_state.mission_context(w)
        self.assertEqual(context['termination_mode'],'objectives')
        self.assertIn('objectives',dsh_simulation.prompt(w))


if __name__=='__main__':unittest.main()
