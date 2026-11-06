"""Configured suppression recovery cannot silently stall a quiet formation."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_operations as ho,missions,fire_process
from tools.qa.boundary_lifecycle_fixture import inputs
from verify_campaign_plan_backends import proposal


class QuietSuppressionTests(unittest.TestCase):
    def setUp(self):
        source,parameters=inputs()
        parameters['actors']['ww2.cn.division159']['formation']['suppression']=65
        self.source,self.parameters=source,parameters
        self.world=ho.initial(source,parameters)
        self.unit=next(u for u in self.world['red_units'] if u['formation']['suppression']==65)

    def candidate(self,suppression):
        value=proposal(self.world)
        formation=next(r for r in value['unit_updates'] if r['unit']==self.unit['name'])['formation']
        if suppression is None:formation.pop('suppression',None)
        else:formation['suppression']=suppression
        return value

    def apply(self,value,step='15分钟'):
        from backend import dsh_simulation
        with patch.object(missions,'advance',side_effect=AssertionError('No host effect executor')):
            return dsh_simulation.apply(self.world,value,step)

    def test_real_stale_threshold_is_rejected_without_repair_or_input_mutation(self):
        value=self.candidate(65);old=copy.deepcopy((self.world,value))
        with self.assertRaisesRegex(ValueError,'压制.*65.*900.*60'):
            self.apply(value)
        self.assertEqual((self.world,value),old)

    def test_omitting_passive_recovery_cannot_keep_the_old_threshold(self):
        value=self.candidate(None);old=copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,'压制|suppression'):
            self.apply(value)
        self.assertEqual(value,old)

    def test_explicit_recovery_admits_model_state_and_preserves_estimate_source(self):
        value=self.candidate(60);old=copy.deepcopy((self.world,value))
        after=self.apply(value)
        self.assertEqual(next(u for u in after['red_units'] if u['name']==self.unit['name'])['formation']['suppression'],60)
        self.assertEqual(after['dsh_execution']['effects_source'],'dsh_model_estimate')
        self.assertEqual((self.world,value),old)

    def test_full_recovery_never_becomes_negative(self):
        self.parameters['clock']['time_step']='6小时'
        self.world=ho.initial(self.source,self.parameters)
        self.unit=next(u for u in self.world['red_units'] if u['formation']['suppression']==65)
        after=self.apply(self.candidate(0),'6小时')
        self.assertEqual(next(u for u in after['red_units'] if u['name']==self.unit['name'])['formation']['suppression'],0)

    def test_targeted_actor_does_not_acquire_a_guessed_quiet_fire_outcome(self):
        value=self.candidate(65);attacker=self.world['blue_units'][0]['name']
        next(r for r in value['orders'] if r['unit']==attacker).update(action='fire',target=self.unit['name'])
        self.assertIsNone(fire_process.validate(self.world,copy.deepcopy(self.world),value,900))

    def test_prompt_explains_quiet_recovery_and_required_explicit_update(self):
        text=fire_process.instruction(self.world)
        self.assertIn('未被本轮火力命令指向',text)
        self.assertIn('suppression',text)
        self.assertIn('1800',text)


if __name__=='__main__':unittest.main()
