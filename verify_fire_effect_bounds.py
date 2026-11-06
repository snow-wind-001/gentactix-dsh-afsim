"""Necessary effect bounds, not an outcome calculator or historical quota."""
import copy
import math
import unittest
from unittest.mock import patch

from backend import dsh_simulation
from gentactix import missions


def fixture():
    from verify_fire_process import FireProcessTests
    probe=FireProcessTests();probe.setUp()
    world=probe.world;value=probe.shot();actor=world['red_units'][0];target=world['blue_units'][0]
    value['orders'][0]['action']='bombard';value['engagements'][0]['weapon_action']='bombard'
    row=value['fire_ledger']['units'][0];row['action']='bombard'
    account=value['resource_ledger']['units'][0];account['spent']={'shells':24}
    value['unit_updates'][0]['formation']['shells']=actor['formation']['shells']-24
    return world,value,target


def losses(world,value,target,amount):
    row=next(r for r in value['unit_updates'] if r['unit']==target['name'])
    row['personnel']={'current':target['personnel']['current']-amount,'casualties':target['personnel']['casualties']+amount}


class FireEffectBoundsTests(unittest.TestCase):
    def test_real_air_and_capture_paths_can_share_a_target_without_counting_capture_as_air_damage(self):
        from tools.qa.fire_effect_fixture import mixed_air_capture
        world,value,target,actor=mixed_air_capture()
        after=dsh_simulation.apply(world,value,'30分钟',require_fire_ledger=True)
        row=next(r for r in after['dsh_execution']['effect_admission']['units'] if r['unit']==target['name'])
        self.assertEqual((row['air_casualties'],row['captured'],row['ground_casualties']),(4,10,0))
        airborne=after['air_operations']['missions'][0]['target_turn_effects']
        self.assertEqual((airborne['air_casualties'],airborne['captured'],airborne['ground_casualties']),(4,10,0))
        bad=copy.deepcopy(value);bad['orders'][1]=dict(unit=actor['name'],action='hold')
        with self.assertRaisesRegex(ValueError,'航空|受降'):dsh_simulation.apply(world,bad,'30分钟',require_fire_ledger=True)
        bad=copy.deepcopy(value);bad['campaign']['actors'][target['name']]['captured_this_turn']=11
        with self.assertRaisesRegex(ValueError,'受降'):dsh_simulation.apply(world,bad,'30分钟',require_fire_ledger=True)

    def test_conserved_but_impossible_24_shell_239_loss_proposal_is_rejected_without_repair(self):
        world,value,target=fixture();losses(world,value,target,239);saved=copy.deepcopy((world,value))
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physics')):
            with self.assertRaisesRegex(ValueError,'效能.*上界'):
                dsh_simulation.apply(world,value,'30分钟',require_fire_ledger=True)
        self.assertEqual((world,value),saved)

    def test_zero_or_within_bound_losses_remain_estimates_without_forced_hits(self):
        for amount in (0,10):
            world,value,target=fixture();losses(world,value,target,amount)
            after=dsh_simulation.apply(world,value,'30分钟',require_fire_ledger=True)
            receipt=after['dsh_execution']['effect_admission']
            self.assertEqual(receipt['version'],'closed-fire-effect-bound-1')
            row=next(r for r in receipt['units'] if r['unit']==target['name'])
            self.assertEqual(row['ground_casualties'],amount)
            self.assertEqual(row['ground_maximum'],math.floor(24*1.5/math.sqrt(3)))
            self.assertFalse(receipt['calibration_proven'])

    def test_suppression_cannot_borrow_bombard_damage_efficiency(self):
        world,value,target=fixture();losses(world,value,target,10)
        value['orders'][0]['action']='suppress';value['engagements'][0]['weapon_action']='suppress'
        value['fire_ledger']['units'][0]['action']='suppress'
        with self.assertRaisesRegex(ValueError,'效能.*上界'):
            dsh_simulation.apply(world,value,'30分钟',require_fire_ledger=True)

    def test_changing_footprint_in_a_result_cannot_raise_the_bound(self):
        world,value,target=fixture();losses(world,value,target,239)
        next(r for r in value['unit_updates'] if r['unit']==target['name'])['formation']['dispersion_km2']=.001
        with self.assertRaisesRegex(ValueError,'展开面积'):
            dsh_simulation.apply(world,value,'30分钟',require_fire_ledger=True)

    def test_air_and_capture_receipts_are_counted_once_and_stale_air_does_not_exempt_losses(self):
        from gentactix import fire_effect_bounds as bounds
        world,value,target=fixture();after=copy.deepcopy(world);name=target['name']
        after['mission']['turn']+=1;unit=after['blue_units'][0]
        unit['personnel']['casualties']+=30;unit['personnel']['current']-=30
        after['campaign']={'turn':after['mission']['turn'],'execution_source':'dsh_model_estimate','actors':{name:{'captured_this_turn':4}}}
        after['air_operations']={'last_turn':after['mission']['turn'],'missions':[
            dict(target=name,personnel_effect=n,turn=after['mission']['turn'],source='dsh_model_estimate',status='returned',
                 target_turn_effects={'air_casualties':6}) for n in (2,4)]}
        receipt=bounds.validate(world,after,value,value['fire_ledger'])
        row=next(r for r in receipt['units'] if r['unit']==name)
        self.assertEqual((row['air_casualties'],row['captured'],row['ground_casualties']),(6,4,20))
        after['air_operations']['last_turn']-=1
        with self.assertRaisesRegex(ValueError,'效能.*上界'):bounds.validate(world,after,value,value['fire_ledger'])

    def test_multiple_attackers_share_one_target_budget_and_one_fractional_carry(self):
        from gentactix import fire_effect_bounds as bounds
        world,value,target=fixture();after=copy.deepcopy(world);name=target['name']
        world['blue_units'][0]['formation']['combat_damage_remainder']=.75
        row=copy.deepcopy(value['fire_ledger']['units'][0]);row['unit']=world['red_units'][0]['name']+' second'
        actor=copy.deepcopy(world['red_units'][0]);actor['name']=row['unit'];world['red_units'].append(actor)
        value['orders'].append(dict(unit=actor['name'],action='bombard',target=name))
        value['resource_ledger']['units'][0]['spent']['shells']=12
        value['resource_ledger']['units'].append(dict(unit=actor['name'],spent={'shells':12}))
        ledger=copy.deepcopy(value['fire_ledger']);ledger['units'].append(row)
        after['red_units'].append(copy.deepcopy(actor));after['mission']['turn']+=1
        receipt=bounds.validate(world,after,value,ledger);row=next(r for r in receipt['units'] if r['unit']==name)
        self.assertEqual(row['ground_maximum'],math.floor(24*1.5/math.sqrt(3)+.75))
        self.assertEqual(len(row['contributions']),2)

    def test_shared_formulas_use_round_half_up_and_reject_text_bindings(self):
        from gentactix import fire_process
        self.assertEqual(fire_process.formula_value('direct_attempts',committed=1,engaged_fraction=.5,rounds_per_min=1,direct_cycle_s=60),1)
        with self.assertRaises(ValueError):fire_process.formula_value('indirect_power',shells='24')

    def test_registered_direct_parameters_are_used_and_unknown_versions_are_not_silently_certified(self):
        from gentactix import combat_effects,fire_effect_bounds as bounds
        world,value,target=fixture();after=copy.deepcopy(world);after['mission']['turn']+=1
        value['orders'][0]['action']='fire';value['resource_ledger']['units'][0]['spent']={}
        ledger=copy.deepcopy(value['fire_ledger']);ledger['units'][0]['action']='fire'
        baseline=bounds.validate(world,after,value,ledger)
        ref=combat_effects.reference(world);ref['direct_fire']['hit_probability']*=2
        ref['definition_hash']=combat_effects.digest({k:v for k,v in ref.items() if k!='definition_hash'});world['combat_reference']=ref
        higher=bounds.validate(world,after,value,ledger)
        a=next(r for r in baseline['units'] if r['unit']==target['name'])
        b=next(r for r in higher['units'] if r['unit']==target['name'])
        self.assertGreater(b['ground_maximum'],a['ground_maximum'])
        ref['version']='unregistered-model';ref['definition_hash']=combat_effects.digest({k:v for k,v in ref.items() if k!='definition_hash'})
        with self.assertRaisesRegex(ValueError,'未支持'):bounds.validate(world,after,value,ledger)

    def test_legacy_estimates_without_a_fire_receipt_do_not_claim_new_effect_verification(self):
        from verify_fire_process import FireProcessTests
        probe=FireProcessTests();probe.setUp();value=probe.shot();value.pop('fire_ledger')
        after=dsh_simulation.apply(probe.world,value,'30分钟')
        self.assertNotIn('effect_admission',after['dsh_execution'])

    def test_readonly_observation_keeps_the_current_bound_distinct_from_calibration(self):
        from backend import afsim_state
        world,value,target=fixture();losses(world,value,target,10)
        after=dsh_simulation.apply(world,value,'30分钟',require_fire_ledger=True)
        session=dict(id='a'*12,war_state=after,turn_count=1,time_step='30分钟',execution_backend='narrative')
        row=next(r for r in afsim_state.observation(session)['units'] if r['name']==target['name'])
        self.assertEqual(row['effect_constraint']['ground_casualties'],10)
        self.assertFalse(row['effect_constraint']['calibration_proven'])
        self.assertNotIn('contributions',row['effect_constraint'])
        after['dsh_execution']['effect_admission']['turn']=0
        stale=afsim_state.observation(session)
        self.assertTrue(all('effect_constraint' not in r for r in stale['units']))

    def test_preview_returns_the_bound_and_normal_retry_reuses_feedback_without_changing_the_world(self):
        from backend import turn_preview
        world,bad,target=fixture();losses(world,bad,target,239);good=copy.deepcopy(bad);losses(world,good,target,10)
        session=dict(id='a'*12,war_state=world,turn_count=0,time_step='30分钟',execution_backend='narrative')
        before=copy.deepcopy(session);ctx=turn_preview.context(session,None,operation_id='effect-test',fixed_orders=bad['orders'])
        rejected=turn_preview.execute(ctx,dict(tool=turn_preview.TOOL,args=dict(candidate=bad)))
        self.assertFalse(rejected['ok']);self.assertIn('上界',rejected['error'])
        with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,good]) as model:
            result,_,_=dsh_simulation.advance(session,None,None,fixed_orders=bad['orders'])
        self.assertEqual(model.call_count,2);self.assertIn('上界',model.call_args_list[1].args[0]);self.assertEqual(session,before)
        self.assertEqual(result['updated_state']['blue_units'][0]['personnel']['casualties'],10)


if __name__=='__main__':unittest.main(verbosity=2)
