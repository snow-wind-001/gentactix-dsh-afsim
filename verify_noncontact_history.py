"""Sourced non-contact transfers must not invent an opposing force."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi,historical_operations as ho,missions,commands,synthetic_history
from tools.qa.noncontact_fixture import CASES,inputs


class NoncontactHistoryTests(unittest.TestCase):
    def test_sourced_profiles_keep_unknowns_and_other_axes_outside(self):
        for identity,(battle,phase) in CASES.items():
            with self.subTest(profile=identity):
                s=hi.initial(battle,phase)['historical_initial'];hi.validate_definition(s['definition'])
                units={u['id']:u for u in s['definition']['units']};ids=ho.partition(s)
                self.assertEqual(len(ids),1);self.assertEqual({units[i]['team'] for i in ids},{'red'})
                self.assertTrue(all(f['value'] is None for u in units.values() for f in u['facts'].values()))
                self.assertFalse(any(s['definition']['coverage'][k] for k in ('order_of_battle_complete','opening_deployment_complete','strength_complete')))
                with self.assertRaises(ValueError):ho.partition(hi.initial(battle)['historical_initial'])

    def test_selected_phase_discloses_sourced_interaction_in_existing_skill_basis(self):
        from backend.scenario_builder import historical_basis
        for battle,phase in CASES.values():
            basis=historical_basis(battle)
            self.assertTrue(basis['ready']);self.assertEqual(basis['initial']['phase_id'],phase)
            self.assertEqual(basis['interaction']['kind'],'non_contact_transfer')
            self.assertEqual(basis['interaction']['active_teams'],['red'])
            self.assertTrue(basis['excluded_references'])

    def test_one_sided_exception_requires_valid_source_bound_metadata(self):
        s,_=inputs();definition=copy.deepcopy(s['definition'])
        phase=next(p for p in definition['phases'] if p['id']==s['phase_id'])
        for bad in ({'kind':'non_contact_transfer','active_teams':['red'],'scope':'x','evidence':[]},
                    {'kind':'free_combat','active_teams':['red'],'scope':'x','evidence':phase['evidence']},
                    {'kind':'non_contact_transfer','active_teams':[],'scope':'x','evidence':phase['evidence']}):
            d=copy.deepcopy(definition);next(p for p in d['phases'] if p['id']==s['phase_id'])['interaction']=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):hi.validate_definition(d)
        phase.pop('interaction');s=copy.deepcopy(s);s['definition']=definition;s['definition_hash']=hi.digest(definition)
        with self.assertRaisesRegex(ValueError,'双方'):ho.partition(s)

    def test_declared_noncontact_scope_does_not_silently_discard_a_present_enemy(self):
        s,_=inputs();s=copy.deepcopy(s)
        enemy=next(u for u in s['definition']['units'] if u['team']=='blue')
        next(p for p in enemy['presence'] if p['phase_id']==s['phase_id'])['status']='reported_present'
        s['definition_hash']=hi.digest(s['definition'])
        with self.assertRaisesRegex(ValueError,'范围|非接敌'):ho.partition(s)

    def test_shared_initial_and_frozen_restore_never_invent_a_blue_actor_or_warehouse(self):
        for identity in CASES:
            s,p=inputs(identity);before=copy.deepcopy(s);w=ho.initial(s,p)
            self.assertEqual(len(w['red_units']),1);self.assertEqual(w['blue_units'],[])
            self.assertEqual({n['team'] for n in w['supply_nodes']},{'red'})
            self.assertEqual(s,before)
            self.assertEqual(ho.from_binding(w['mission']['definition']['historical_calculation'])['initial_state']['blue_units'],[])
            for purpose in ('analysis','historical','synthetic'):
                for engine in ('afsim','narrative'):self.assertEqual(hi.initial(s['definition']['battle'],s['phase_id'],purpose=purpose,engine=engine)['historical_initial'],s)

    def test_inactive_support_cannot_introduce_stock_or_an_opposing_goal(self):
        s,p=inputs()
        for key in ('stock','inventory','goal'):
            bad=copy.deepcopy(p)
            if key=='stock':bad['support']['blue']['stock']=1
            elif key=='inventory':bad['support']['blue']['inventory']['shells']=1
            else:bad['goal']['team']='blue'
            with self.subTest(key=key),self.assertRaises(ValueError):ho.initial(s,bad)

    def test_numeric_feedback_identifies_the_actual_field_and_minimum(self):
        s,p=inputs();identity=next(iter(p['actors']))
        p['actors'][identity]['formation']['dispersion_km2']=.0004
        with self.assertRaisesRegex(ValueError,r'actors\.'+identity+r'\.formation\.dispersion_km2.*0.001'):
            ho.initial(s,p)

    def test_rule_numeric_feedback_does_not_invite_changing_unrelated_boolean_switches(self):
        s,p=inputs();p['rules']['command_base_s']=True
        with self.assertRaisesRegex(ValueError,r'rules.command_base_s'):
            ho.initial(s,p)

    def test_unused_engineering_coefficient_still_has_explicit_registered_bounds(self):
        s,p=inputs();p['facility']['crossing_model']['build_progress_per_engineer_hour']=0
        with self.assertRaisesRegex(ValueError,r'build_progress_per_engineer_hour.*0.0001'):
            ho.initial(s,p)

    def test_explicit_required_ferry_supplies_unfilled_shape_without_inventing_a_boat(self):
        from backend import scenario_builder,scenario_assembly
        battle,phase=CASES['LM13-jinsha1936'];basis=scenario_builder.historical_basis(battle,phase)
        before=copy.deepcopy(basis['initial'])
        scenario_assembly.prepare_required_models(basis,['formation-ferry-1'])
        ferry=basis['configuration_template']['facility']['crossing_model']['ferry']
        self.assertEqual(ferry['version'],'formation-ferry-1')
        self.assertIsNone(ferry['boats'][0]['seats']);self.assertIsNone(ferry['boats'][0]['id'])
        self.assertEqual(basis['initial'],before)

    def test_full_configuration_tool_rejects_encoded_json_with_actionable_shape_feedback(self):
        from backend import scenario_builder
        s,p=inputs();basis=scenario_builder.historical_basis(s['definition']['battle'],s['phase_id'],time_step='1分钟')
        import json
        response=scenario_builder._historical_tool({'initial':s,'basis':basis},'validate_scenario_configuration',{'configuration':json.dumps(p)})
        self.assertFalse(response['valid']);self.assertIn('JSON对象',response['error'])
        self.assertIn('clock',response['expected_top_level']);self.assertEqual(response['received_configuration_type'],'str')

    def test_small_but_coupled_transfer_reuses_existing_native_staged_workflow(self):
        import os,tempfile
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as builder,harness_engine as h
        s,p=inputs();before=copy.deepcopy(s)
        # This mocked model must honor the request's objective-driven mode,
        # exactly as a real staged model is now rechecked by the host.
        p['goal']['termination_mode']='objectives'
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}), \
                patch.object(builder,'build_historical_staged',return_value=(p,{'source':'dsh_native_skill','skill':'historical-unit-configuration'})) as staged, \
                patch.object(h,'_run_brain',side_effect=AssertionError('Do not use unstructured full JSON for coupled transfers')):
            response=TestClient(main.app).post('/api/historical-scenarios/build',json={
                'battle':s['definition']['battle'],'phase_id':s['phase_id'],'execution_backend':'narrative',
                'time_step':'1分钟','required_models':['formation-ferry-1']})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(staged.call_count,1)
            self.assertEqual(staged.call_args.args[0]['interaction']['kind'],'non_contact_transfer')
            self.assertEqual(s,before)

    def test_noncontact_goals_are_transport_not_trivial_combat_success(self):
        s,p=inputs();bad=copy.deepcopy(p);bad['rules']['goal_profile']='assault';bad['goal']['profile']='assault'
        with self.assertRaisesRegex(ValueError,'转移|非接敌'):ho.initial(s,bad)
        w=ho.initial(s,p);w['mission']['turn']=1
        missions.evaluate(w);self.assertEqual(w['mission']['status'],'active')

    def test_failed_transfer_is_a_missed_goal_not_a_victory_for_a_fictitious_enemy(self):
        w=ho.initial(*inputs());w['mission']['turn']=w['mission']['definition']['deadline_turn']
        missions.evaluate(w)
        self.assertEqual(w['mission']['status'],'completed');self.assertIsNone(w['mission']['winner'])
        from tools.qa.historical_crossing_fixture import inputs as combat_inputs
        legacy=ho.initial(*combat_inputs());legacy['mission']['turn']=legacy['mission']['definition']['deadline_turn']
        missions.evaluate(legacy);self.assertEqual(legacy['mission']['winner'],'blue')

    def test_native_scene_has_one_real_ground_actor_and_surface_ferry(self):
        from backend import afsim_world
        w=ho.initial(*inputs());target=w['combined_arms']['bridge']['crossing_model']['banks']['b']
        order=[{'unit':w['red_units'][0]['name'],'action':'move',**target}]
        scene=afsim_world.compile_scene(w,order,60,native_rules=True)
        self.assertEqual(len(scene['entities']),1)
        self.assertEqual({r['team'] for r in scene['entities'].values()},{'red'})
        self.assertIn('WSF_SURFACE_MOVER',scene['script'])

    def test_no_target_means_no_attack_action_in_existing_control_menu(self):
        w=ho.initial(*inputs());session={'id':'a123456789ab','war_state':w,'turn_count':0,'time_step':'1分钟','simulation_mode':'open'}
        result=commands.capabilities(session,w['red_units'][0],'red')
        self.assertIn('move',result['actions']);self.assertIn('hold',result['actions'])
        self.assertFalse(set(result['actions'])&{'fire','bombard','suppress','air_support'})

    def test_synthetic_default_retains_same_empty_side_and_does_not_remove_existing_actors(self):
        w=ho.initial(*inputs());binding=w['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding)
        self.assertEqual(seed['configuration']['teams']['blue'],[])
        derived=synthetic_history.definition(binding,seed['configuration'])
        self.assertEqual(derived['initial_state']['blue_units'],[])
        self.assertEqual(len(derived['initial_state']['red_units']),1)
        bad=copy.deepcopy(seed['configuration']);bad['teams']['red']=[]
        with self.assertRaises(ValueError):synthetic_history.definition(binding,bad)


if __name__=='__main__':unittest.main()
