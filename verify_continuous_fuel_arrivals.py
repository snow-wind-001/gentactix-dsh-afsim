"""Incoming Native fuel must share one physical stock and explicit gross flow."""
import copy
import unittest

from backend import afsim_continuous_motion as cm
from gentactix import motion_state
from verify_continuous_motion_integration import compile_world


class ContinuousFuelArrivalTests(unittest.TestCase):
    def test_fractional_incoming_fuel_is_a_gross_credit_not_negative_spending(self):
        before={'formation':{'fatigue':60,'fatigue_carry_ticks':0,
                            'fuel_liters':1,'fuel_credit_microliters':200000}}
        after=copy.deepcopy(before);after['formation'].update(fuel_liters=1,fuel_credit_microliters=50000)
        snapshot=copy.deepcopy((before,after))
        cm.check_fuel(before,after,400000,received_microliters=250000)
        self.assertEqual((before,after),snapshot)
        with self.assertRaises(ValueError):cm.check_fuel(before,after,400001,received_microliters=250000)
        for value in [True,-1,1.5]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                cm.check_fuel(before,after,400000,received_microliters=value)

    def receipt(self):
        from verify_continuous_motion_integration import ContinuousMotionIntegrationTests
        text,model=ContinuousMotionIntegrationTests().support_receipt()
        lines=[]
        for line in text.splitlines():
            if line.startswith('GTXCMOTION|'):
                p=line.split('|');k=2+cm.INTEGER_FIELDS.index('fuel_microliters')
                p[k]=str(int(p[k])+7000000);line='|'.join(p)
            if line.startswith('GTXCMRECEIVED|'):continue
            lines.append(line)
        lines += ['GTXCMRECEIVED|'+identity+'|7000000' for identity in model['controls']]
        return '\n'.join(lines),model

    def test_native_receipts_separate_incoming_motion_and_convoy_fuel(self):
        text,model=self.receipt();saved=copy.deepcopy(model);rows=cm.parse(text,model)
        self.assertEqual(model,saved)
        for identity,row in rows.items():
            self.assertEqual(row['fuel_received_microliters'],7000000)
            self.assertEqual(row['fuel_spent_microliters'],0)
            self.assertEqual(row['support_fuel_spent_microliters'],5000000)
            self.assertEqual(row['fuel_microliters'],motion_state.fuel_load({'formation':model['controls'][identity]['formation']})+2000000)

    def test_missing_duplicate_wrong_or_fractional_arrival_cannot_balance_by_netting(self):
        text,model=self.receipt();line=next(x for x in text.splitlines() if x.startswith('GTXCMRECEIVED|'))
        for bad in [text.replace(line,''),text+'\n'+line,text.replace(line,line.rsplit('|',1)[0]+'|6000000'),
                    text.replace(line,line.rsplit('|',1)[0]+'|-1'),text.replace(line,line.rsplit('|',1)[0]+'|7.5')]:
            with self.subTest(ending=bad[-25:]),self.assertRaises(ValueError):cm.parse(bad,model)

    def test_existing_resupply_compiles_into_native_credit_without_a_new_allocator(self):
        value,_,_,_=compile_world();u=value['red_units'][0]
        _,_,_,model=compile_world(value,[{'unit':u['name'],'action':'resupply'}])
        self.assertEqual(model['continuous_motion']['fuel_receipt_revision'],2)
        self.assertTrue('GtxCMReceiveFuel(' in model['script'])
        self.assertTrue('GTXCMRECEIVED|' in model['script'])

    def test_depot_paid_convoy_fuel_has_an_explicit_global_balance(self):
        from backend import afsim_combined
        _,_,scene,model=compile_world()
        motion={identity:{'fuel_microliters':motion_state.fuel_load({'formation':c['formation']}),
            'fuel_spent_microliters':0,'support_fuel_spent_microliters':0}
            for identity,c in model['continuous_motion']['controls'].items()}
        pools=copy.deepcopy(model['before_combined']['depots']);pools['red']['fuel_liters']-=3
        opening=copy.deepcopy((motion,pools))
        flow=afsim_combined.validate_motion_fuel_totals(model,scene,motion,pools,{'red':3000000,'blue':0})
        self.assertEqual(flow['red']['depot_support_spent_microliters'],3000000)
        self.assertEqual((motion,pools),opening)
        for paid in [{'red':0,'blue':0},{'red':3000000},{'red':-1,'blue':0}]:
            with self.subTest(paid=paid),self.assertRaises(ValueError):
                afsim_combined.validate_motion_fuel_totals(model,scene,motion,pools,paid)


if __name__=='__main__':
    unittest.main()
