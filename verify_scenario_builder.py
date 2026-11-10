"""Historical reference integrity and staged exercise construction contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from gentactix import combined_arms,missions,scenario_basis


class ScenarioBuilderTests(unittest.TestCase):
    def test_rejected_model_candidate_is_regenerated_and_validated_once(self):
        from backend import scenario_builder as b, harness_engine as h
        seed = scenario_basis.exercise_seed('CA-AJ18-v1')
        context = {'scenario_composer': {'mission_id': 'CA-AJ18-v1', 'seed': seed}}
        candidate = b.execute_tool(context, {'tool': 'get_scenario_basis'})['configuration']
        observer = h.RunObserver('test')
        prompts = []
        names = ('read_scenario_skill', 'get_scenario_basis', 'validate_scenario_configuration')
        def run(prompt, *args, **kwargs):
            prompts.append(prompt)
            observer.runs.append({'events': [{'type': 'tool/call', 'name': name} for name in names]})
            return SimpleNamespace(final_response=('{"configuration":' if len(prompts) == 1 else
                                   json.dumps({'configuration': candidate, 'explanation': 'test'})))
        with patch.object(h, '_run_brain', side_effect=run):
            answer, config = b.generate_exercise_candidate('CA-AJ18-v1', 'initial', context, observer)
        self.assertEqual(len(prompts), 2)
        self.assertIn('配置未提交', prompts[1])
        self.assertTrue(observer.runs[0]['rejection'] == 'invalid_scenario_candidate')
        self.assertEqual(answer['configuration'], candidate)
        self.assertEqual(config['historical_basis'], seed['configuration']['historical_basis'])

    def test_retries_are_bounded_and_tool_evidence_cannot_cross_attempts(self):
        from backend import scenario_builder as b, harness_engine as h
        seed = scenario_basis.exercise_seed('CA-AJ18-v1')
        context = {'scenario_composer': {'mission_id': 'CA-AJ18-v1', 'seed': seed}}
        candidate = b.execute_tool(context, {'tool': 'get_scenario_basis'})['configuration']
        observer = h.RunObserver('test')
        calls = []
        def run(*args, **kwargs):
            names = ('read_scenario_skill', 'get_scenario_basis') if not calls else ('validate_scenario_configuration',)
            calls.append(names)
            observer.runs.append({'events': [{'type': 'tool/call', 'name': name} for name in names]})
            return SimpleNamespace(final_response=json.dumps({'configuration': candidate}))
        with patch.object(h, '_run_brain', side_effect=run):
            with self.assertRaisesRegex(ValueError, '调用证据'):
                b.generate_exercise_candidate('CA-AJ18-v1', 'initial', context, observer)
        self.assertEqual(len(calls), 2)

    def test_cancelled_scenario_candidate_does_not_call_model(self):
        from backend import scenario_builder as b, harness_engine as h
        observer = h.RunObserver('test'); observer.cancel_requested = True
        with patch.object(h, '_run_brain') as run:
            with self.assertRaisesRegex(RuntimeError, '取消'):
                b.generate_exercise_candidate('CA-AJ18-v1', 'initial', {}, observer)
        run.assert_not_called()

    def test_build_route_never_stages_rejected_candidate(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b, harness_engine as h
        seed = scenario_basis.exercise_seed('CA-AJ18-v1')
        context = {'scenario_composer': {'mission_id': 'CA-AJ18-v1', 'seed': seed}}
        candidate = b.execute_tool(context, {'tool': 'get_scenario_basis'})['configuration']
        bad = copy.deepcopy(candidate); bad['unexpected'] = True
        names = ('read_scenario_skill', 'get_scenario_basis', 'validate_scenario_configuration')
        calls = []
        def run(prompt, *args, **kwargs):
            calls.append(prompt)
            kwargs['observer'].runs.append({'events': [{'type': 'tool/call', 'name': name} for name in names]})
            return SimpleNamespace(final_response=json.dumps({'configuration': bad if len(calls) == 1 else candidate}))
        with patch.object(h, '_run_brain', side_effect=run), patch.object(b, 'stage', return_value={'id': 'validated'}) as stage:
            result = TestClient(main.app).post('/api/scenarios/build', json={'mission_id': 'CA-AJ18-v1', 'execution_backend': 'narrative'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(calls), 2)
        stage.assert_called_once()
        self.assertNotIn('unexpected', stage.call_args.args[1])

    def test_build_route_does_not_echo_invalid_model_response(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as b, harness_engine as h
        def run(prompt, *args, **kwargs):
            kwargs['observer'].runs.append({'events': []})
            return SimpleNamespace(final_response='{"private-model-marker":')
        with patch.object(h, '_run_brain', side_effect=run) as model, patch.object(b, 'stage') as stage:
            result = TestClient(main.app).post('/api/scenarios/build', json={'mission_id': 'CA-AJ18-v1', 'execution_backend': 'narrative'})
        self.assertEqual(result.status_code, 502)
        self.assertIn('JSON', result.text)
        self.assertNotIn('private-model-marker', result.text)
        self.assertEqual(model.call_count, 2)
        stage.assert_not_called()

    def test_all_catalog_seeds_bind_both_sides_without_fabricated_historical_counts(self):
        specs=combined_arms.catalog();self.assertEqual(len(specs),45)
        for spec in specs:
            with self.subTest(battle=spec['battle']):
                seed=scenario_basis.exercise_seed(spec['id']);refs={r['id']:r for r in seed['basis']['units']}
                for team in ('red','blue'):
                    for row in seed['configuration']['teams'][team]:
                        self.assertEqual(refs[row['basis_id']]['team'],team)
                        self.assertIsNone(refs[row['basis_id']]['actual_personnel'])
                        self.assertIsNone(refs[row['basis_id']]['actual_tactical_position'])
                world=missions.initial(spec['id'],configuration=seed['configuration']);missions.validate(world)
                self.assertTrue(all(u.get('historical_reference') and u.get('parameter_sources') for _,u in missions.units(world)))

    def test_source_hash_and_side_cannot_be_forged(self):
        seed=scenario_basis.exercise_seed('CA-AJ18-v1');c=seed['configuration']
        bad=copy.deepcopy(c);bad['historical_basis']['basis_hash']='invented'
        with self.assertRaises(ValueError):combined_arms.configure('CA-AJ18-v1',bad)
        bad=copy.deepcopy(c);bad['teams']['blue'][0]['basis_id']=c['teams']['red'][0]['basis_id']
        with self.assertRaises(ValueError):combined_arms.configure('CA-AJ18-v1',bad)

    def test_map_placement_must_stay_inside_the_local_theater(self):
        c=scenario_basis.exercise_seed('CA-AJ18-v1')['configuration']
        c['teams']['blue'][0]['position']={'lat':40.792,'lng':40.792}
        with self.assertRaisesRegex(ValueError,'边界'):combined_arms.configure('CA-AJ18-v1',c)

    def test_coordinate_integer_and_float_lexemes_have_same_variant_definition(self):
        c=scenario_basis.exercise_seed('CA-AJ18-v1')['configuration']
        center=combined_arms.definition('CA-AJ18-v1')['map_center']
        c['teams']['red'][0]['position']=center
        a=combined_arms.configure('CA-AJ18-v1',c)
        b=combined_arms.configure('CA-AJ18-v1',copy.deepcopy(c))
        self.assertEqual(missions.digest(a),missions.digest(b))

    def test_native_skill_uses_only_existing_domain_bridge(self):
        from backend import scenario_builder as b,harness_engine as h
        context={'scenario_composer':{'mission_id':'CA-AJ18-v1','seed':scenario_basis.exercise_seed('CA-AJ18-v1')}}
        r=b.execute_tool(context,{'tool':'read_scenario_skill'})
        self.assertIn('get_scenario_basis',r['content'])
        self.assertIn('模板',r['upstream_content'])
        policy=h.role_policy('scenario-builder',tools=True)
        self.assertEqual(set(policy['allowed_tools']),{'read_scenario_skill','get_scenario_basis','update_scenario_configuration','validate_scenario_configuration'})
        self.assertEqual(policy['reasoning_effort'],'medium')

    def test_invalid_top_level_explains_schema_without_silently_dropping_fields(self):
        from backend import scenario_builder as b
        seed=scenario_basis.exercise_seed('CA-AJ18-v1');config=copy.deepcopy(seed['configuration'])
        config['map_center']=seed['map_center']
        result=b.execute_tool({'scenario_composer':{'mission_id':'CA-AJ18-v1','seed':seed}},
            {'tool':'validate_scenario_configuration','args':{'configuration':config}})
        self.assertFalse(result['valid'])
        self.assertIn('historical_basis',result['expected_top_level'])
        self.assertIn('map_center',config)

    def test_model_edits_do_not_need_to_regenerate_readonly_provenance(self):
        from backend import scenario_builder as b
        seed=scenario_basis.exercise_seed('CA-AJ18-v1');context={'scenario_composer':{'mission_id':'CA-AJ18-v1','seed':seed}}
        view=b.execute_tool(context,{'tool':'get_scenario_basis'})
        self.assertEqual(set(view['configuration']),{'teams'})
        bound=b.bind_model_configuration('CA-AJ18-v1',view['configuration'])
        self.assertEqual(bound['historical_basis'],seed['configuration']['historical_basis'])
        self.assertTrue(b.execute_tool(context,{'tool':'validate_scenario_configuration','args':{'configuration':view['configuration']}})['valid'])
        wrong=copy.deepcopy(bound);wrong['historical_basis']['basis_hash']='forged'
        with self.assertRaises(ValueError):b.bind_model_configuration('CA-AJ18-v1',wrong)

    def test_unstaged_historical_basis_cannot_create_an_exercise(self):
        from fastapi.testclient import TestClient
        from backend import main
        config=scenario_basis.exercise_seed('CA-AJ18-v1')['configuration']
        r=TestClient(main.app).post('/api/sessions',json={'scenario':'不允许伪造skill证据','mission_id':'CA-AJ18-v1','execution_backend':'afsim','synthetic_configuration':config})
        self.assertEqual(r.status_code,422)
        self.assertIn('skill',r.text)

    def test_draft_from_an_old_model_requires_native_revalidation(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder
        config=scenario_basis.exercise_seed('CA-AJ18-v1')['configuration']
        record={'mission_id':'CA-AJ18-v1','configuration':config,'definition_hash':'older-model',
                'construction':{'source':'dsh_native_skill'}}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}),patch.object(scenario_builder,'load',return_value=record),patch('tools.afsim.launch.status',return_value={'available':True}):
            r=TestClient(main.app).post('/api/sessions',json={'scenario':'旧模型草稿拒收','mission_id':'CA-AJ18-v1','execution_backend':'afsim','synthetic_configuration':config,'scenario_draft_id':'a'*32})
        self.assertEqual(r.status_code,422,r.text)
        self.assertIn('更新',r.text)

    def test_cancelled_staging_writes_no_draft_and_path_is_confined(self):
        from backend import scenario_builder as b
        seed=scenario_basis.exercise_seed('CA-AJ18-v1')
        def execute(session,scene,*a,**kw):
            return {identity:entry['origin'] for identity,entry in scene['entities'].items()},{'source':'explicit_test_fixture'}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(Path(directory)/'sessions')}),patch.object(b.afsim_world,'run_scene',side_effect=execute):
            with self.assertRaisesRegex(RuntimeError,'取消'):
                b.stage('CA-AJ18-v1',seed['configuration'],construction={'source':'test_fixture'},cancel_check=lambda:True)
            self.assertFalse(b.directory().exists())
            with self.assertRaises(ValueError):b.load('../../outside')


if __name__=='__main__':unittest.main()
