"""Person-scaled ration mass, frozen capacity and existing executor contracts."""
import copy
import unittest

from gentactix import support_dynamics as sd, historical_operations as ho, missions
from tools.qa.historical_operational_fixture import inputs
from verify_support_dynamics import config as legacy_config
from verify_split_supply import config as split_config

VERSION='personnel-rations-1'


def config():
    cfg=legacy_config();cfg.pop('food_work_per_hour')
    cfg.update(version=VERSION,ration_kg_per_person_day=.75,food_kg_per_work=125,
               carried_kg_per_committed_person=.5,
               assumption='Explicit software QA estimates of dry-food mass; not historical rations, physiological requirements or disease calibration.')
    return cfg


def parameters(food=2):
    snapshot,p=inputs();p['support_dynamics']=config();p['supply_distribution']=split_config()
    p['rules']['ton_per_supply_unit']=.25
    for actor in p['actors'].values():actor['logistics']['food']=food
    return snapshot,p


def world(food=2):return ho.initial(*parameters(food))


class PersonnelRationsTests(unittest.TestCase):
    def test_invalid_version_types_mixed_units_and_nonfinite_rates_are_rejected(self):
        for patch in ({'version':[]},{'version':{}},{'ration_kg_per_person_day':True},
                      {'ration_kg_per_person_day':float('nan')},{'food_kg_per_work':0},{'food_work_per_hour':4}):
            s,p=parameters();p['support_dynamics'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):ho.initial(s,p)

    def test_explicit_new_version_freezes_without_reinterpreting_legacy(self):
        w=world();self.assertEqual(w['mission']['definition']['support_dynamics'],config())
        self.assertTrue(all(u['sustainment']['version']==VERSION for _,u in missions.units(w)))
        self.assertTrue(missions.validate(w))
        s,p=inputs();p['support_dynamics']=legacy_config();old=ho.initial(s,p)
        self.assertEqual(old['mission']['definition']['support_dynamics'],legacy_config())

    def test_same_ration_scales_with_actual_people_not_number_of_formations(self):
        w=world();a,b=w['red_units'][0],w['blue_units'][0]
        self.assertEqual(sd.expected(config(),a,'hold',3600)['demand'],1.5)
        self.assertEqual(sd.expected(config(),b,'hold',3600)['demand'],.75)
        self.assertEqual(sd.expected(config(),a,'move',3600)['demand'],3)

    def test_deaths_reduce_next_demand_without_deleting_carried_food_or_capacity(self):
        u=world()['red_units'][0];prior=copy.deepcopy(u);u['personnel']['current']=3000
        self.assertEqual(sd.expected(config(),u,'hold',3600)['demand'],.75)
        self.assertEqual(sd.food_capacity(config(),u),sd.food_capacity(config(),prior))
        self.assertEqual(sd.food_mass(config(),u),250)
        u['personnel']['current']=0
        self.assertEqual(sd.expected(config(),u,'hold',3600)['demand'],0)

    def test_capacity_comes_from_frozen_committed_load_not_generic_100(self):
        u=world()['red_units'][0]
        self.assertEqual(sd.food_capacity(config(),u),24)
        s,p=parameters();p['actors']['ww2.cn.division31']['logistics']['food']=25
        with self.assertRaisesRegex(ValueError,'携行|容量'):ho.initial(s,p)

    def test_transport_and_food_mass_conversion_cannot_diverge(self):
        for edit in ('missing_split','wrong_mass','too_large_capacity'):
            s,p=parameters()
            if edit=='missing_split':p.pop('supply_distribution')
            elif edit=='wrong_mass':p['rules']['ton_per_supply_unit']=.5
            else:p['support_dynamics']['carried_kg_per_committed_person']=5
            with self.subTest(edit=edit),self.assertRaises(ValueError):ho.initial(s,p)

    def test_fractional_split_conserves_demand_mass_and_capacity(self):
        from gentactix import formation_conversion as fc
        u=world()['red_units'][0]
        result=fc.split_current(u,[dict(id='a',label='A',committed=2400),dict(id='b',label='B',committed=3600)],
            assumption='Software conservation only',operation_id='d'*32,product_mode='synthetic')
        leaves=result['after']
        self.assertAlmostEqual(sum(sd.expected(config(),v,'hold',3600)['demand'] for v in leaves),1.5)
        self.assertAlmostEqual(sum(sd.food_mass(config(),v) for v in leaves),250)
        from gentactix import formation_parts
        self.assertAlmostEqual(sum(sd.food_capacity(config(),v)*formation_parts.scale(v) for v in leaves),24)

    def test_partial_food_and_step_partition_without_attrition(self):
        u=world()['red_units'][0];u['logistics']['food']=1
        full=sd.expected(config(),u,'hold',3600)
        first=sd.expected(config(),u,'hold',1800);second=copy.deepcopy(u)
        second['logistics']['food']-=first['consumed']
        second['sustainment'].update({k:first[k] for k in ('shortage_hours','noncombat_remainder')})
        tail=sd.expected(config(),second,'hold',1800)
        self.assertAlmostEqual(full['consumed'],first['consumed']+tail['consumed'])
        self.assertAlmostEqual(full['shortage_hours'],tail['shortage_hours'])

    def test_readonly_budget_exposes_kilograms_and_person_coupled_horizon(self):
        from gentactix import sustainment,resource_readiness
        w=world();budget=sustainment.assess(w);readiness=resource_readiness.assess(w)
        self.assertEqual(budget['teams']['red']['food_per_hold_round'],.75)
        self.assertEqual(budget['teams']['red']['on_hand_food_kg'],250)
        row=next(r for r in readiness['units'] if r['team']=='red')
        self.assertAlmostEqual(row['food_hold_hours'],2/1.5)
        self.assertEqual(row['food_capacity_kg'],3000)
        self.assertEqual(row['food_on_hand_kg'],250)

    def test_native_compilation_uses_same_demand_and_smaller_carrying_capacity(self):
        from backend import afsim_sustainment,afsim_split_supply
        u=world()['red_units'][0]
        text='\n'.join(afsim_sustainment.finish(config(),u,'hold',3600,0,'unit','sp'))
        self.assertIn('foodNeed0=1.5',text)
        split='\n'.join(afsim_split_supply.plan(split_config(),u,0,0,nutrition=config()))
        self.assertIn('22',split)

    def test_required_model_is_exact_and_staged_draft_does_not_guess_missing_values(self):
        from backend import scenario_assembly as sa,scenario_builder as sb
        from tools.qa.historical_operational_fixture import BATTLE
        basis=sb.historical_basis(BATTLE,'taierzhuang')
        sa.prepare_required_models(basis,[VERSION]);t=basis['configuration_template']['support_dynamics']
        self.assertEqual(t['version'],VERSION);self.assertIsNone(t['ration_kg_per_person_day'])
        _,p=parameters();sa.validate_required_models(p,[VERSION])
        p['support_dynamics']=legacy_config()
        with self.assertRaises(ValueError):sa.validate_required_models(p,[VERSION])

    def test_real_model_effect_contract_requires_explicit_personnel_receipt(self):
        from backend import dsh_simulation
        from verify_dsh_resources import model_result
        w=world();value=model_result(w);original=copy.deepcopy(w)
        value['sustainment_ledger']={'version':VERSION,'units':[]}
        updates={row['unit']:row for row in value['unit_updates']}
        accounts={row['unit']:row for row in value['resource_ledger']['units']}
        for _,u in missions.units(w):
            receipt=sd.expected(config(),u,'hold',1800);row=updates[u['name']]
            row['sustainment']={'version':VERSION,**{k:receipt[k] for k in ('shortage_hours','noncombat_remainder')}}
            row.setdefault('logistics',{})['food']=u['logistics']['food']-receipt['consumed']
            accounts[u['name']]['food_spent']=receipt['consumed']
            value['sustainment_ledger']['units'].append(dict(unit=u['name'],**receipt))
        proposed=copy.deepcopy(value);after=dsh_simulation.apply(w,value,'30分钟')
        self.assertEqual(after['red_units'][0]['logistics']['food'],1.25)
        self.assertEqual(w,original);self.assertEqual(value,proposed)
        bad=copy.deepcopy(value);bad['sustainment_ledger']['version']='time-sustainment-1'
        with self.assertRaises(ValueError):dsh_simulation.apply(w,bad,'30分钟')
        self.assertEqual(w,original)
        self.assertIn('不再乘编组份额',dsh_simulation.prompt(w))

    def test_synthetic_baseline_and_phase_freeze_keep_selected_mass_model(self):
        from gentactix import synthetic_history
        w=world();binding=w['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding)
        generated=missions.from_definition(synthetic_history.definition(binding,seed['configuration']))
        self.assertEqual(generated['mission']['definition']['support_dynamics'],config())
        self.assertEqual(sd.food_mass(config(),generated['red_units'][0]),250)

    def test_scheduled_native_expression_reduces_demand_after_prior_shortage_losses(self):
        from backend import afsim_supply_schedule
        w=world();u=w['red_units'][0]
        text='\n'.join(afsim_supply_schedule._consume({**w,'_schedule_orders':{}},u,'sp'))
        self.assertIn('6000-sp.AuxDataDouble("sl_nc")',text)
        self.assertIn('0.00025',text)

    def test_edited_draft_records_new_requirements_without_mutating_parent(self):
        import os,tempfile,json
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as sb
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            s,p=parameters();old=copy.deepcopy(p);old['support_dynamics']=legacy_config()
            parent=sb.stage_historical(s,old,construction={'source':'dsh_native_skill','required_models':['time-sustainment-1']},execution_backend='narrative')
            path=sb.directory()/(parent['id']+'.json');original=path.read_bytes()
            reply=TestClient(main.app).post('/api/historical-scenarios/validate',json=dict(parameters=p,parent_draft_id=parent['id'],
                required_models=[VERSION],execution_backend='narrative'))
            self.assertEqual(reply.status_code,200,reply.text)
            record=reply.json();self.assertEqual(record['construction']['required_models'],[VERSION])
            self.assertEqual(record['parameters']['support_dynamics']['version'],VERSION)
            self.assertEqual(path.read_bytes(),original)

    def test_manual_edit_does_not_require_or_rebind_original_generation_checkpoint(self):
        import os,tempfile,json
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as sb
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder+'/sessions'}):
            s,p=parameters();old=copy.deepcopy(p);old['support_dynamics']=legacy_config()
            parent=sb.stage_historical(s,old,construction={'source':'dsh_native_skill'},execution_backend='narrative')
            path=sb.directory()/(parent['id']+'.json');record=json.loads(path.read_text())
            record['construction']['assembly_checkpoint_id']='a'*32
            path.write_text(json.dumps(record));original=path.read_bytes()
            response=TestClient(main.app).post('/api/historical-scenarios/validate',json=dict(parameters=p,parent_draft_id=parent['id'],
                required_models=[VERSION],execution_backend='narrative'))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['construction']['assembly_checkpoint_id'],'a'*32)
            self.assertTrue(response.json()['construction']['manual_revision'])
            self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
