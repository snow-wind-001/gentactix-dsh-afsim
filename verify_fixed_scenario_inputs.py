"""Fixed user numerical inputs must survive native model drafts without repair."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.qa.historical_operational_fixture import BATTLE, inputs


class FixedScenarioInputsTests(unittest.TestCase):
    def setUp(self):
        from backend import scenario_builder, scenario_assembly
        from gentactix import scenario_constraints
        self.builder, self.assembly_module, self.constraints = scenario_builder, scenario_assembly, scenario_constraints
        self.basis = scenario_builder.historical_basis(BATTLE, 'taierzhuang', termination_mode='objectives')
        self.parameters = inputs()[1]
        self.parameters['goal']['termination_mode'] = 'objectives'
        self.parameters['goal']['team'] = 'red'
        self.parameters['supply_distribution'] = copy.deepcopy(self.basis['configuration_template']['supply_distribution'])
        for actor in self.parameters['actors'].values():
            actor['formation'].setdefault('motorized', self.parameters['rules']['motorized'])
        self.fixed = [{'path': ['area', 'radius_km'], 'value': self.parameters['area']['radius_km']},
                      {'path': ['actors', 'ww2.cn.division31', 'personnel'], 'value': 6000}]
        self.parameters['actors']['ww2.cn.division31']['personnel'] = 6000

    def assembly(self):
        self.constraints.prepare(self.basis, self.fixed)
        assembly = self.assembly_module.create(self.basis)
        self.addCleanup(self.assembly_module.close, assembly.id)
        return assembly

    def globals(self, assembly, **changes):
        parameters = copy.deepcopy(self.parameters)
        parameters.update(changes)
        return assembly.tool('globals', 'update_scenario_configuration', {'revision': assembly.revision,
            'patch': {k:v for k,v in parameters.items() if k not in ('actors', 'format', 'phase_id')}})

    def test_conflicting_global_write_is_atomic_and_names_the_lock(self):
        a = self.assembly()
        original = copy.deepcopy(a.configuration)
        result = self.globals(a, area={**self.parameters['area'], 'radius_km': 30})
        self.assertFalse(result['updated'])
        self.assertEqual(a.configuration, original)
        self.assertEqual(a.revision, 0)
        self.assertEqual(result['fixed_parameter_conflicts'][0]['path'], ['area', 'radius_km'])
        self.assertTrue(self.globals(a)['updated'])

    def test_assigned_actor_cannot_overwrite_user_personnel(self):
        a = self.assembly()
        self.assertTrue(self.globals(a)['updated'])
        actors = copy.deepcopy(self.parameters['actors'])
        actors['ww2.cn.division31']['personnel'] = 5000
        before = copy.deepcopy(a.configuration)
        result = a.tool('actors:0', 'update_scenario_configuration', {'revision': a.revision, 'patch': {'actors': actors}})
        self.assertFalse(result['updated'])
        self.assertEqual(a.configuration, before)
        self.assertEqual(a.revision, 1)

    def test_seed_does_not_count_as_actual_model_configuration(self):
        a = self.assembly()
        self.assertEqual(a.configuration['actors']['ww2.cn.division31']['personnel'], 6000)
        self.assertFalse(a.global_ready)
        self.assertFalse(a.filled)
        self.assertFalse(a.tool('final', 'validate_scenario_configuration', {})['valid'])

    def test_unfixed_numbers_can_change_and_int_float_lexemes_compare_numerically(self):
        self.fixed[0]['value'] = float(self.fixed[0]['value'])
        self.fixed[1]['value'] = 6000.0
        a = self.assembly()
        self.assertIs(type(a.configuration['actors']['ww2.cn.division31']['personnel']), int)
        self.assertIs(type(a.basis['fixed_parameters']['values'][1]['value']), int)
        changed = {**self.parameters['area'], 'terrain_factor': 1.25}
        self.assertTrue(self.globals(a, area=changed)['updated'])
        self.assertEqual(a.configuration['area']['terrain_factor'], 1.25)

    def test_continuous_measures_are_not_restricted_by_integral_prior_literals(self):
        from verify_supply_schedule import config
        basis=copy.deepcopy(self.basis)
        template=basis['configuration_template'];template['area']['radius_km']=20
        template['area']['center']['lat']=34
        template['supply_schedule']=config()
        catalog={tuple(f['path']):f for f in self.constraints.fields(template,basis['actors'])}
        for path in [('area','radius_km'),('area','center','lat'),('supply_schedule','passive_work_per_hour'),
                     ('supply_schedule','warehouse_tons_per_hour','red-historical-supply'),
                     ('rules','cargo_mass_tons','fuel_liters')]:
            self.assertFalse(catalog[path]['integer'],path)
        self.assertTrue(catalog[('supply_schedule','period_seconds')]['integer'])
        self.assertTrue(catalog[('actors','ww2.cn.division31','personnel')]['integer'])
        # An actual global draft with a valid fractional radius must be writable.
        self.basis['configuration_template']['area']['radius_km']=20
        self.fixed[0]['value']=20.5;self.parameters['area']['radius_km']=20.5
        a=self.assembly();self.assertTrue(self.globals(a)['updated'])

    def test_bulk_known_inputs_fit_the_largest_current_catalogue(self):
        # A catalogue-shaped input fixture, not invented historical forces.
        count=2152
        basis={'configuration_template':{'actors':{f'qa{i}':{'personnel':10} for i in range(count)}},'actors':[]}
        rows=[{'path':['actors',f'qa{i}','personnel'],'value':10} for i in range(count)]
        request=self.builder.HistoricalBuildRequest.model_validate({'battle':BATTLE,'phase_id':'taierzhuang','fixed_parameters':rows})
        self.constraints.prepare(basis,request.fixed_parameters)
        self.assertEqual(len(basis['fixed_parameters']['values']),count)

    def test_unknown_readonly_duplicate_and_nonfinite_paths_reject_before_mutation(self):
        for rows in ([{'path':['actors','fake','personnel'],'value':10}],
                     [{'path':['campaign_scope','window','version'],'value':1}],
                     [{'path':['goal','description'],'value':1}],
                     [self.fixed[0],self.fixed[0]],
                     [{'path':['area','radius_km'],'value':True}],
                     [{'path':['area','radius_km'],'value':float('nan')}],
                     [{'path':['area','radius_km'],'value':10**1000}],
                     [{'path':['area','radius_km'],'value':'20'}]):
            basis = copy.deepcopy(self.basis)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.constraints.prepare(basis, rows)
            self.assertEqual(basis, self.basis)

    def test_view_exposes_only_global_and_own_unit_locks(self):
        basis = self.builder.historical_basis('抗日战争-车桥战役-1944.03.05至1944.03.06', 'core_march5_6', version='1.1.0')
        ids = list(basis['configuration_template']['actors'])
        fixed = [{'path':['actors',ids[-1],'personnel'],'value':1234}, {'path':['area','radius_km'],'value':20}]
        self.constraints.prepare(basis, fixed)
        a = self.assembly_module.create(basis)
        self.addCleanup(self.assembly_module.close,a.id)
        for part in ['globals','actors:0']:
            view = a.tool(part,'get_scenario_basis',{})
            self.assertEqual(view['fixed_parameters']['values'], [fixed[1]])
        last = a.tool(a.parts[-1], 'get_scenario_basis', {})
        self.assertIn(fixed[0],last['fixed_parameters']['values'])
        self.assertNotIn('fixed_parameter_fields', last)

    def test_ui_catalogue_has_labels_and_optional_supply_fields_without_locking_them(self):
        fields = self.basis['fixed_parameter_fields']
        field = next(f for f in fields if f['path']==['actors','ww2.cn.division31','personnel'])
        self.assertIn('第31师',field['label'])
        scheduled = next(f for f in fields if f['path']==['supply_schedule','passive_work_per_hour'])
        self.assertIn('scheduled-supply-1',scheduled['required_models'])
        self.assertNotIn('fixed_parameters',self.basis)

    def test_final_stage_rejects_bypass_before_native_load_or_checkpoint_save(self):
        construction={'source':'dsh_native_skill','fixed_parameters':{'version':self.constraints.VERSION,'values':self.fixed}}
        bad=copy.deepcopy(self.parameters);bad['area']['radius_km']=30
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(Path(td)/'sessions')}),patch.object(self.builder,'_load_world') as native:
            with self.assertRaisesRegex(ValueError,'固定'):
                self.builder.stage_historical(self.basis['initial'],bad,construction=construction,execution_backend='narrative')
            native.assert_not_called()
            self.assertFalse(self.builder.directory().exists())

    def test_api_preflight_rejects_unknown_fixed_field_without_model_call(self):
        from fastapi.testclient import TestClient
        from backend import main
        with patch.object(self.builder,'build_historical_staged') as model:
            r=TestClient(main.app).post('/api/historical-scenarios/build',json={'battle':BATTLE,'phase_id':'taierzhuang',
                'execution_backend':'narrative','fixed_parameters':[{'path':['actors','wrong','personnel'],'value':10}]})
        self.assertEqual(r.status_code,422,r.text)
        model.assert_not_called()

    def test_optional_schedule_input_requires_its_model_before_seeding(self):
        row={'path':['supply_schedule','passive_work_per_hour'],'value':4}
        before=copy.deepcopy(self.basis)
        with self.assertRaises(ValueError):self.constraints.prepare(self.basis,[row])
        self.assertEqual(self.basis,before)
        self.assembly_module.prepare_required_models(self.basis,['scheduled-supply-1'])
        self.constraints.prepare(self.basis,[row])
        self.assertEqual(self.basis['configuration_template']['supply_schedule']['passive_work_per_hour'],4)

    def test_host_rechecks_fixed_inputs_even_if_staged_function_returns_wrong_output(self):
        from fastapi.testclient import TestClient
        from backend import main
        bad=copy.deepcopy(self.parameters);bad['area']['radius_km']=30
        with patch.object(self.builder,'build_historical_staged',return_value=(bad,{'source':'dsh_native_skill'})),patch.object(self.builder,'stage_historical') as stage:
            r=TestClient(main.app).post('/api/historical-scenarios/build',json={'battle':BATTLE,'phase_id':'taierzhuang',
                'execution_backend':'narrative','fixed_parameters':self.fixed})
        self.assertEqual(r.status_code,502,r.text)
        self.assertIn('固定',r.text)
        stage.assert_not_called()

    def test_api_passes_user_constraints_to_native_work_and_persists_evidence(self):
        from fastapi.testclient import TestClient
        from backend import main
        def model(basis,instruction,execution_backend,observer):
            self.assertEqual(basis['fixed_parameters']['values'],self.fixed)
            self.assertEqual(basis['configuration_template']['actors']['ww2.cn.division31']['personnel'],6000)
            return copy.deepcopy(self.parameters),{'source':'dsh_native_skill','fixed_parameters':basis['fixed_parameters']}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(Path(td)/'sessions')}),patch.object(self.builder,'build_historical_staged',side_effect=model):
            r=TestClient(main.app).post('/api/historical-scenarios/build',json={'battle':BATTLE,'phase_id':'taierzhuang',
                'execution_backend':'narrative','fixed_parameters':self.fixed})
            self.assertEqual(r.status_code,200,r.text[:500])
            saved=self.builder.load(r.json()['id'])
            self.assertEqual(saved['construction']['fixed_parameters']['values'],self.fixed)
            self.assertEqual(saved['parameters']['actors']['ww2.cn.division31']['personnel'],6000)

    def test_host_also_rejects_a_staged_function_switching_objectives_to_deadline(self):
        from fastapi.testclient import TestClient
        from backend import main
        bad=copy.deepcopy(self.parameters);bad['goal']['termination_mode']='deadline'
        with patch.object(self.builder,'build_historical_staged',return_value=(bad,{'source':'dsh_native_skill'})),patch.object(self.builder,'stage_historical') as stage:
            r=TestClient(main.app).post('/api/historical-scenarios/build',json={'battle':BATTLE,'phase_id':'taierzhuang',
                'execution_backend':'narrative','fixed_parameters':self.fixed})
        self.assertEqual(r.status_code,502,r.text)
        self.assertIn('结束方式',r.text)
        stage.assert_not_called()

    def test_revalidation_inherits_constraints_and_explicit_unlock_removes_current_claim(self):
        from fastapi.testclient import TestClient
        from backend import main
        construction={'source':'dsh_native_skill','fixed_parameters':{'version':self.constraints.VERSION,'values':self.fixed}}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(Path(td)/'sessions')}):
            parent=self.builder.stage_historical(self.basis['initial'],self.parameters,construction=construction,execution_backend='narrative')
            bad=copy.deepcopy(parent['parameters']);bad['actors']['ww2.cn.division31']['personnel']=5000
            request={'parent_draft_id':parent['id'],'parameters':bad,'execution_backend':'narrative'}
            r=TestClient(main.app).post('/api/historical-scenarios/validate',json=request)
            self.assertEqual(r.status_code,422,r.text)
            r=TestClient(main.app).post('/api/historical-scenarios/validate',json={**request,'fixed_parameters':[]})
            self.assertEqual(r.status_code,200,r.text[:500])
            body=r.json()
            self.assertEqual(body['construction']['fixed_parameters']['values'],[])
            self.assertTrue(body['construction']['manual_revision'])
            self.assertEqual(body['parent_id'],parent['id'])


if __name__ == '__main__':
    unittest.main()
