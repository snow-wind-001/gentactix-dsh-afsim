"""Native code layout bounds interpreter frames without changing equations."""
import copy
import hashlib
import unittest

from backend import afsim_world


class SettlementLayoutTests(unittest.TestCase):
    @staticmethod
    def lower(header,actors,tail,**kwargs):
        from backend.afsim_script_layout import lower_settlement
        return lower_settlement(header,actors,tail,**kwargs)

    def sample(self):
        return ([' WsfPlatform hub=WsfSimulation.FindPlatform("hub");',' double stock=10; int survivors=0; bool available=true;'],
                [[' double current0=3; double private0=2; stock=stock-private0; survivors=survivors+1;',
                  ' writeln("current0 stock // not code",current0);'],
                 [' double current1=4; if (available) { stock=stock-1; } survivors=survivors+1;']],
                [' writeln("result",stock,survivors,current0,current1);'])

    def test_small_layout_is_left_byte_exact(self):
        args=self.sample();saved=copy.deepcopy(args)
        self.assertIsNone(self.lower(*args));self.assertEqual(args,saved)

    def test_shared_stock_and_survivors_keep_type_reset_and_order(self):
        prefix,body,meta=self.lower(*self.sample(),max_flat_locals=0)
        declarations='\n'.join(prefix);execution='\n'.join(body)
        self.assertIn('double gtx_settlement_stock=0;',declarations)
        self.assertIn('int gtx_settlement_survivors=0;',declarations)
        self.assertIn('bool gtx_settlement_available=false;',declarations)
        self.assertLess(execution.index('gtx_settlement_stock=10'),execution.index('GtxSettlementActor0('))
        self.assertLess(execution.index('GtxSettlementActor0('),execution.index('GtxSettlementActor1('))
        self.assertIn('gtx_settlement_stock=gtx_settlement_stock-private0',declarations)
        self.assertEqual(meta['actor_count'],2)

    def test_tail_counts_export_but_actor_private_values_stay_local(self):
        prefix,body,_=self.lower(*self.sample(),max_flat_locals=0);text='\n'.join(prefix)
        globals=text.split('end_script_variables')[0]
        self.assertIn('double gtx_settlement_current0=0;',globals)
        self.assertNotIn('private0',globals);self.assertIn('double private0=2;',text)
        self.assertIn('gtx_settlement_current1','\n'.join(body))

    def test_strings_and_comments_are_not_rewritten_as_variables(self):
        args=self.sample();args[1][0].append(' // current0 stock keep this comment')
        prefix,_,_=self.lower(*args,max_flat_locals=0);text='\n'.join(prefix)
        self.assertIn('"current0 stock // not code"',text)
        self.assertIn('// current0 stock keep this comment',text)

    def test_cross_actor_platform_lifetime_is_explicitly_rejected(self):
        header,actors,tail=self.sample();actors[0].append(' WsfPlatform leaked=WsfSimulation.FindPlatform("unit");');tail.append(' writeln(leaked.Latitude());')
        with self.assertRaisesRegex(ValueError,'平台引用'):
            self.lower(header,actors,tail,max_flat_locals=0)

    def test_scratch_namespace_and_ambiguous_declarations_are_rejected(self):
        header,actors,tail=self.sample();header.append(' double gtx_settlement_stock=5;')
        with self.assertRaisesRegex(ValueError,'命名空间'):self.lower(header,actors,tail,max_flat_locals=0)
        header,actors,tail=self.sample();actors[1].append(' double current0=9;')
        with self.assertRaisesRegex(ValueError,'重复'):self.lower(header,actors,tail,max_flat_locals=0)

    def test_four_small_physical_profiles_keep_previous_wsf_bytes(self):
        from verify_fire_density import world
        gold={(False,False):'6f4a123a2589a22887c228fd2f57deb969c715655fbf89435ecb67056fb3ccc2',
              (False,True):'f2678dd60eb267eebcefcbbdc4eecb679a30a6a451cfca87bf747758fe707abd',
              (True,False):'3c6240a6fd2007b12dcff44f7baf6abccdfa53190c4082c6ef677e26ab850e54',
              (True,True):'d06c83af9a0136063122064cd85dda73ed4ea044086ddd9d485dcdb22167455a'}
        for (selected,accounting),expected in gold.items():
            w=world(selected=selected,accounting=accounting);orders=[dict(unit=u['name'],action='hold')for team in ['red','blue']for u in w[team+'_units']]
            scene=afsim_world.compile_scene(w,orders,1800,native_rules=True)
            self.assertEqual(hashlib.sha256(scene['script'].encode()).hexdigest(),expected)
            self.assertNotIn('settlement_layout',scene['native_model'])

    def test_large_campaign_compiles_bounded_frames_and_binds_layout(self):
        from tools.qa.campaign_capacity_fixture import inputs,configuration
        from gentactix import historical_operations as ho,synthetic_history as sh,missions
        snapshot,params=inputs();binding=ho.definition(snapshot,params)['historical_calculation']
        w=missions.from_definition(sh.definition(binding,configuration(binding,112,16)));saved=copy.deepcopy(w)
        orders=[dict(unit=u['name'],action='move',lat=u['lat']+.0002,lng=u['lng'])for team in ['red','blue']for u in w[team+'_units']]
        scene=afsim_world.compile_scene(w,orders,1800,native_rules=True);layout=scene['native_model'].get('settlement_layout')
        self.assertIsNotNone(layout,'Large native settlement must not retain a10000-local callback')
        self.assertEqual(layout['version'],'actor-settlement-frames-1');self.assertEqual(layout['actor_count'],128)
        self.assertLess(layout['max_actor_locals'],256);self.assertGreater(layout['flat_local_declarations'],4096)
        self.assertIn('GtxSettlementActor127(hub);',scene['script']);self.assertEqual(w,saved)
        self.assertIn('GTXMODEL|'+scene['native_model']['input_digest'],scene['script'])

    @staticmethod
    def scheduled_world(step='30分钟'):
        from tools.qa.campaign_capacity_fixture import inputs,configuration
        from gentactix import historical_operations as ho,synthetic_history as sh,missions
        from verify_support_dynamics import config as nutrition
        from verify_supply_schedule import config as scheduled
        from verify_movement_feedback import CONFIG
        snapshot,params=inputs()
        params.update(support_dynamics=nutrition(),supply_schedule=scheduled(),movement_feedback=copy.deepcopy(CONFIG))
        params['clock']['time_step']=step
        binding=ho.definition(snapshot,params)['historical_calculation']
        return missions.from_definition(sh.definition(binding,configuration(binding,112,16)))

    def test_large_scheduled_supply_and_mobility_keep_native_models(self):
        w=self.scheduled_world()
        orders=[dict(unit=u['name'],action='hold')for team in ['red','blue']for u in w[team+'_units']]
        scene=afsim_world.compile_scene(w,orders,1800,native_rules=True)
        self.assertIn('settlement_layout',scene['native_model'])
        self.assertIn('supply_schedule',scene['native_model']);self.assertIn('support_dynamics',scene['native_model'])
        self.assertIn('movement_feedback',scene['native_model'])
        self.assertIn('GTXMOVEMENT|',scene['script'])

    @staticmethod
    def ferry_world():
        from verify_ferries import ferry_inputs
        from gentactix import historical_operations as ho,synthetic_history as sh,missions
        from tools.qa.campaign_capacity_fixture import configuration
        snapshot,params=ferry_inputs();params.pop('partitions')
        binding=ho.definition(snapshot,params)['historical_calculation']
        return missions.from_definition(sh.definition(binding,configuration(binding,64,64)))

    def test_large_crossing_and_ferry_keep_native_completion_receipts(self):
        w=self.ferry_world()
        orders=[dict(unit=u['name'],action='hold')for team in ['red','blue']for u in w[team+'_units']]
        scene=afsim_world.compile_scene(w,orders,60,native_rules=True)
        self.assertEqual(scene['native_model']['settlement_layout']['actor_count'],128)
        self.assertIn('GTXFERRY|',scene['script']);self.assertIn('GTXCROSS|',scene['script'])


if __name__=='__main__':unittest.main(verbosity=2)
