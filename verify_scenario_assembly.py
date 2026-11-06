"""Scoped configuration drafts use native tools without serializing whole worlds."""
import copy
import json
import unittest
from unittest.mock import patch

from tools.qa.historical_operational_fixture import BATTLE, inputs


class CampaignLifecycleAssemblyTests(unittest.TestCase):
    def setUp(self):
        from backend import scenario_builder, scenario_assembly
        self.module=scenario_assembly
        self.basis=scenario_builder.historical_basis(
            '抗日战争-万家岭战役-1938.09下旬至1938.10',version='1.4.0',
            force_scope='campaign',campaign_window_id='WJL-oct6-10',
            campaign_window_version='1.4.0',time_step='1小时',termination_mode='objectives')
        self.assembly=scenario_assembly.create(self.basis)
        self.addCleanup(scenario_assembly.close,self.assembly.id)
        self.lifecycle=dict(version='campaign-lifecycle-1',finish_policy='goal_outcomes',
            assumption='软件验收的连续阶段估计；不将史实结果自动写入战局。',phases=[
                dict(id='deploy',label='观察展开',goal_ids=[],minimum_duration_seconds=3600,
                     operation_ids=['WJL-Oct6-orders'],assumption='一小时展开为计算估计。'),
                dict(id='block',label='外线阻援',goal_ids=['red_block'],minimum_duration_seconds=0,
                     operation_ids=['WJL-Oct6-relief-blocking'],assumption='程序目标判定。'),
                dict(id='attack',label='内线攻击',goal_ids=['red_inner'],minimum_duration_seconds=0,
                     operation_ids=['WJL-Oct7-shibao'],assumption='程序目标判定。'),
                dict(id='consolidate',label='保存主力',goal_ids=['red_preserve'],minimum_duration_seconds=0,
                     operation_ids=['WJL-Oct10-residual'],assumption='程序目标判定；蓝方仍可获胜。')])

    def update(self,value):
        return self.assembly.tool('globals','update_scenario_configuration',
            {'revision':self.assembly.revision,'patch':{'campaign_lifecycle':value}})

    def test_public_22_actor_draft_accepts_and_restores_optional_continuous_stages(self):
        original=copy.deepcopy(self.basis)
        result=self.update(self.lifecycle)
        self.assertTrue(result['updated'],result)
        state=json.loads(json.dumps(self.assembly.export_state()))
        self.module.close(self.assembly.id)
        restored=self.module.restore(state)
        self.addCleanup(self.module.close,restored.id)
        self.assertEqual(restored.configuration,self.assembly.configuration)
        self.assertEqual(restored.configuration['campaign_lifecycle'],self.lifecycle)
        self.assertEqual(len(restored.ids),22)
        for part in restored.parts:
            ids=restored.assigned(part)
            receipt=restored.tool(part,'update_scenario_configuration',
                {'revision':restored.revision,'patch':{'actors':{
                    identity:{'assumption':restored.configuration['actors'][identity]['assumption']}
                    for identity in ids}}})
            self.assertTrue(receipt['updated'],receipt)
        final=restored.tool('final','validate_scenario_configuration',{})
        self.assertTrue(final['valid'],final)
        self.assertEqual(restored.finish(final)['campaign_lifecycle'],self.lifecycle)
        self.assertEqual(self.basis,original)

    def test_invalid_stage_reference_goal_or_dependency_never_changes_draft(self):
        for mutate,message in [
            (lambda v:v['phases'][0]['operation_ids'].append('invented-source'),'来源'),
            (lambda v:v['phases'][1]['goal_ids'].append('invented-goal'),'目标'),
            (lambda v:v['phases'][1].update(goal_ids=['red_preserve']),'后阶段'),
            (lambda v:v['phases'][0].update(minimum_duration_seconds=0),'非零')]:
            with self.subTest(reason=message):
                value=copy.deepcopy(self.lifecycle);mutate(value)
                before=self.assembly.export_state()
                result=self.update(value)
                self.assertFalse(result['updated'],result)
                self.assertEqual(self.assembly.export_state(),before)

    def test_domain_partial_validation_rejects_invalid_lifecycle_before_actor_lock(self):
        from gentactix import historical_operations
        value=copy.deepcopy(self.basis['configuration_template'])
        value['campaign_lifecycle']=copy.deepcopy(self.lifecycle)
        value['campaign_lifecycle']['phases'][1]['goal_ids']=['invented-goal']
        with self.assertRaises(ValueError):
            historical_operations._validate(self.basis['initial'],value,actor_ids=[])


class ScenarioAssemblyTests(unittest.TestCase):
    def test_campaign_coordinator_sees_identity_index_without_full_actor_payloads(self):
        from backend import scenario_builder, scenario_assembly
        basis=scenario_builder.historical_basis('抗日战争-车桥战役-1944.03.05至1944.03.06',
            'core_march5_6',version='1.1.0')
        assembly=scenario_assembly.create(basis)
        self.addCleanup(scenario_assembly.close,assembly.id)
        view=assembly.tool('globals','get_scenario_basis',{})
        self.assertEqual(len(view['actor_index']),15)
        self.assertTrue(all(set(row)=={'id','name','team','echelon'} for row in view['actor_index']))
        self.assertNotIn('actor_index',assembly.tool('actors:0','get_scenario_basis',{}))
        self.assertIn('阻援',view['goal_semantics']['assault'])

    def setUp(self):
        from backend import scenario_builder, scenario_assembly
        self.module=scenario_assembly
        self.basis=scenario_builder.historical_basis(BATTLE,'taierzhuang')
        self.assembly=scenario_assembly.create(self.basis)
        self.addCleanup(scenario_assembly.close,self.assembly.id)
        self.params=inputs()[1]
        self.params['supply_distribution']=copy.deepcopy(self.basis['configuration_template']['supply_distribution'])
        self.params['goal']['team']=self.basis['configuration_template']['goal']['team']
        for actor in self.params['actors'].values():actor['formation'].setdefault('motorized',True)

    def call(self,part,tool,args=None):
        # Runtime bridge copies context for EVERY call. State must live outside it.
        from backend import scenario_builder
        return scenario_builder.execute_tool(copy.deepcopy(self.assembly.context(part)),{'tool':tool,'args':args or {}})

    def globals(self):
        config={k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')}
        return self.call('globals','update_scenario_configuration',{'revision':0,'patch':config})

    def actors(self):
        return self.call('actors:0','update_scenario_configuration',{
            'revision':self.assembly.revision,'patch':{'actors':self.params['actors']}})

    def test_malformed_encoded_patch_returns_actionable_error_without_mutation(self):
        before=copy.deepcopy(self.assembly.configuration)
        result=self.call('globals','update_scenario_configuration',{'revision':0,'patch':'{"clock": {"start": "1938"} "goal": {}}'})
        self.assertFalse(result['updated'])
        self.assertEqual(result['input_error']['code'],'encoded_patch_invalid_json')
        self.assertGreater(result['input_error']['column'],0)
        self.assertIn('JSON对象',result['instruction'])
        self.assertEqual(self.assembly.configuration,before)
        self.assertEqual(self.assembly.revision,0)

    def test_failed_globals_feedback_includes_supported_optional_models(self):
        result=self.call('globals','update_scenario_configuration',{'revision':0,'patch':{}})
        self.assertTrue({'support_dynamics','partitions','supply_distribution'} <= set(result['expected_patch_top_level']))
        view=self.call('globals','get_scenario_basis')
        self.assertEqual(view['optional_patch_fields'],['partitions','support_dynamics','supply_distribution','terrain_model','supply_schedule','operation_boundary','campaign_lifecycle','movement_feedback','fire_accounting','fire_dynamics'])

    def test_explicit_movement_requirement_uses_native_tool_contract_and_never_falls_back(self):
        from backend import scenario_builder
        from gentactix import movement_feedback as mf
        req=scenario_builder.HistoricalBuildRequest(battle=BATTLE,phase_id='taierzhuang',
            execution_backend='afsim',required_models=[mf.VERSION])
        basis=copy.deepcopy(self.basis)
        self.module.prepare_required_models(basis,req.required_models)
        self.assertEqual(basis['configuration_template']['movement_feedback']['version'],mf.VERSION)
        with self.assertRaisesRegex(ValueError,mf.VERSION):
            self.module.validate_required_models(self.params,req.required_models)
        cfg=dict(version=mf.VERSION,assumption='显式QA约束，未作历史标定')
        self.module.validate_required_models({**self.params,'movement_feedback':cfg},req.required_models)
        self.assertTrue(self.globals()['updated'])
        result=self.call('globals','update_scenario_configuration',{'revision':self.assembly.revision,'patch':{'movement_feedback':cfg}})
        self.assertTrue(result['updated'],result)
        self.assertEqual(self.assembly.configuration['movement_feedback'],cfg)

    def test_explicit_time_sustainment_requirement_cannot_silently_fall_back(self):
        from backend import scenario_builder
        from gentactix import support_dynamics
        req=scenario_builder.HistoricalBuildRequest(battle=BATTLE,phase_id='taierzhuang',
            execution_backend='afsim',required_models=['time-sustainment-1'])
        basis=copy.deepcopy(self.basis)
        self.module.prepare_required_models(basis,req.required_models)
        template=basis['configuration_template']['support_dynamics']
        self.assertEqual(template['version'],support_dynamics.VERSION)
        self.assertTrue(all(template[k] is None for k in support_dynamics.LIMITS))
        with self.assertRaisesRegex(ValueError,'time-sustainment-1'):
            self.module.validate_required_models(self.params,req.required_models)
        cfg={'version':support_dynamics.VERSION,'assumption':'显式QA估计',
             **{k:bounds[0] for k,bounds in support_dynamics.LIMITS.items()}}
        self.module.validate_required_models({**self.params,'support_dynamics':cfg},req.required_models)
        cfg['food_work_per_hour']=-1
        with self.assertRaises(ValueError):
            self.module.validate_required_models({**self.params,'support_dynamics':cfg},req.required_models)

    def test_tool_view_is_scoped_and_complete_world_stays_on_host(self):
        view=self.call('globals','get_scenario_basis')
        self.assertEqual(view['workflow'],'staged_historical_configuration')
        self.assertNotIn('actors',view['configuration'])
        self.assertNotIn('phase_id',view['configuration'])
        self.assertNotIn('format',view['configuration'])
        self.assertEqual(view['readonly_identity']['phase_id'],'taierzhuang')
        self.assertNotIn('initial',view)
        self.assertNotIn('definition',view)
        self.assertLess(len(json.dumps(view)),24000)

    def test_updates_survive_copied_context_and_never_change_the_source_snapshot(self):
        original=copy.deepcopy(self.basis)
        self.assertTrue(self.globals()['updated'])
        self.assertEqual(self.call('actors:0','get_scenario_basis')['revision'],1)
        self.assertTrue(self.actors()['updated'])
        self.assertEqual(self.basis,original)
        self.assertEqual(self.assembly.configuration['actors'],self.params['actors'])
        self.assertEqual(self.assembly.revision,2)

    def test_stale_revision_invalid_parameter_or_unknown_field_never_writes(self):
        self.globals();original=copy.deepcopy(self.assembly.configuration)
        for args in ({'revision':0,'patch':{'assumptions':'stale'}},
                     {'revision':1,'patch':{'unknown':'hidden'}},
                     {'revision':1,'patch':{'actors':self.params['actors']}}):
            result=self.call('globals','update_scenario_configuration',args)
            self.assertFalse(result['updated'])
            self.assertEqual(self.assembly.configuration,original)
        bad=copy.deepcopy(self.params['actors']);next(iter(bad.values()))['personnel']=True
        result=self.call('actors:0','update_scenario_configuration',{'revision':1,'patch':{'actors':bad}})
        self.assertFalse(result['updated'])
        self.assertEqual(self.assembly.configuration,original)

    def test_final_validation_rejects_missing_units_and_uses_existing_native_compiler(self):
        self.globals()
        self.assertFalse(self.call('final','validate_scenario_configuration')['valid'])
        self.actors()
        from backend import afsim_world
        with patch.object(afsim_world,'compile_scene',wraps=afsim_world.compile_scene) as compile_scene:
            result=self.call('final','validate_scenario_configuration')
        self.assertTrue(result['valid'])
        self.assertEqual(result['scope'],'complete_configuration_and_native_template; not_live_load')
        self.assertTrue(compile_scene.called)
        self.assertEqual(self.assembly.finish(result)['actors'],self.params['actors'])
        self.assertNotIn('configuration',result)
        self.assertNotIn('script',result)

    def test_any_update_invalidates_the_previous_validation_receipt(self):
        self.globals();self.actors()
        receipt=self.call('final','validate_scenario_configuration')
        self.assertTrue(receipt['valid'])
        self.actors()
        with self.assertRaisesRegex(ValueError,'校验|版本'):
            self.assembly.finish(receipt)

    def test_child_cannot_read_or_modify_another_page_or_global_configuration(self):
        # This is a view-isolation fixture, not historical OOB acceptance.
        extended=copy.deepcopy(self.basis)
        actors=extended['configuration_template']['actors']
        for i in range(40):
            identity=f'qa.extra{i}'
            actors[identity]=copy.deepcopy(next(iter(actors.values())))
            extended['actors'].append({**copy.deepcopy(extended['actors'][0]),'id':identity,'name':f'QA actor{i}'})
        assembly=self.module.create(extended);self.addCleanup(self.module.close,assembly.id)
        from backend import scenario_builder
        context=assembly.context('actors:0')
        view=scenario_builder.execute_tool(context,{'tool':'get_scenario_basis'})
        self.assertLessEqual(len(view['actors']),self.module.PAGE_SIZE)
        self.assertEqual(set(view['configuration']['actors']),set(view['assigned_actor_ids']))
        self.assertNotIn('qa.extra39',json.dumps(view))
        original=copy.deepcopy(assembly.configuration)
        result=scenario_builder.execute_tool(context,{'tool':'update_scenario_configuration','args':{
            'revision':0,'patch':{'actors':{'qa.extra39':self.params['actors']['ww2.cn.division31']}}}})
        self.assertFalse(result['updated']);self.assertEqual(assembly.configuration,original)
        with self.assertRaises(ValueError):assembly.context('actors:999')

    def test_small_tool_receipt_and_expired_operation_cannot_be_used_as_a_full_config(self):
        self.globals();self.actors();receipt=self.call('final','validate_scenario_configuration')
        bad={**receipt,'configuration_hash':'invented'}
        with self.assertRaises(ValueError):self.assembly.finish(bad)
        self.module.close(self.assembly.id)
        with self.assertRaises(ValueError):self.call('final','get_scenario_basis')

    def test_global_configuration_is_locked_after_unit_work_starts(self):
        self.globals();self.actors()
        result=self.call('globals','update_scenario_configuration',{'revision':2,'patch':{'assumptions':'late global change'}})
        self.assertFalse(result['updated'])

    def test_explicit_ferry_requirement_cannot_be_lost_before_globals_lock(self):
        from backend import scenario_builder
        from verify_ferries import ferry_inputs
        snapshot, parameters = ferry_inputs()
        basis = scenario_builder.historical_basis(snapshot['definition']['battle'], 'follow_on_jan3')
        basis['required_models'] = ['formation-ferry-1']
        assembly = self.module.create(basis)
        self.addCleanup(self.module.close, assembly.id)
        patch_value = {k: v for k, v in parameters.items() if k not in ('actors', 'format', 'phase_id')}
        good = copy.deepcopy(patch_value)
        del patch_value['facility']['crossing_model']['ferry']
        frozen = copy.deepcopy(assembly.configuration)
        result = assembly.tool('globals', 'update_scenario_configuration', {'revision': 0, 'patch': patch_value})
        self.assertFalse(result['updated'])
        self.assertIn('formation-ferry-1', result['error'])
        self.assertFalse(assembly.global_ready)
        self.assertEqual(assembly.configuration, frozen)
        self.assertEqual(assembly.tool('globals', 'get_scenario_basis', {})['required_models'], ['formation-ferry-1'])
        result = assembly.tool('globals', 'update_scenario_configuration', {'revision': 0, 'patch': good})
        self.assertTrue(result['updated'], result)
        self.assertTrue(assembly.global_ready)

    def test_requirement_uses_explicit_request_not_free_text_keyword_inference(self):
        from backend import scenario_builder
        from pydantic import ValidationError
        request = {'battle': BATTLE, 'phase_id': 'taierzhuang',
                   'instruction': '不要加入formation-ferry-1，也不需要舟艇'}
        self.assertEqual(scenario_builder.HistoricalBuildRequest(**request).required_models, [])
        self.assertEqual(scenario_builder.HistoricalBuildRequest(**request, required_models=['formation-ferry-1']).required_models,
                         ['formation-ferry-1'])
        with self.assertRaises(ValidationError):
            scenario_builder.HistoricalBuildRequest(**request, required_models=['invented-ship'])

    def test_revalidation_cannot_claim_selected_ferry_when_input_omits_it(self):
        from fastapi.testclient import TestClient
        from backend import main, scenario_builder as builder
        parent = {'kind': 'historical_operation', 'construction': {'source': 'dsh_native_skill'}}
        with patch.object(builder, 'load', return_value=parent), \
             patch.object(builder, 'stage_historical', side_effect=AssertionError('Missing requirement must fail before load')):
            for engine in ('afsim', 'narrative'):
                response = TestClient(main.app).post('/api/historical-scenarios/validate', json={
                    'parameters': self.params, 'parent_draft_id': 'a' * 32,
                    'execution_backend': engine, 'required_models': ['formation-ferry-1']})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('formation-ferry-1', response.json()['detail'])

    def test_single_encoded_json_patch_still_passes_exact_scope_and_domain_validation(self):
        self.globals()
        result=self.call('actors:0','update_scenario_configuration',{'revision':1,'patch':json.dumps({'actors':self.params['actors']})})
        self.assertTrue(result['updated'],result)
        self.assertEqual(result['normalized_patch'],'json_object_string')
        self.assertEqual(self.assembly.configuration['actors'],self.params['actors'])
        before=copy.deepcopy(self.assembly.configuration)
        for p in ('[]','null','{"actors": {"invented": {}}}','{"actors":NaN}'):
            result=self.call('actors:0','update_scenario_configuration',{'revision':2,'patch':p})
            self.assertFalse(result['updated'])
            self.assertEqual(self.assembly.configuration,before)

    def test_bad_patch_explains_exact_fields_and_missing_ids_without_accepting_wrappers(self):
        self.globals()
        result=self.call('actors:0','update_scenario_configuration',{'revision':1,'patch':{'configuration':{'actors':self.params['actors']}}})
        self.assertFalse(result['updated'])
        self.assertEqual(result['expected_patch_top_level'],['actors'])
        self.assertEqual(set(result['required_actor_ids']),set(self.params['actors']))
        self.assertEqual(set(result['missing_actor_ids']),set(self.params['actors']))
        self.assertIn('不要',result['instruction'])

    def test_native_step_budget_error_does_not_misdiagnose_model_connection(self):
        from backend import harness_engine as h
        from types import SimpleNamespace
        result=SimpleNamespace(finish_reason='error',final_response='',events=[{'type':'turn/end','data':{
            'reason':{'kind':'error','error':{'message':'GenTactix 模型步骤预算已用尽','code':'UNKNOWN'}}}}])
        with self.assertRaises(h.HarnessRunError) as raised:h._gate(result)
        self.assertIn('领域步骤',str(raised.exception))
        self.assertNotIn('测试当前连接',str(raised.exception))

    def test_native_patch_schema_guides_actual_actor_fields_instead_of_an_untyped_object(self):
        import subprocess
        result=subprocess.run(['node','--input-type=module','-e',
            "import {configurationPatchSchema as s} from './plugins/dsh-afsim/scenario-schema.mjs'; process.stdout.write(JSON.stringify(s));"],capture_output=True,text=True,check=True)
        schema=json.loads(result.stdout)
        self.assertFalse(schema['additionalProperties'])
        actor=schema['properties']['actors']['additionalProperties']
        self.assertEqual(actor['properties']['personnel']['type'],'integer')
        self.assertIn('formation',actor['required'])
        self.assertNotIn('phase_id',schema['properties'])
        self.assertNotIn('configuration',schema['properties'])
        self.assertIn('campaign_scope',schema['properties'])
        self.assertIn('campaign',schema['properties'])
        boundary=schema['properties']['operation_boundary']
        self.assertFalse(boundary['additionalProperties'])
        self.assertEqual(boundary['properties']['routes']['maxItems'],64)
        self.assertIn('formation-partitions-2',schema['properties']['partitions']['properties']['version']['enum'])
        from gentactix import support_dynamics
        variants=schema['properties']['support_dynamics']['anyOf']
        by_version={v['properties']['version']['enum'][0]:v for v in variants}
        self.assertEqual(set(by_version),support_dynamics.VERSIONS)
        for version,variant in by_version.items():
            self.assertEqual(set(variant['required']),set(support_dynamics.limits(version))|{'version','assumption'})
            self.assertFalse(variant['additionalProperties'])
        lifecycle=schema['properties']['campaign_lifecycle']
        self.assertEqual(lifecycle['properties']['version']['enum'],['campaign-lifecycle-1'])
        phases=lifecycle['properties']['phases']
        self.assertEqual((phases['minItems'],phases['maxItems']),(2,256))
        self.assertEqual(set(phases['items']['required']),{
            'id','label','goal_ids','minimum_duration_seconds','operation_ids','assumption'})
        self.assertEqual(lifecycle['properties']['finish_policy']['enum'],['all_phases','goal_outcomes'])

    def test_cancelled_build_returns_cancellation_not_a_connection_error(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as b
        from tools.qa.pingxingguan_fixture import BATTLE as qiaogou_battle
        def cancelled(basis,instruction,engine,observer):
            observer.cancel_requested=True
            raise RuntimeError('harness ended after cancellation')
        with patch.object(b,'build_historical_staged',side_effect=cancelled):
            response=TestClient(main.app).post('/api/historical-scenarios/build',json={
                'battle':qiaogou_battle,'phase_id':'qiaogou','execution_backend':'afsim'})
        self.assertEqual(response.status_code,409,response.text)
        self.assertIn('取消',response.json()['detail'])
        self.assertNotIn('连接',response.json()['detail'])

    def test_workflow_uses_native_child_sessions_and_returns_only_host_validated_parameters(self):
        from backend import scenario_builder as b
        from tools.qa.pingxingguan_fixture import inputs as qiaogou
        from types import SimpleNamespace
        snapshot,params=qiaogou();basis=b.historical_basis(snapshot['definition']['battle'],'qiaogou')
        params['goal']['team']=basis['configuration_template']['goal']['team']
        observer=b.h.RunObserver('staged-test');calls=[]
        def native(binding,prompt,obs,**kwargs):
            context=kwargs['context'];part=context['scenario_composer']['part']
            self.assertEqual(kwargs['role'],'scenario-builder')
            self.assertNotIn('"actors":',prompt)
            self.assertLess(len(json.dumps(context)),600)
            skill=b.execute_tool(context,{'tool':'read_scenario_skill'})
            self.assertTrue(skill['ok'])
            view=b.execute_tool(context,{'tool':'get_scenario_basis'})
            if part=='final':
                receipt=b.execute_tool(context,{'tool':'validate_scenario_configuration'})
                names=['get_scenario_basis','validate_scenario_configuration']
            else:
                patch_={k:v for k,v in params.items() if k not in ('actors','format','phase_id')} if part=='globals' else {'actors':{i:params['actors'][i] for i in view['assigned_actor_ids']}}
                receipt=b.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':view['revision'],'patch':patch_}})
                self.assertTrue(receipt['updated'],receipt)
                names=['read_scenario_skill','get_scenario_basis','update_scenario_configuration']
            sid=binding['session_id'] if binding else 'gentactix-unit-'+kwargs['namespace']+'-'+str(len(calls))
            obs.runs.append({'session_id':sid,'events':[{'type':'tool/call','name':n} for n in names]})
            calls.append((part,kwargs.get('parent_session_id'),sid))
            answer={k:receipt[k] for k in ('revision','configuration_hash')};answer['explanation']='Explicit QA assumptions, not surveyed history'
            return SimpleNamespace(final_response=json.dumps(answer)),{'session_id':sid,'factory':'DSH.AgentRegistry'}
        with patch.object(b.h,'unit_run',side_effect=native),patch.object(b.h,'dispose_unit_sessions') as dispose:
            config,construction=b.build_historical_staged(basis,'QA','narrative',observer)
        self.assertEqual(config,params)
        self.assertEqual([r[0] for r in calls],['globals','actors:0','actors:1','final'])
        self.assertTrue(all(r[1]==calls[0][2] for r in calls[1:3]))
        self.assertEqual(calls[-1][2],calls[0][2])
        self.assertEqual(construction['workflow'],'native_agent_registry_scoped_drafts')
        self.assertEqual(len(dispose.call_args.args[0]),3)

    def test_cancelled_staged_workflow_cleans_up_without_model_or_native_load(self):
        from backend import scenario_builder as b
        observer=b.h.RunObserver('cancelled');observer.cancel_requested=True
        with patch.object(b.h,'unit_run',side_effect=AssertionError('No model after cancel')),patch.object(b.afsim_world,'run_scene',side_effect=AssertionError('No native load')):
            with self.assertRaisesRegex(RuntimeError,'取消'):
                b.build_historical_staged(self.basis,'QA','afsim',observer)

    def test_staged_workflow_does_not_accept_claims_without_native_tool_calls(self):
        from backend import scenario_builder as b
        from types import SimpleNamespace
        observer=b.h.RunObserver('missing evidence')
        with patch.object(b.h,'unit_run',return_value=(SimpleNamespace(final_response='{}'),{'session_id':'gentactix-unit-fake'})),patch.object(b.h,'dispose_unit_sessions'):
            with self.assertRaisesRegex(ValueError,'调用证据'):
                b.build_historical_staged(self.basis,'QA','narrative',observer)

    def test_native_child_route_reuses_role_policy_and_disposes_failed_fresh_handles(self):
        from backend import harness_engine as h
        observer=h.RunObserver('native child');created=[]
        policy={'allowed_tools':['update_scenario_configuration'],'reasoning_effort':'high','max_tokens':65536,'max_steps':8,'max_tool_calls':16}
        def control(path,body):
            if body.get('operation')=='inspect':raise RuntimeError('not yet created')
            created.append(body)
            return {'factory':'DSH.AgentRegistry','parent_session_id':'parent'}
        with patch.object(h,'get_harness'),patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'RUNTIME_STATUS',{'connected':True}), \
             patch.object(h,'role_policy',return_value=policy) as role,patch.object(h.runtime_bridge,'control',side_effect=control), \
             patch.object(h,'_native_control_run',side_effect=RuntimeError('native failure')),patch.object(h,'dispose_unit_sessions') as dispose:
            with self.assertRaisesRegex(RuntimeError,'native failure'):
                h.unit_run(None,'bounded task',observer,namespace='scenario-test',role='scenario-builder',parent_session_id='parent',dispose_on_failure=True)
        self.assertEqual(role.call_args.args[0],'scenario-builder')
        self.assertEqual(created[0]['parent_session_id'],'parent')
        self.assertEqual(created[0]['policy'],policy)
        self.assertEqual(next(iter(dispose.call_args.args[0].values()))['session_id'],created[0]['session_id'])

    def test_operation_progress_is_read_only_and_distinguishes_draft_work_from_load(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as b
        observer=b.h.RunObserver('configuration');observer.progress.update(phase='scenario_configuration',completed_actors=4,total_actors=6)
        identity='a'*32
        with b._active_lock:b._active[identity]=observer
        try:
            client=TestClient(main.app)
            result=client.get(f'/api/scenarios/operations/{identity}/progress')
            self.assertEqual(result.status_code,200)
            self.assertTrue(result.json()['active'])
            self.assertEqual(result.json()['progress']['completed_actors'],4)
            self.assertFalse(observer.cancel_requested)
            self.assertFalse(client.get('/api/scenarios/operations/'+'f'*32+'/progress').json()['active'])
        finally:
            with b._active_lock:b._active.pop(identity,None)

    def test_readonly_recovery_cannot_modify_already_validated_draft(self):
        from backend import scenario_builder as b
        self.globals();self.actors();original=copy.deepcopy(self.assembly.configuration)
        context=self.assembly.context('actors:0',read_only=True)
        with self.assertRaisesRegex(ValueError,'只读'):
            b.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':2,'patch':{'actors':self.params['actors']}}})
        view=b.execute_tool(context,{'tool':'get_scenario_basis'})
        self.assertFalse(view['write_allowed'])
        self.assertEqual(self.assembly.configuration,original)

    def test_valid_saved_part_can_recover_final_receipt_in_fresh_native_readonly_session(self):
        from backend import scenario_builder as b
        from types import SimpleNamespace
        observer=b.h.RunObserver('recovery');attempts=[]
        def native(binding,prompt,obs,**kwargs):
            context=kwargs['context'];part=context['scenario_composer']['part'];readonly=context['scenario_composer'].get('read_only')
            view=b.execute_tool(context,{'tool':'get_scenario_basis'});sid='gentactix-unit-'+kwargs['namespace']+'-'+str(len(attempts))
            if readonly:
                receipt=view;names=['get_scenario_basis'];self.assertFalse(view['write_allowed'])
            elif part=='final':
                receipt=b.execute_tool(context,{'tool':'validate_scenario_configuration'});names=['get_scenario_basis','validate_scenario_configuration']
            else:
                patch_={k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')} if part=='globals' else {'actors':self.params['actors']}
                receipt=b.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':view['revision'],'patch':patch_}})
                self.assertTrue(receipt['updated'],receipt);names=['read_scenario_skill','get_scenario_basis','update_scenario_configuration']
            obs.runs.append({'id':sid,'session_id':sid,'finish_reason':'completed','events':[{'type':'tool/call','name':n} for n in names]})
            attempts.append((part,bool(readonly)))
            if part=='actors:0' and not readonly:
                obs.runs[-1]['finish_reason']='error'
                raise b.h.HarnessRunError('native step budget after validated draft save')
            return SimpleNamespace(final_response=json.dumps({k:receipt[k] for k in ('revision','configuration_hash')})),{'session_id':sid,'factory':'DSH.AgentRegistry'}
        with patch.object(b.h,'unit_run',side_effect=native),patch.object(b.h,'dispose_unit_sessions'):
            config,construction=b.build_historical_staged(self.basis,'QA','narrative',observer)
        self.assertEqual(config,self.params)
        self.assertEqual(attempts,[('globals',False),('actors:0',False),('actors:0',True),('final',False)])
        self.assertEqual(construction['recovery_count'],1)
        self.assertFalse(next(r for r in construction['runs'] if r['finish_reason']=='error')['accepted'])

    def test_final_recovery_requires_real_full_validation_and_cannot_regenerate_inputs(self):
        from backend import scenario_builder as b
        from types import SimpleNamespace
        for actual_validation in (True,False):
            observer=b.h.RunObserver('final-read-recovery');attempts=[]
            def native(binding,prompt,obs,**kwargs):
                context=kwargs['context'];part=context['scenario_composer']['part'];readonly=context['scenario_composer'].get('read_only')
                sid='gentactix-unit-'+kwargs['namespace']+'-'+str(len(attempts))
                if readonly:
                    receipt=b.execute_tool(context,{'tool':'get_scenario_basis'});names=['get_scenario_basis']
                    self.assertFalse(receipt['write_allowed'])
                elif part=='final':
                    receipt=b.execute_tool(context,{'tool':'validate_scenario_configuration'}) if actual_validation else {'revision':2,'configuration_hash':'unverified'}
                    names=['validate_scenario_configuration']
                else:
                    view=b.execute_tool(context,{'tool':'get_scenario_basis'})
                    patch_={k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')} if part=='globals' else {'actors':self.params['actors']}
                    receipt=b.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':view['revision'],'patch':patch_}})
                    self.assertTrue(receipt['updated'],receipt)
                    names=['read_scenario_skill','get_scenario_basis','update_scenario_configuration']
                obs.runs.append({'id':sid,'session_id':sid,'finish_reason':'completed','events':[{'type':'tool/call','name':n} for n in names]})
                attempts.append((part,bool(readonly)))
                return SimpleNamespace(final_response=json.dumps({k:receipt[k] for k in ('revision','configuration_hash')})),{'session_id':sid,'factory':'DSH.AgentRegistry'}
            with self.subTest(validated=actual_validation),patch.object(b.h,'unit_run',side_effect=native),patch.object(b.h,'dispose_unit_sessions'):
                if actual_validation:
                    config,construction=b.build_historical_staged(self.basis,'QA','narrative',observer)
                    self.assertEqual(config,self.params);self.assertEqual(construction['recovery_count'],1)
                    self.assertEqual(attempts[-2:],[('final',False),('final',True)])
                    self.assertTrue(any(r.get('accepted') is False for r in construction['runs']))
                else:
                    with self.assertRaisesRegex(ValueError,'调用证据'):b.build_historical_staged(self.basis,'QA','narrative',observer)
                    self.assertFalse(any(readonly for _,readonly in attempts))

    def test_completed_stale_receipt_recovers_readonly_without_repeating_valid_writes(self):
        from backend import scenario_builder as b
        from types import SimpleNamespace
        for failed_part,bad_recovery in [('actors:0',False),('final',False),('final',True)]:
            with self.subTest(part=failed_part,bad_recovery=bad_recovery):
                observer=b.h.RunObserver('stale-receipt');attempts=[]
                def native(binding,prompt,obs,**kwargs):
                    context=kwargs['context'];part=context['scenario_composer']['part'];readonly=context['scenario_composer'].get('read_only',False)
                    sid='gentactix-unit-'+kwargs['namespace']+'-'+str(len(attempts))
                    view=b.execute_tool(context,{'tool':'get_scenario_basis'})
                    if readonly:
                        receipt=view;names=['get_scenario_basis'];self.assertFalse(view['write_allowed'])
                    elif part=='final':
                        receipt=b.execute_tool(context,{'tool':'validate_scenario_configuration'});names=['get_scenario_basis','validate_scenario_configuration']
                        self.assertTrue(receipt['valid'])
                    else:
                        patch_={k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')} if part=='globals' else {'actors':self.params['actors']}
                        receipt=b.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':view['revision'],'patch':patch_}})
                        self.assertTrue(receipt['updated'],receipt);names=['read_scenario_skill','get_scenario_basis','update_scenario_configuration']
                    obs.runs.append({'id':sid,'session_id':sid,'finish_reason':'completed','events':[{'type':'tool/call','name':n} for n in names]})
                    attempts.append((part,readonly))
                    answer={k:receipt[k] for k in ('revision','configuration_hash')}
                    if part==failed_part and (not readonly or bad_recovery):answer['configuration_hash']='copied-with-a-typo'
                    return SimpleNamespace(final_response=json.dumps(answer)),{'session_id':sid,'factory':'DSH.AgentRegistry'}
                with patch.object(b.h,'unit_run',side_effect=native),patch.object(b.h,'dispose_unit_sessions'):
                    if bad_recovery:
                        with self.assertRaisesRegex(ValueError,'过期版本或配置哈希'):
                            b.build_historical_staged(self.basis,'QA','narrative',observer)
                    else:
                        config,construction=b.build_historical_staged(self.basis,'QA','narrative',observer)
                        self.assertEqual(config,self.params)
                        self.assertEqual(len(construction['draft_updates']),2)
                        self.assertEqual(construction['recovery_count'],1)
                        self.assertTrue(any(r.get('accepted') is False for r in construction['runs']))
                self.assertEqual(sum(readonly for _,readonly in attempts),1)


if __name__=='__main__':unittest.main()
