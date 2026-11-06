"""Whole Native model binding contracts; no release admission or host physics."""
import copy
import unittest

from backend import afsim_continuous_motion as cm, afsim_rules, afsim_world
from gentactix import missions, motion_state
from verify_continuous_motion import world


def compile_world(value=None, orders=None, seconds=300):
    value = value or world()
    unit = value['red_units'][0]
    orders = orders or [{'unit':unit['name'],'action':'move','lat':unit['lat']+.005,
                        'lng':unit['lng'],'intent_id':'e'*32}]
    plain = {team+'_units':copy.deepcopy(value[team+'_units']) for team in ('red','blue')}
    scene = afsim_world.compile_scene(plain,orders,seconds)
    return value, orders, scene, afsim_rules.compile_model(scene,value,orders)


class ContinuousMotionIntegrationTests(unittest.TestCase):
    def test_combined_model_binds_all_entities_to_same_native_component(self):
        value,orders,scene,model = compile_world()
        component = model['continuous_motion']
        self.assertEqual(set(component['controls']),set(scene['entities']))
        self.assertEqual(component['version'],cm.VERSION)
        self.assertEqual(component['controls'],cm.inputs(value,orders,scene['entities']))
        self.assertIn('GtxCMSettle(',model['script'])
        self.assertIn('GTXCMODEL|'+component['token'],model['script'])
        self.assertEqual(model['script'].count('script void GtxSuppressionDecay('),1)

    def test_new_model_does_not_repeat_legacy_pause_and_end_round_costs(self):
        _,_,_,model = compile_world()
        script = model['script']
        self.assertNotIn('bool fuelLimited0',script)
        self.assertNotIn('double pause0=',script)
        self.assertNotIn('Math.Ceil(mfGround0*',script)
        self.assertNotIn('GtxRound(mfGround0*',script)

    def test_continuing_intent_uses_remaining_wait_in_parent_c2_model(self):
        value=world();u=value['red_units'][0]
        order={'unit':u['name'],'action':'move','lat':u['lat']+.005,'lng':u['lng'],'intent_id':'e'*32}
        u['formation']['motion_task']=cm.intent(u,order,30000)
        u['formation']['motion_task'].update(status='moving',wait_remaining_ms=0,speed_mps=.2)
        _,_,_,model=compile_world(value,[order])
        component=model['continuous_motion']
        control=next(c for c in component['controls'].values() if c['name']==u['name'])
        self.assertEqual(control['task']['wait_remaining_ms'],0)
        self.assertIn('SetAuxData("ca_delay_s",(double)(0))',model['script'])

    def test_shared_component_exposes_setup_and_receipts_without_own_clock(self):
        value,orders,scene,_=compile_world()
        component=cm.compile_process(cm.inputs(value,orders,scene['entities']),300,shared=True)
        self.assertTrue(component['setup_lines'])
        self.assertTrue(component['receipt_lines'])
        self.assertNotIn('execute at_time', '\n'.join(component['setup_lines']))
        self.assertNotIn('ca_live_strength_ratio', '\n'.join(component['setup_lines']))
        self.assertNotIn('script void GtxSuppressionDecay(',component['functions'])

    def test_schedule_uses_the_physical_stock_in_the_lower_compiler(self):
        from gentactix import historical_operations as ho
        from tools.qa.historical_operational_fixture import inputs
        from verify_support_dynamics import config
        from verify_continuous_motion import CONFIG
        from verify_split_supply import config as split_config
        from verify_supply_schedule import config as schedule_config
        source,params=inputs()
        params.update(movement_feedback=copy.deepcopy(CONFIG),
            fire_dynamics={'version':'live-footprint-density-2','assumption':CONFIG['assumption']},
            support_dynamics=config(),supply_distribution=split_config(),supply_schedule=schedule_config())
        value=ho.initial(source,params);u=value['red_units'][0]
        _,_,_,model=compile_world(value,[{'unit':u['name'],'action':'resupply'}])
        self.assertIn('GTXSCHEDULE2|',model['script'])
        self.assertNotIn('"sl_food"',model['script'])
        self.assertIn('GtxCNReceiveFood(',model['script'])

    def test_public_execution_stays_closed_until_whole_chain_is_verified(self):
        value=world()
        with self.assertRaisesRegex(ValueError,'整局执行链尚未验收'):
            afsim_world.compile_scene(value,[],300,native_rules=True)

    def support_receipt(self):
        from verify_continuous_motion_native import NativeContinuousMotionTests
        text,old=NativeContinuousMotionTests().receipt()
        model=cm.compile_process(old['controls'],300,shared=True)
        lines=[]
        for line in text.replace(old['token'],model['token']).splitlines():
            if line.startswith('GTXCMOTION|'):
                p=line.split('|');k=2+cm.INTEGER_FIELDS.index('fuel_microliters')
                p[k]=str(int(p[k])-5000000);line='|'.join(p)
            lines.append(line)
        lines += ['GTXCMSUPPORT|'+identity+'|5000000' for identity in model['controls']]
        if model.get('fuel_receipt_revision')==2:
            lines += ['GTXCMRECEIVED|'+identity+'|0' for identity in model['controls']]
        return '\n'.join(lines),model

    def test_convoy_fuel_is_separate_from_distance_and_balances_total_stock(self):
        text,model=self.support_receipt();saved=copy.deepcopy(model)
        rows=cm.parse(text,model)
        self.assertEqual(model,saved)
        for row in rows.values():
            self.assertEqual(row['fuel_spent_microliters'],0)
            self.assertEqual(row['support_fuel_spent_microliters'],5000000)

    def test_missing_duplicate_or_unbalanced_convoy_receipt_is_rejected(self):
        text,model=self.support_receipt()
        row=next(line for line in text.splitlines() if line.startswith('GTXCMSUPPORT|'))
        for bad in [text.replace(row,''),text+'\n'+row,text.replace(row,row.rsplit('|',1)[0]+'|4000000'),
                    text.replace(row,row.rsplit('|',1)[0]+'|-1')]:
            with self.subTest(case=bad[-25:]),self.assertRaises(ValueError):cm.parse(bad,model)

    def test_compact_execution_observation_preserves_native_time_and_stock_units(self):
        from backend import afsim_state
        execution={'turn':1,'continuous_motion':{'elapsed_ms':300000,'waiting_ms':30000,
            'moving_ms':270000,'fuel_spent_microliters':210795,
            'support_fuel_spent_microliters':5000000,'source':'afsim_native_estimate',
            'fuel_unit':'microliter'}}
        saved=copy.deepcopy(execution)
        row=afsim_state._execution_observation(execution)
        self.assertEqual(row['continuous_motion'],execution['continuous_motion'])
        row['continuous_motion']['waiting_ms']=0
        self.assertEqual(execution,saved)


if __name__=='__main__':
    unittest.main()
