"""Time-based food contracts: explicit estimates, replay and native parity."""
import copy
import unittest

from gentactix import historical_operations as ho, missions
from tools.qa.historical_operational_fixture import inputs


def config():
    return {'version':'time-sustainment-1','food_work_per_hour':4,'move_factor':2,
            'shortage_fatigue_per_hour':2,'recovery_hours_per_fed_hour':1,
            'incapacity_after_hours':48,'incapacity_fraction_per_hour':.0001,
            'assumption':'QA sensitivity inputs only; not historical or physiological calibration'}


def world(food=0, step='30分钟'):
    s,p=inputs();p['support_dynamics']=config();p['clock']['time_step']=step
    for a in p['actors'].values():a['logistics']['food']=food
    return ho.initial(s,p)


class SupportDynamicsTests(unittest.TestCase):
    def test_explicit_configuration_freezes_and_old_definitions_stay_unchanged(self):
        w=world();self.assertEqual(w['mission']['definition']['support_dynamics'],config())
        self.assertTrue(missions.validate(copy.deepcopy(w)))
        s,p=inputs();old=ho.initial(s,p)
        self.assertNotIn('support_dynamics',old['mission']['definition'])
        self.assertTrue(all('sustainment' not in u for _,u in missions.units(old)))

    def test_short_shortage_has_no_instant_fixed_attrition(self):
        from gentactix import support_dynamics as sd
        w=world();u=w['red_units'][0];r=sd.expected(config(),u,'hold',1800)
        self.assertEqual(r['shortage_hours'],.5);self.assertEqual(r['noncombat_delta'],0)
        self.assertEqual(r['fatigue_floor'],1);self.assertEqual(r['unmet'],2)

    def test_elapsed_time_controls_food_and_late_delivery_cannot_feed_past_hours(self):
        from gentactix import support_dynamics as sd
        w=world(.5);u=w['red_units'][0]
        r=sd.expected(config(),u,'hold',900)
        self.assertEqual(r['demand'],1);self.assertEqual(r['consumed'],.5)
        self.assertEqual(r['shortage_hours'],.125)
        self.assertEqual(sd.expected(config(),u,'move',900)['demand'],2)

    def test_fractional_losses_survive_round_boundaries_and_are_not_deaths(self):
        from gentactix import support_dynamics as sd
        u=world()['red_units'][0];u['sustainment']['shortage_hours']=48
        full=sd.expected(config(),u,'hold',3600)
        half=sd.expected(config(),u,'hold',1800);second=copy.deepcopy(u)
        second['sustainment'].update(shortage_hours=half['shortage_hours'],noncombat_remainder=half['noncombat_remainder'])
        second['personnel']['current']-=half['noncombat_delta']
        tail=sd.expected(config(),second,'hold',1800)
        self.assertEqual(full['noncombat_delta'],half['noncombat_delta']+tail['noncombat_delta'])
        self.assertAlmostEqual(full['noncombat_remainder'],tail['noncombat_remainder'])
        self.assertNotIn('killed',full)

    def test_fed_time_recovers_debt_and_bad_config_is_rejected(self):
        from gentactix import support_dynamics as sd
        u=world(50)['red_units'][0];u['sustainment']['shortage_hours']=3
        self.assertEqual(sd.expected(config(),u,'hold',3600)['shortage_hours'],2)
        for field,value in [('food_work_per_hour',float('nan')),('assumption',''),('move_factor',True),('version','unknown')]:
            s,p=inputs();p['support_dynamics']={**config(),field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):ho.initial(s,p)

    def test_partial_feeding_before_hunger_is_invariant_to_step_partition(self):
        from gentactix import support_dynamics as sd
        u=world(1)['red_units'][0];u['sustainment']['shortage_hours']=49
        full=sd.expected(config(),u,'hold',3600)
        fed=sd.expected(config(),u,'hold',900);second=copy.deepcopy(u)
        second['logistics']['food']=0
        second['sustainment'].update(shortage_hours=fed['shortage_hours'],noncombat_remainder=fed['noncombat_remainder'])
        tail=sd.expected(config(),second,'hold',2700)
        self.assertAlmostEqual(full['noncombat_delta']+full['noncombat_remainder'],
                               fed['noncombat_delta']+tail['noncombat_delta']+tail['noncombat_remainder'])

    def test_dsh_receipts_are_required_checked_and_do_not_repair_the_model(self):
        from backend import dsh_simulation
        from gentactix import support_dynamics as sd
        from verify_dsh_resources import model_result
        w=world(0);value=model_result(w);value['sustainment_ledger']={'version':sd.VERSION,'units':[]}
        for row,(_,u) in zip(value['unit_updates'],missions.units(w)):
            r=sd.expected(config(),u,'hold',1800)
            row['sustainment']={'version':sd.VERSION,**{k:r[k] for k in ('shortage_hours','noncombat_remainder')}}
            value['sustainment_ledger']['units'].append({'unit':u['name'],**r})
        frozen=copy.deepcopy(w);proposal=copy.deepcopy(value)
        after=dsh_simulation.apply(w,value,'30分钟')
        self.assertEqual(after['red_units'][0]['sustainment']['shortage_hours'],.5)
        self.assertEqual(w,frozen);self.assertEqual(value,proposal)
        missing=copy.deepcopy(value);missing.pop('sustainment_ledger')
        with self.assertRaisesRegex(ValueError,'sustainment_ledger'):dsh_simulation.apply(w,missing,'30分钟')
        bad=copy.deepcopy(value);bad['sustainment_ledger']['units'][0]['noncombat_delta']=2
        with self.assertRaisesRegex(ValueError,'时间保障'):dsh_simulation.apply(w,bad,'30分钟')
        prompt=dsh_simulation.prompt(w)
        self.assertIn('sustainment_ledger',prompt);self.assertNotIn('food_spent取需求和轮初food+delivery',prompt)

    def test_new_budget_and_synthetic_baseline_preserve_configuration(self):
        from gentactix import sustainment,synthetic_history
        w=world();binding=w['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding)
        hs=missions.from_definition(synthetic_history.definition(binding,seed['configuration']))
        self.assertEqual(hs['mission']['definition']['support_dynamics'],config())
        self.assertTrue(all(u['sustainment']['shortage_hours']==0 for _,u in missions.units(hs)))
        self.assertEqual(sustainment.assess(w)['dynamics'],config())

    def test_dsh_native_configuration_tool_can_set_optional_model_without_full_world(self):
        from backend import scenario_builder,scenario_assembly
        from tools.qa.historical_operational_fixture import BATTLE
        basis=scenario_builder.historical_basis(BATTLE,'taierzhuang');assembly=scenario_assembly.create(basis)
        self.addCleanup(scenario_assembly.close,assembly.id)
        _,p=inputs();p['goal']['team']=basis['configuration_template']['goal']['team']
        patch={k:v for k,v in p.items() if k not in ('format','phase_id','actors')};patch['support_dynamics']=config()
        result=assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':patch})
        self.assertTrue(result['updated'],result.get('error'))
        self.assertEqual(assembly.tool('globals','get_scenario_basis',{})['configuration']['support_dynamics'],config())


if __name__=='__main__':unittest.main()
