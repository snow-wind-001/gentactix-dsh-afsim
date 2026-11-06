"""WSF numerical serialization must retain tiny accumulated balances."""
import copy
import unittest
from backend import afsim_combined,afsim_rules,afsim_campaign


class NumericLiteralTests(unittest.TestCase):
    def test_small_carry_never_uses_the_rejected_integer_exponent_token(self):
        for formatter in (afsim_combined.n,afsim_rules.number,afsim_campaign.n):
            with self.subTest(formatter=formatter.__module__):
                value=formatter(3e-12)
                self.assertNotRegex(value,r'[eE]')
                self.assertEqual(float(value),3e-12)

    def test_precision_and_finite_guards_are_preserved(self):
        for value in (0,1,-.00000003,1e8,.123456789012345):
            actual=afsim_combined.n(value)
            self.assertRegex(actual,r'^-?\d+(?:\.\d+)?$')
            self.assertEqual(float(actual),float(format(value,'.12g')))
        for invalid in (True,float('nan'),float('inf'),'3e-12'):
            with self.subTest(value=repr(invalid)),self.assertRaises(ValueError):afsim_combined.n(invalid)

    def test_each_model_retains_its_existing_significant_digits(self):
        from backend.afsim_literals import number
        for value in (3e-12,-3e-8,.12345678901234567,1e20):
            for formatter,precision in ((afsim_combined.n,12),(afsim_campaign.n,15),(afsim_rules.number,15)):
                with self.subTest(value=value,precision=precision):
                    self.assertEqual(float(formatter(value)),float(format(value,f'.{precision}g')))
            self.assertEqual(float(number(value)),value)

    def test_saved_partition_carries_compile_without_erasing_the_balance(self):
        from tools.qa.historical_crossing_fixture import inputs
        from verify_formation_parts import partition_input
        from gentactix import historical_operations as ho
        from backend import afsim_world
        snapshot,params=inputs();params['partitions']=partition_input(params)
        world=ho.initial(snapshot,params)
        unit=next(u for u in world['red_units'] if u.get('formation_part'))
        unit['formation']['partition_noncombat_remainder']=3e-12
        unit['formation']['combat_damage_remainder']=3e-12
        frozen=copy.deepcopy(world)
        scene=afsim_world.compile_scene(world,[],1800,native_rules=True)
        self.assertIn('=0.000000000003;',scene['script'])
        self.assertNotRegex(scene['script'],r'\b\d+(?:\.\d*)?[eE][+-]\d+')
        self.assertEqual(world,frozen)

    def test_crossing_rate_and_progress_use_the_same_safe_serialization(self):
        from backend import afsim_crossing,afsim_crossing_network
        from verify_crossing_network import fixture
        world=fixture()['initial_state'];world['combined_arms']['bridge']['crossing_model']['throughput_work_per_hour']=.0108
        scene={'seconds':1800}
        script=afsim_crossing.functions(scene,world)
        self.assertIn('actor.AuxDataDouble("ca_cross_rate")',script)
        self.assertIn('0.000003', '\n'.join(afsim_crossing_network.actor_setup(world,{}, {},'p')))
        task={'status':'queued','required_work':10,'served_work':3e-12}
        setup='\n'.join(afsim_crossing.setup_actor('p',{'crossing':task},{},None))
        self.assertIn('0.000000000003',setup)
        self.assertNotRegex(setup,r'\b\d+(?:\.\d*)?[eE][+-]\d+')


if __name__=='__main__':unittest.main()
