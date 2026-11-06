"""Opt-in classified indirect ammunition, frozen legacy costs and Native contracts."""
import copy
import json
from pathlib import Path
import subprocess
import os
import tempfile
import unittest
from unittest.mock import patch

from backend import afsim_world, dsh_simulation, scenario_assembly
from gentactix import combat_effects, combined_arms, fire_process, historical_operations as ho, missions, resource_readiness
from tools.qa.historical_operational_fixture import inputs, NOTE
from verify_dsh_resources import model_result

CFG = {'version':'classified-indirect-1', 'assumption':NOTE+'；通用弹药仅代表直射轻武器，炮击另按分类实弹记账。'}


class FireAccountingTests(unittest.TestCase):
    def world(self, *, selected=True, ammo=0, shells=54):
        snapshot, params = inputs()
        unit = params['actors']['ww2.cn.division31']
        unit['equipment']['artillery'] = 3
        unit['logistics']['ammo'] = ammo
        unit['formation']['shells'] = shells
        if selected: params['fire_accounting'] = copy.deepcopy(CFG)
        return ho.initial(snapshot, params)

    def shot(self, world, *, cycles=2, shells=12):
        value = model_result(world); actor=world['red_units'][0]; target=world['blue_units'][0]
        value['orders'][0].update(action='bombard',target=target['name'])
        value['engagements']=[dict(attacker=actor['name'],attacker_team='red',attacker_pos=[actor['lat'],actor['lng']],
            target=target['name'],lat=target['lat'],lng=target['lng'],weapon_action='bombard')]
        value['resource_ledger']['units'][0]['spent']={'shells':shells}
        value['unit_updates'][0]['formation'].update(shells=actor['formation']['shells']-shells,
            suppression=0,intel_confidence=70,reload_remaining_s=0)
        value['unit_updates'][1]['formation']['suppression']=30
        value['fire_ledger']={'version':fire_process.VERSION,'units':[dict(unit=actor['name'],action='bombard',
            target=target['name'],delay_s=fire_process.delay_seconds(world,actor),first_fire_s=150,
            last_fire_s=150+(cycles-1)*120,fire_cycles=cycles,active_fire_s=cycles*120,
            reload_remaining_s=0,stop_reason='uncertain',assumptions=NOTE)]}
        return value

    def apply(self, world, candidate):
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            return dsh_simulation.apply(world,candidate,'30分钟',require_fire_ledger=True)

    def test_legacy_zero_work_still_blocks_indirect_fire(self):
        world=self.world(selected=False); unit=world['red_units'][0]
        self.assertNotIn('bombard',combined_arms.actions(world,unit,'red'))
        self.assertNotIn('fire_accounting',world['mission']['definition'])
        self.assertEqual(combat_effects.reference(world)['combat_revision'],2)

    def test_frozen_root_profile_is_the_action_gate_source(self):
        world=self.world(selected=False,ammo=.75); unit=world['red_units'][0]
        ref=combat_effects.reference(world);ref['ammo_per_cycle']=.5
        ref['definition_hash']=combat_effects.digest({k:v for k,v in ref.items()if k!='definition_hash'})
        world['combat_reference']=ref
        self.assertIn('fire',combined_arms.actions(world,unit,'red'))
        self.assertIn('bombard',combined_arms.actions(world,unit,'red'))

    def test_selected_profile_freezes_a_distinct_revision_and_action_costs(self):
        world=self.world();ref=combat_effects.reference(world)
        self.assertEqual(ref['version'],'aggregate-fire-cycles-2.4')
        self.assertEqual(ref['combat_revision'],3)
        self.assertEqual(ref['fire_accounting'],CFG)
        self.assertTrue(combat_effects.validate_profile(ref))
        self.assertEqual([combat_effects.work_cost(ref,a)for a in ('fire','bombard','suppress')],[1,0,0])
        old=combat_effects.reference(self.world(selected=False,ammo=2))
        self.assertEqual([combat_effects.work_cost(old,a)for a in ('fire','bombard','suppress')],[1,1,1])

    def test_selected_indirect_fire_uses_shells_while_direct_still_needs_work(self):
        world=self.world();unit=world['red_units'][0];actions=combined_arms.actions(world,unit,'red')
        self.assertIn('bombard',actions);self.assertIn('suppress',actions);self.assertNotIn('fire',actions)
        target=world['blue_units'][0]
        self.assertTrue(missions.validate_orders(world,[dict(unit=unit['name'],action='bombard',target=target['name'])],'30分钟'))

    def test_empty_or_unavailable_weapons_do_not_gain_free_fire(self):
        for kind in ('no_shells','no_guns','no_people'):
            world=self.world(ammo=80);unit=world['red_units'][0]
            if kind=='no_shells':unit['formation']['shells']=0
            elif kind=='no_guns':
                gun=next(e for e in unit['equipment']if e['category']=='artillery');gun.update(destroyed=gun['operational'],operational=0)
            else:unit['personnel'].update(casualties=unit['personnel']['current'],current=0)
            with self.subTest(kind=kind):
                if kind=='no_people':
                    with self.assertRaisesRegex(ValueError,'无可用人员'):
                        missions.validate_orders(world,[dict(unit=unit['name'],action='bombard',target=world['blue_units'][0]['name'])],'30分钟')
                else:self.assertNotIn('bombard',combined_arms.actions(world,unit,'red'))

    def test_actual_shell_expense_is_preserved_without_charging_generic_work(self):
        world=self.world();candidate=self.shot(world);prior=copy.deepcopy((world,candidate))
        after=self.apply(world,candidate)
        unit=after['red_units'][0]
        self.assertEqual(unit['logistics']['ammo'],0)
        self.assertEqual(unit['formation']['shells'],42)
        self.assertEqual(after['mission']['ledger'][0]['ammo_spent'],0)
        self.assertEqual(after['mission']['ledger'][0]['spent']['shells'],12)
        self.assertEqual(after['combat_reference']['combat_revision'],3)
        self.assertEqual((world,candidate),prior)

    def test_zero_expense_engagement_and_extra_generic_debit_are_rejected(self):
        world=self.world(ammo=2)
        for kind in ('free','extra_generic'):
            candidate=self.shot(world)
            if kind=='free':
                candidate['resource_ledger']['units'][0]['spent']={}
                candidate['unit_updates'][0]['formation']['shells']=54
            else:
                candidate['resource_ledger']['units'][0]['ammo_spent']=2
                candidate['unit_updates'][0]['logistics']['ammo']=0
            frozen=copy.deepcopy(world)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(world,candidate)
            self.assertEqual(world,frozen)

    def test_last_partial_salvo_is_paid_by_one_real_shell(self):
        world=self.world(shells=1);after=self.apply(world,self.shot(world,cycles=1,shells=1))
        self.assertEqual(after['red_units'][0]['formation']['shells'],0)
        self.assertEqual(after['red_units'][0]['logistics']['ammo'],0)

    def test_native_input_uses_the_same_zero_indirect_cost_and_revision(self):
        world=self.world();unit=world['red_units'][0];target=world['blue_units'][0]
        scene=afsim_world.compile_scene(world,[dict(unit=unit['name'],action='bombard',target=target['name'])],1800,native_rules=True)
        self.assertEqual(scene['native_model']['combat_revision'],3)
        self.assertIn('p0.SetAuxData("ca_ammo_cycle",(double)(0))',scene['script'])
        self.assertIn('GtxCAStopFire(actor,6)',scene['script'])

    def test_budget_states_which_actions_use_work_and_does_not_zero_divide(self):
        world=self.world();unit=world['red_units'][0]
        value=resource_readiness.fire_budget(world,unit)
        self.assertEqual(value['ammo_work']['applies_to'],['fire'])
        self.assertEqual(value['indirect']['generic_work_per_cycle'],0)
        self.assertEqual(value['indirect']['full_salvos_at_ceiling'],9)
        row=next(r for r in resource_readiness.assess(world)['units']if r['unit']==unit['name'])
        self.assertEqual(row['fire_work_minutes'],0)
        self.assertEqual(row['artillery_minutes'],18)

    def test_frozen_profile_cannot_be_reinterpreted_by_a_different_config(self):
        world=self.world(selected=False,ammo=2);world['combat_reference']=combat_effects.reference(world)
        world['mission']['definition']['fire_accounting']=copy.deepcopy(CFG)
        with self.assertRaisesRegex(ValueError,'计量|参照'):combat_effects.reference(world)

    def test_required_model_exposes_shape_and_rejects_a_dropped_selection(self):
        _,params=inputs();basis={'configuration_template':params}
        scenario_assembly.prepare_required_models(basis,[CFG['version']])
        cfg=basis['configuration_template']['fire_accounting']
        self.assertEqual(cfg['version'],CFG['version'])
        scenario_assembly.validate_required_models(basis['configuration_template'],[CFG['version']])
        basis['configuration_template'].pop('fire_accounting')
        with self.assertRaises(ValueError):scenario_assembly.validate_required_models(basis['configuration_template'],[CFG['version']])

    def test_phase_handoff_cannot_silently_switch_ammunition_meaning(self):
        from verify_phase_rule_contracts import PhaseRuleContractTests
        from gentactix import phase_continuity
        source,target=PhaseRuleContractTests().source_and_target()
        target['parameters']['fire_accounting']=copy.deepcopy(CFG)
        with self.assertRaisesRegex(ValueError,'计量|物理.*规则'):
            phase_continuity.definition(phase_continuity.bind(source,target))

    def test_synthetic_configuration_can_select_it_without_changing_the_template(self):
        spec=combined_arms.demo_definition();before=copy.deepcopy(spec)
        cfg=combined_arms.configuration(spec['id']);cfg['fire_accounting']=copy.deepcopy(CFG)
        selected=combined_arms.configure(spec['id'],cfg);world=missions.from_definition(selected)
        self.assertEqual(combat_effects.reference(world)['combat_revision'],3)
        self.assertEqual(spec,before)

    def test_invalid_or_overbroad_accounting_configuration_is_rejected(self):
        for changed in ({**CFG,'version':'anything'}, {**CFG,'work_costs':{'fire':0}}, {**CFG,'assumption':''}):
            snapshot,params=inputs();params['fire_accounting']=changed
            with self.subTest(config=changed),self.assertRaises(ValueError):ho.initial(snapshot,params)

    def test_historical_synthetic_seed_retains_selection_and_explicit_disable_works(self):
        from gentactix import synthetic_history
        snapshot,params=inputs();params['fire_accounting']=copy.deepcopy(CFG)
        binding=dict(format=ho.FORMAT,initial=snapshot,parameters=params)
        seed=synthetic_history.seed(binding)
        self.assertEqual(seed['configuration']['fire_accounting'],CFG)
        retained=missions.from_definition(synthetic_history.definition(binding,seed['configuration']))
        self.assertEqual(combat_effects.reference(retained)['combat_revision'],3)
        seed['configuration'].pop('fire_accounting')
        disabled=missions.from_definition(synthetic_history.definition(binding,seed['configuration']))
        self.assertEqual(combat_effects.reference(disabled)['combat_revision'],2)

    def test_selected_dsh_prompt_does_not_require_extra_generic_expense(self):
        text=dsh_simulation.prompt(self.world())
        self.assertIn('work_cost_by_action',text)
        self.assertIn('炮击',text)
        self.assertNotIn('实际交火必须申报非零ammo_spent',text)

    def test_existing_native_patch_schema_accepts_only_the_declared_config_shape(self):
        code="import{configurationPatchSchema as s}from'./plugins/dsh-afsim/scenario-schema.mjs';console.log(JSON.stringify(s.properties.fire_accounting??null));"
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,check=True)
        schema=json.loads(result.stdout)
        self.assertIsInstance(schema,dict)
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']),{'version','assumption'})
        self.assertEqual(schema['properties']['version']['enum'],[CFG['version']])

    def test_synthetic_native_builder_accepts_explicit_accounting_choice(self):
        from backend import scenario_builder
        from gentactix import scenario_basis
        config=scenario_basis.exercise_seed('CA-AJ18-v1')['configuration']
        config['fire_accounting']=copy.deepcopy(CFG)
        bound=scenario_builder.bind_model_configuration('CA-AJ18-v1',config)
        self.assertEqual(bound['fire_accounting'],CFG)
        world,_=scenario_builder.validate_configuration('CA-AJ18-v1',bound)
        self.assertEqual(combat_effects.reference(world)['combat_revision'],3)

    def test_synthetic_native_basis_exposes_the_selected_accounting(self):
        from backend import scenario_builder
        from gentactix import scenario_basis
        seed=scenario_basis.exercise_seed('CA-AJ18-v1')
        seed['configuration']['fire_accounting']=copy.deepcopy(CFG)
        view=scenario_builder.execute_tool({'scenario_composer':{'mission_id':'CA-AJ18-v1','seed':seed}},
            {'tool':'get_scenario_basis'})
        self.assertEqual(view['configuration']['fire_accounting'],CFG)
        self.assertEqual(seed['configuration']['fire_accounting'],CFG)

    def test_native_model_cannot_silently_drop_accounting_from_historical_base(self):
        from backend import scenario_builder
        from gentactix import synthetic_history
        binding=self.world()['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding)
        with self.assertRaisesRegex(ValueError,'计量'):
            scenario_builder.bind_model_configuration(ho.from_binding(binding)['id'],
                {'teams':seed['configuration']['teams']},historical_base=binding)

    def test_new_draft_can_select_accounting_without_reinterpreting_frozen_parent(self):
        from backend import scenario_builder
        from gentactix import synthetic_history
        world=self.world(selected=False,ammo=2)
        previous=combat_effects.reference(world);previous['ammo_per_cycle']=.5
        previous['definition_hash']=combat_effects.digest({k:v for k,v in previous.items()if k!='definition_hash'})
        binding=world['mission']['definition']['historical_calculation']
        cfg=synthetic_history.seed(binding)['configuration'];cfg['fire_accounting']=copy.deepcopy(CFG)
        frozen=copy.deepcopy((world,previous,cfg))
        with tempfile.TemporaryDirectory()as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(Path(folder)/'sessions')}):
            draft=scenario_builder.stage(world['mission']['id'],cfg,construction={'source':'explicit_test_fixture'},
                historical_base=binding,combat_reference=previous,execution_backend='narrative')
        actual=draft['preview_world']['combat_reference']
        self.assertEqual(actual['combat_revision'],3)
        self.assertEqual(actual['ammo_per_cycle'],.5)
        self.assertEqual(draft['combat_reference'],actual)
        self.assertNotEqual(actual['definition_hash'],previous['definition_hash'])
        self.assertEqual((world,previous,cfg),frozen)

    def test_new_draft_can_disable_accounting_without_modifying_source(self):
        from backend import scenario_builder
        from gentactix import synthetic_history
        world=self.world(ammo=2);binding=world['mission']['definition']['historical_calculation']
        previous=combat_effects.reference(world);frozen=copy.deepcopy((world,previous))
        cfg=synthetic_history.seed(binding)['configuration'];cfg.pop('fire_accounting')
        new,_=scenario_builder.validate_configuration(world['mission']['id'],cfg,
            historical_base=binding,combat_reference=previous)
        self.assertEqual(combat_effects.reference(new)['combat_revision'],2)
        self.assertNotIn('fire_accounting',new['combat_reference'])
        self.assertEqual((world,previous),frozen)

    def test_explicit_configuration_rebind_refuses_a_world_with_executed_turns(self):
        world=self.world();previous=combat_effects.reference(world)
        world['mission']['turn']=1
        frozen=copy.deepcopy((world,previous))
        with self.assertRaisesRegex(ValueError,'已运行|未执行'):
            combat_effects.configuration_reference(world,previous)
        self.assertEqual((world,previous),frozen)

    def test_generate_and_revalidate_requests_share_classified_model_choices(self):
        from backend import scenario_builder as builder
        built=builder.HistoricalBuildRequest(battle='QA',phase_id='opening',required_models=[CFG['version']])
        revised=builder.HistoricalValidateRequest(parameters={},parent_draft_id='a'*32,
            required_models=built.required_models)
        self.assertEqual(revised.required_models,[CFG['version']])
        with self.assertRaises(ValueError):
            builder.HistoricalValidateRequest(parameters={},parent_draft_id='a'*32,required_models=['invented'])


if __name__=='__main__':unittest.main()
