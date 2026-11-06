"""Explicit live-density inputs, frozen compatibility, and observation contracts."""
import copy
import unittest
from unittest.mock import patch

from backend import afsim_world,scenario_assembly,scenario_builder
from gentactix import combined_arms,combat_effects,fire_process,historical_operations as ho,missions,synthetic_history
from tools.qa.historical_operational_fixture import inputs,NOTE

CFG={'version':'live-footprint-density-1','assumption':NOTE+' Dynamic shared density sampled before simultaneous fire.'}
ACCOUNT={'version':'classified-indirect-1','assumption':NOTE}


class ConversionDensityTests(unittest.TestCase):
    def test_split_keeps_integer_micro_debt_without_rounding_the_parent(self):
        from gentactix import formation_conversion as fc
        from verify_formation_conversion import damaged
        u=damaged();u['formation']['combat_damage_remainder']=.532133;before=copy.deepcopy(u)
        p=fc.split_current(u,[dict(id=k,label=k,committed=5000)for k in ('left','right')],
            assumption=NOTE,operation_id='a'*32,product_mode='synthetic',damage_quantum=.000001)
        self.assertEqual([x['formation']['combat_damage_remainder']for x in p['after']],[.266067,.266066])
        self.assertEqual(p['totals_before'],p['totals_after']);self.assertEqual(u,before)
        self.assertTrue(fc.verify_proposal(p))
        u['formation']['combat_damage_remainder']=.5321335
        with self.assertRaisesRegex(ValueError,'精度'):fc.split_current(u,p['request']['allocations'],
            assumption=NOTE,operation_id='b'*32,product_mode='synthetic',damage_quantum=.000001)

    def test_merge_canonicalizes_micro_sum_without_changing_legacy_arithmetic(self):
        from gentactix import formation_conversion as fc
        from verify_formation_conversion import ConversionTests
        a,b=ConversionTests().split()['after']
        a['formation']['combat_damage_remainder']=.1;b['formation']['combat_damage_remainder']=.2
        q=fc.merge_current([a,b],assumption=NOTE,operation_id='b'*32,damage_quantum=.000001)
        self.assertEqual(q['after'][0]['formation']['combat_damage_remainder'],.3)
        self.assertTrue(fc.verify_proposal(q))
        old=fc.merge_current([a,b],assumption=NOTE,operation_id='b'*32)
        self.assertEqual(old['after'][0]['formation']['combat_damage_remainder'],.1+.2)
        self.assertNotIn('damage_quantum',old['request'])

    def test_conversion_never_claims_old_native_density_for_new_identities(self):
        from gentactix import formation_conversion as fc
        from verify_formation_conversion import ConversionTests,damaged
        u=damaged();u['formation']['last_density_sample']={'source':'afsim_native','turn':9}
        p=ConversionTests().split(u)
        self.assertIn('last_density_sample',p['before'][0]['formation'])
        self.assertTrue(all('last_density_sample'not in x['formation']for x in p['after']))
        for x in p['after']:x['formation']['last_density_sample']={'source':'afsim_native','turn':9}
        q=fc.merge_current(p['after'],assumption=NOTE,operation_id='b'*32)
        self.assertNotIn('last_density_sample',q['after'][0]['formation'])

    @staticmethod
    def campaign_world(selected=True):
        from tools.qa.campaign_plan_fixture import inputs as campaign_inputs
        s,p=campaign_inputs()
        for actor in p['actors'].values():actor['personnel']=10000;actor['equipment']['transport']=20
        if selected:p['fire_dynamics']=copy.deepcopy(CFG)
        binding=ho.initial(s,p)['mission']['definition']['historical_calculation']
        return missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))

    def test_detached_proposal_precision_must_match_the_frozen_world(self):
        from gentactix import formation_conversion as fc,formation_registry
        from verify_formation_continuity import selected
        for enabled in (True,False):
            w=self.campaign_world(enabled);u=selected(w)
            p=fc.split_current(u,[dict(id=k,label=k,committed=5000)for k in ('left','right')],
                assumption=NOTE,operation_id='c'*32,product_mode='synthetic',historical_snapshot=w['historical_initial'],
                **({}if enabled else {'damage_quantum':.000001}))
            with self.subTest(enabled=enabled),self.assertRaisesRegex(ValueError,'精度|冻结'):
                formation_registry.stage(w,p,team='red')

    def test_normal_commit_split_merge_and_cold_restore_preserve_micro_debt(self):
        import json,os,tempfile
        from backend import formation_commit,session_store
        from gentactix import commands,force_organization,formation_conversion as fc
        from verify_formation_commit import fixture
        s,uid,_=fixture(self.campaign_world());unit=commands.resolve_units(s)[uid][1]
        unit['formation']['combat_damage_remainder']=.532133
        unit['formation']['last_density_sample']={'source':'afsim_native','turn':0}
        before=copy.deepcopy(s)
        args=dict(kind='split',unit_ids=[uid],allocations=[dict(id=k,label=k,committed=5000)for k in ('left','right')],assumption=NOTE)
        def commit(args,identity):
            v=fc.observation(s,args);cs=commands.view(s)
            request={**args,'expected_turn':s['turn_count'],'revision':cs['revision'],'world_version':cs['world_version'],
                'organization_revision':force_organization.state(s)['revision'],'view_version':v['view_version'],'commit_id':identity*32}
            return formation_commit.commit(s,request)
        with tempfile.TemporaryDirectory()as tmp,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':tmp+'/sessions',
                'GENTACTIX_TRACE_DIR':tmp+'/traces','GENTACTIX_ROLE_INDEX':tmp+'/roles.json'}):
            p=fc.preparation(s,args);self.assertEqual(p['proposal']['request']['damage_quantum'],.000001)
            self.assertEqual(s,before)
            result=commit(args,'d');ids=result['command_map'][uid]
            self.assertEqual(sum(round(commands.resolve_units(s)[i][1]['formation']['combat_damage_remainder']*1000000)for i in ids),532133)
            self.assertTrue(missions.validate(s['war_state']))
            commit(dict(kind='merge',unit_ids=ids,assumption=NOTE),'e')
            merged=[u for u in s['war_state']['red_units']if u.get('runtime_allocation')]
            self.assertEqual(len(merged),1);self.assertEqual(merged[0]['formation']['combat_damage_remainder'],.532133)
            self.assertNotIn('last_density_sample',merged[0]['formation'])
            loaded,errors=session_store.load_all();self.assertFalse(errors)
            self.assertEqual(session_store.serializable(s),session_store.serializable(loaded[s['id']]))
            self.assertEqual(s['war_state']['simulation_clock'],before['war_state']['simulation_clock'])


def world(*,selected=True,accounting=False):
    s,p=inputs()
    if selected:p['fire_dynamics']=copy.deepcopy(CFG)
    if accounting:p['fire_accounting']=copy.deepcopy(ACCOUNT)
    return ho.initial(s,p)


class ModelDensityEvidenceTests(unittest.TestCase):
    @staticmethod
    def prior():
        w=world();u=w['red_units'][0]
        u['formation']['last_density_sample']=dict(version=CFG['version'],source='afsim_native',turn=0,
            sample_s=1795,lat_cell=round(u['lat']*1000000),lng_cell=round(u['lng']*1000000),
            own_current=u['personnel']['current'],eligible=1,
            footprint_committed=u['personnel']['committed'],footprint_current=u['personnel']['current'])
        return w

    def test_model_cannot_rewrite_or_resubmit_a_prior_native_sample(self):
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        for change in ({},{'turn':1},{'source':'dsh_model_estimate'},{'footprint_current':0}):
            w=self.prior();value=model_result(w)
            value['unit_updates'][0]['formation']['last_density_sample']={**w['red_units'][0]['formation']['last_density_sample'],**change}
            frozen=copy.deepcopy((w,value))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'原生.*回执'):
                dsh_simulation.apply(w,value,'30分钟')
            self.assertEqual((w,value),frozen)

    def test_model_cannot_invent_a_native_sample_in_a_new_world(self):
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        w=world();value=model_result(w)
        value['unit_updates'][0]['formation']['last_density_sample']=self.prior()['red_units'][0]['formation']['last_density_sample']
        with self.assertRaisesRegex(ValueError,'原生.*回执'):dsh_simulation.apply(w,value,'30分钟')

    def test_model_projection_omits_native_sampling_but_checkpoint_keeps_it(self):
        from backend import dsh_simulation
        w=self.prior();frozen=copy.deepcopy(w)
        projected=dsh_simulation.observation_view(w)
        self.assertNotIn('last_density_sample',projected['red_units'][0]['formation'])
        self.assertEqual(w,frozen)

    def test_ordinary_model_update_preserves_prior_sample_without_claiming_native_execution(self):
        from backend import afsim_state,dsh_simulation
        from verify_dsh_resources import model_result
        w=self.prior();frozen=copy.deepcopy(w)
        after=dsh_simulation.apply(w,model_result(w),'30分钟')
        self.assertEqual(after['red_units'][0]['formation']['last_density_sample'],w['red_units'][0]['formation']['last_density_sample'])
        session=dict(id='model-density-provenance',war_state=after,turn_count=1,time_step='30分钟',execution_backend='narrative',simulation_mode='open')
        self.assertNotIn('last_density_sample',afsim_state.observation(session,{'limit':1})['units'][0]['formation'])
        self.assertEqual(after['dsh_execution']['effects_source'],'dsh_model_estimate');self.assertEqual(w,frozen)


class FireDensityTests(unittest.TestCase):
    def test_new_density_profile_declares_integer_damage_quantum(self):
        ref=combat_effects.reference(world())
        self.assertEqual(ref['damage_quantum'],.000001)

    def test_new_quantum_cannot_silently_round_an_incompatible_carried_fraction(self):
        w=world();w['red_units'][0]['formation']['combat_damage_remainder']=.1234567
        with self.assertRaisesRegex(ValueError,'毁伤余量.*精度'):combined_arms.validate(w)

    def test_frozen_early_dynamic_profile_can_keep_its_original_float_interpretation(self):
        w=world();ref=combat_effects.reference(w);ref.pop('damage_quantum',None)
        ref['definition_hash']=combat_effects.digest({k:v for k,v in ref.items()if k!='definition_hash'})
        w['combat_reference']=ref
        scene=afsim_world.compile_scene(w,[],1800,native_rules=True)
        self.assertNotIn('pending_damage_micro',scene['script'])
        self.assertEqual(combat_effects.reference(w),ref)
    def test_absent_option_keeps_exact_legacy_profile_and_no_dynamic_assumption(self):
        for accounted,version,revision in ((False,'aggregate-fire-cycles-2.3',2),(True,'aggregate-fire-cycles-2.4',3)):
            old=world(selected=False,accounting=accounted);ref=combat_effects.reference(old)
            self.assertEqual((ref['version'],ref['combat_revision']),(version,revision))
            self.assertNotIn('fire_dynamics',ref)
            self.assertNotIn('live-footprint-density-1',str(ref))

    def test_selection_freezes_distinct_version_and_preserves_accounting_choice(self):
        for accounted in (False,True):
            w=world(accounting=accounted);ref=combat_effects.reference(w)
            self.assertEqual((ref['version'],ref['combat_revision']),('aggregate-fire-cycles-2.5',4))
            self.assertEqual(ref['fire_dynamics'],CFG)
            self.assertEqual(combat_effects.work_cost(ref,'bombard'),0 if accounted else 1)
            self.assertEqual(combat_effects.work_cost(ref,'fire'),1)
            self.assertTrue(combat_effects.validate_profile(ref))
            self.assertNotEqual(ref['definition_hash'],combat_effects.reference(world(selected=False,accounting=accounted))['definition_hash'])

    def test_invalid_or_silent_dynamic_configuration_is_rejected(self):
        for invalid in (None,{},dict(CFG,version='unknown'),dict(CFG,assumption=''),dict(CFG,bonus=1)):
            s,p=inputs();p['fire_dynamics']=invalid
            with self.subTest(value=invalid),self.assertRaisesRegex(ValueError,'密度|火力过程'):ho.initial(s,p)

    def test_frozen_old_world_cannot_be_hot_migrated(self):
        old=world(selected=False);old['combat_reference']=combat_effects.reference(old)
        old['mission']['definition']['fire_dynamics']=copy.deepcopy(CFG)
        with self.assertRaisesRegex(ValueError,'冻结|新建'):combat_effects.reference(old)

    def test_frozen_new_world_cannot_silently_drop_the_option(self):
        w=world();w['combat_reference']=combat_effects.reference(w)
        del w['mission']['definition']['fire_dynamics']
        with self.assertRaisesRegex(ValueError,'冻结|新建'):combat_effects.reference(w)

    def test_explicit_draft_reference_change_is_detached_and_keeps_parameters(self):
        old=world(selected=False);ref=combat_effects.reference(old);w=copy.deepcopy(old)
        w['mission']['definition']['fire_dynamics']=copy.deepcopy(CFG)
        before=copy.deepcopy((old,ref,w))
        new=combat_effects.configuration_reference(w,ref)
        self.assertEqual(new['fire_dynamics'],CFG)
        self.assertEqual(new['direct_fire'],ref['direct_fire'])
        self.assertEqual((old,ref,w),before)
        w['mission']['turn']=1
        with self.assertRaisesRegex(ValueError,'新建|运行'):combat_effects.configuration_reference(w,ref)

    def test_synthetic_seed_and_derivative_keep_the_explicit_rule(self):
        w=world();binding=w['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding)
        self.assertEqual(seed['configuration']['fire_dynamics'],CFG)
        spec=synthetic_history.definition(binding,seed['configuration'])
        self.assertEqual(combat_effects.reference(missions.from_definition(spec))['fire_dynamics'],CFG)

    def test_required_native_generator_cannot_omit_selected_rule(self):
        s,p=inputs()
        with self.assertRaisesRegex(ValueError,'密度|fire_dynamics'):
            scenario_assembly.validate_required_models(p,[CFG['version']])
        p['fire_dynamics']=copy.deepcopy(CFG)
        scenario_assembly.validate_required_models(p,[CFG['version']])
        self.assertIn('fire_dynamics',scenario_assembly.OPTIONAL_GLOBAL_FIELDS)
        basis={'configuration_template':{}}
        scenario_assembly.prepare_required_models(basis,[CFG['version']])
        self.assertEqual(basis['configuration_template']['fire_dynamics']['version'],CFG['version'])

    def test_phase_continuation_keeps_the_rule_and_rejects_mid_chain_changes(self):
        from gentactix import phase_continuity
        from verify_phase_continuity import checkpoint
        source,target=checkpoint(fire_dynamics=CFG)
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(source,target)))
        self.assertEqual(child['mission']['definition']['fire_dynamics'],CFG)
        self.assertEqual(child['red_units'][0]['personnel'],source['red_units'][0]['personnel'])
        target['parameters'].pop('fire_dynamics')
        with self.assertRaisesRegex(ValueError,'动态密度'):
            phase_continuity.definition(phase_continuity.bind(source,target))

    def test_dsh_submission_remains_a_model_estimate_without_native_samples(self):
        from backend import dsh_simulation
        from verify_fire_accounting import FireAccountingTests
        s,p=inputs();p['fire_dynamics']=copy.deepcopy(CFG);p['fire_accounting']=copy.deepcopy(ACCOUNT)
        actor=p['actors']['ww2.cn.division31'];actor['equipment']['artillery']=3
        actor['formation']['shells']=54;actor['logistics']['ammo']=0
        w=ho.initial(s,p);candidate=FireAccountingTests().shot(w)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')):
            after=dsh_simulation.apply(w,candidate,'30分钟',require_fire_ledger=True)
        self.assertEqual(after['combat_reference']['combat_revision'],4)
        self.assertEqual(after['dsh_execution']['fire_ledger']['source'],'dsh_model_estimate')
        self.assertNotIn('last_density_sample',after['red_units'][0]['formation'])

    def test_current_native_sample_is_projected_but_stale_and_dsh_samples_are_not(self):
        from backend import afsim_state
        w=world();w['mission']['turn']=1
        sample=dict(version=CFG['version'],source='afsim_native',turn=1,sample_s=120,
                    lat_cell=0,lng_cell=0,own_current=6000,eligible=1,footprint_committed=6000,footprint_current=6000)
        w['red_units'][0]['formation']['last_density_sample']=copy.deepcopy(sample)
        session=dict(id='density-observation',war_state=w,turn_count=1,time_step='30分钟',execution_backend='afsim',simulation_mode='open')
        row=afsim_state.observation(session,{'limit':1})['units'][0]
        self.assertEqual(row['formation']['last_density_sample'],sample)
        w['red_units'][0]['formation']['last_density_sample']['turn']=0
        self.assertNotIn('last_density_sample',afsim_state.observation(session,{'limit':1})['units'][0]['formation'])
        w['red_units'][0]['formation']['last_density_sample']['turn']=1;w['dsh_execution']={'source':'dsh_model_estimate'}
        self.assertNotIn('last_density_sample',afsim_state.observation(session,{'limit':1})['units'][0]['formation'])

    def test_synthetic_model_binding_cannot_silently_omit_rule(self):
        w=world();binding=w['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding)['configuration'];candidate=copy.deepcopy(seed)
        del candidate['fire_dynamics']
        with self.assertRaisesRegex(ValueError,'fire_dynamics|密度'):
            scenario_builder.bind_model_configuration('unused',candidate,historical_base=binding)
        value=scenario_builder.bind_model_configuration('unused',seed,historical_base=binding)
        self.assertEqual(value['fire_dynamics'],CFG)

    def test_native_compiler_selects_new_model_without_running_python_combat(self):
        w=world(accounting=True);a=w['red_units'][0];b=w['blue_units'][0]
        with patch.object(missions,'advance',side_effect=AssertionError('No Python executor')):
            scene=afsim_world.compile_scene(w,[dict(unit=a['name'],action='bombard',target=b['name'])],1800,native_rules=True)
        self.assertEqual(scene['native_model']['combat_revision'],4)
        self.assertIn('GTXDENSITY|',scene['script'])
        # One setup sample plus samples before the existing simultaneous-fire loop.
        self.assertIn('density_own_current',scene['script'])

    def test_dsh_observation_reports_dynamic_sampling_and_not_a_convergence_claim(self):
        w=world();before=copy.deepcopy(w);view=fire_process.observation(w)
        self.assertEqual(view['feedback']['indirect_density_sampling'],'live_shared_footprint')
        self.assertFalse(view['feedback']['partition_invariance_verified'])
        self.assertEqual(view['fire_profile']['fire_dynamics'],CFG)
        self.assertIn('同批',view['feedback']['density_scope'])
        self.assertNotIn('轮内没有',view['feedback']['density_scope'])
        self.assertEqual(w,before)

    def test_profile_requires_both_new_version_and_option_hash(self):
        ref=combat_effects.reference(world())
        for invalid in ('missing','old_version','old_revision'):
            changed=copy.deepcopy(ref)
            if invalid=='missing':del changed['fire_dynamics']
            elif invalid=='old_version':changed['version']='aggregate-fire-cycles-2.3'
            else:changed['combat_revision']=2
            changed['definition_hash']=combat_effects.digest({k:v for k,v in changed.items()if k!='definition_hash'})
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):combat_effects.validate_profile(changed)


if __name__=='__main__':unittest.main(verbosity=2)
