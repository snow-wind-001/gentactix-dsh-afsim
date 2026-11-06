"""Orders constrain model estimates; no effect generator or casualty quota."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_operations,missions
from tools.qa.historical_operational_fixture import inputs
from verify_dsh_resources import model_result


class DSHCommandEffectTests(unittest.TestCase):
    def setUp(self):self.before=historical_operations.initial(*inputs())

    def apply(self,value):
        from backend import dsh_simulation
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            return dsh_simulation.apply(self.before,value,'30分钟')

    def move(self,*,delta=.0009,actual=None):
        value=model_result(self.before);u=self.before['red_units'][0];p={'lat':u['lat']+delta,'lng':u['lng']}
        value['orders'][0].update(action='move',**p)
        value['unit_updates'][0].update(actual or p)
        value['unit_updates'][0]['logistics']['food']-=2
        value['unit_updates'][0]['formation'].update(fuel_liters=u['formation']['fuel_liters']-20)
        value['resource_ledger']['units'][0].update(food_spent=4,spent={'fuel_liters':20})
        return value

    def shot(self,action='fire',attacker_side='red',victim_side='blue'):
        value=model_result(self.before);attacker=self.before[attacker_side+'_units'][0];target=self.before[victim_side+'_units'][0]
        order=next(o for o in value['orders'] if o['unit']==attacker['name']);order.update(action=action,target=target['name'])
        account=next(r for r in value['resource_ledger']['units'] if r['unit']==attacker['name']);account['ammo_spent']=1
        change=next(r for r in value['unit_updates'] if r['unit']==attacker['name']);change['logistics']['ammo']-=1
        if action in ('bombard','suppress'):
            account['spent']={'shells':1};change['formation'].update(shells=attacker['formation']['shells']-1)
        value['engagements']=[{'attacker':attacker['name'],'attacker_team':attacker_side,'attacker_pos':[attacker['lat'],attacker['lng']],
            'lat':target['lat'],'lng':target['lng'],'weapon_action':action,'target':target['name']}]
        return value

    def test_hold_cannot_create_a_position_change(self):
        value=self.move();value['orders'][0]={'unit':value['orders'][0]['unit'],'action':'hold'}
        value['resource_ledger']['units'][0]['food_spent']=2;value['unit_updates'][0]['logistics']['food']+=2
        with self.assertRaisesRegex(ValueError,'位置命令'):self.apply(value)

    def test_an_authorized_move_reaches_its_own_destination_without_host_correction(self):
        value=self.move();old=copy.deepcopy(value);before=copy.deepcopy(self.before);after=self.apply(value)
        self.assertEqual(after['red_units'][0]['lat'],value['orders'][0]['lat'])
        self.assertEqual(value,old);self.assertEqual(self.before,before)
        self.assertEqual(after['dsh_execution']['command_validation_version'],'dsh-command-effects-1')

    def test_a_different_destination_inside_the_same_budget_is_not_the_ordered_move(self):
        u=self.before['red_units'][0];value=self.move(actual={'lat':u['lat']-.0009,'lng':u['lng']})
        with self.assertRaisesRegex(ValueError,'位置命令'):self.apply(value)

    def test_actual_motion_cannot_exceed_the_budget_even_inside_the_map(self):
        u=self.before['red_units'][0];value=self.move(actual={'lat':u['lat']+.04,'lng':u['lng']})
        with self.assertRaisesRegex(ValueError,'机动预算'):self.apply(value)

    def test_order_itself_is_checked_when_applying_a_direct_candidate(self):
        value=self.move(delta=.04)
        with self.assertRaisesRegex(ValueError,'移动超过'):self.apply(value)

    def test_ten_meter_existing_position_tolerance_does_not_change_coordinates(self):
        value=self.move();value['unit_updates'][0]['lat']+=.00001
        after=self.apply(value);self.assertEqual(after['red_units'][0]['lat'],value['unit_updates'][0]['lat'])

    def test_unavailable_unit_cannot_hide_an_unordered_teleport(self):
        u=self.last_hungry_person();value=model_result(self.before)
        value['unit_updates'][0].update(lat=u['lat']+.004,personnel={'current':0,'noncombat_losses':u['personnel']['noncombat_losses']+1},
            formation={'fuel_liters':u['formation']['fuel_liters']-20})
        value['resource_ledger']['units'][0]['spent']={'fuel_liters':20}
        with self.assertRaisesRegex(ValueError,'位置命令'):self.apply(value)

    def test_declared_loss_during_a_move_can_leave_a_bounded_partial_position(self):
        u=self.last_hungry_person();value=self.move(actual={'lat':u['lat']+.00045,'lng':u['lng']})
        value['unit_updates'][0]['logistics']['food']=0;value['resource_ledger']['units'][0]['food_spent']=0
        value['unit_updates'][0]['personnel']={'current':0,'noncombat_losses':u['personnel']['noncombat_losses']+1}
        after=self.apply(value);self.assertEqual(after['red_units'][0]['lat'],u['lat']+.00045)

    def last_hungry_person(self):
        # Geometry still needs an unavailable endpoint, but not an impossible
        # loss of a full, supplied formation during one model step.
        u=self.before['red_units'][0];p=u['personnel']
        p['noncombat_losses']+=p['current']-1;p['current']=1
        u['logistics']['food']=0;u['supply']=0;u['hp']=100/p['committed']
        return u

    def test_hold_cannot_generate_an_actual_shot_even_if_ammunition_is_spent(self):
        value=self.shot();value['orders'][0]={'unit':value['orders'][0]['unit'],'action':'hold'}
        with self.assertRaisesRegex(ValueError,'交战.*命令'):self.apply(value)

    def test_weapon_action_cannot_upgrade_a_direct_fire_order_to_artillery(self):
        value=self.shot();value['engagements'][0]['weapon_action']='bombard'
        with self.assertRaisesRegex(ValueError,'武器.*命令'):self.apply(value)

    def test_shot_cannot_substitute_a_different_enemy(self):
        value=self.shot();target=self.before['blue_units'][1]
        value['engagements'][0].update(target=target['name'],lat=target['lat'],lng=target['lng'])
        with self.assertRaisesRegex(ValueError,'交战目标.*命令'):self.apply(value)

    def test_target_coordinates_cannot_silently_switch_to_another_enemy(self):
        value=self.shot();target=self.before['blue_units'][1]
        value['engagements'][0].update(lat=target['lat'],lng=target['lng'])
        with self.assertRaisesRegex(ValueError,'交战目标.*坐标'):self.apply(value)

    def test_reported_combat_loss_requires_a_declared_incoming_engagement(self):
        value=model_result(self.before);u=self.before['red_units'][0]
        value['unit_updates'][0]['personnel']={'current':u['personnel']['current']-7,'casualties':7}
        with self.assertRaisesRegex(ValueError,'战斗减员.*交战'):self.apply(value)

    def test_valid_engagement_preserves_the_models_loss_estimate_not_a_quota(self):
        value=self.shot(attacker_side='blue',victim_side='red');u=self.before['red_units'][0]
        value['unit_updates'][0]['personnel']={'current':u['personnel']['current']-7,'casualties':7}
        after=self.apply(value);self.assertEqual(after['red_units'][0]['personnel']['casualties'],7)

    def test_firing_without_a_successful_hit_can_have_zero_losses(self):
        after=self.apply(self.shot('bombard'));self.assertEqual(after['blue_units'][0]['personnel']['casualties'],0)

    def test_public_decision_action_must_match_the_executed_order(self):
        value=model_result(self.before);value['decisions']=[{'team':'red','unit_name':self.before['red_units'][0]['name'],'action':'move','rationale':'错误声明'}]
        with self.assertRaisesRegex(ValueError,'决策.*命令'):self.apply(value)

    def test_duplicate_or_unknown_public_decisions_are_rejected(self):
        for kind in ('duplicate','unknown','team','not_list'):
            value=model_result(self.before);d={'team':'red','unit_name':self.before['red_units'][0]['name'],'action':'hold'}
            value['decisions']=[d,d] if kind=='duplicate' else [dict(d,unit_name='unknown')] if kind=='unknown' else [dict(d,team='blue')] if kind=='team' else 'hold'
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'决策'):self.apply(value)

    def test_process_event_action_must_belong_to_its_units_order(self):
        value=model_result(self.before);value['combined_arms']={'events':[{'unit':self.before['red_units'][0]['name'],'action':'fire','model_estimate':True}]}
        with self.assertRaisesRegex(ValueError,'过程事件.*命令'):self.apply(value)

    def test_native_equipment_damage_carry_cannot_be_edited_or_echoed_by_model(self):
        for amount in (0,.7):
            value=model_result(self.before);value['unit_updates'][0]['equipment']=[{'category':'armor','damage_load':amount}]
            with self.subTest(amount=amount),self.assertRaisesRegex(ValueError,'原生'):self.apply(value)

    def test_model_cannot_relabel_sources_or_change_its_formation_role(self):
        for field,update in (('personnel',{'source':'已核历史事实'}),('formation',{'source':'AFSIM实际回执'}),
                ('formation',{'role':'armor'}),('equipment',[{'category':'armor','source':'真实战果'}])):
            value=model_result(self.before);value['unit_updates'][0][field]=update
            with self.subTest(field=field,update=update),self.assertRaisesRegex(ValueError,'来源|角色'):self.apply(value)

    def test_missing_available_units_orders_are_not_inferred_as_hold(self):
        value=model_result(self.before);value['orders'].pop()
        with self.assertRaisesRegex(ValueError,'明确命令'):self.apply(value)

    def test_existing_one_retry_corrects_the_effect_without_mutating_the_prior_world(self):
        from backend import dsh_simulation
        bad=self.move();bad['orders'][0]['action']='hold';bad['resource_ledger']['units'][0]['food_spent']=2;bad['unit_updates'][0]['logistics']['food']+=2
        original=copy.deepcopy(self.before)
        with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,model_result(self.before)]) as model:
            result,_,_=dsh_simulation.advance({'war_state':self.before,'time_step':'30分钟'},None,None)
        self.assertEqual(model.call_count,2);self.assertIn('位置命令',model.call_args.args[0])
        self.assertEqual(self.before,original);self.assertEqual(result['updated_state']['red_units'][0]['lat'],self.before['red_units'][0]['lat'])

    def test_prompt_hides_host_only_damage_carry_without_editing_the_world(self):
        import json
        from backend import dsh_simulation
        unit=self.before['red_units'][0]
        unit['formation'].update(combat_damage_remainder=.25,fatality_remainder=.5,last_execution={'turn':0})
        prior=copy.deepcopy(self.before)
        text=dsh_simulation.prompt(self.before)
        view=json.loads(text.split('\n当前态势：',1)[1].split('\n史料：',1)[0])
        for key in ('combat_damage_remainder','fatality_remainder','last_execution'):
            self.assertNotIn(key,view['red_units'][0]['formation'])
        self.assertEqual(self.before,prior)


if __name__=='__main__':unittest.main()
