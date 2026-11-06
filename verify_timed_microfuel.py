"""Chronological physical fuel receipts; no allocation or host simulation."""
import copy
import unittest

TIMES=[(55,'delivery'),(120,'delivery'),(300,'settlement')]


def ledger():
    return {'version':'timed-microfuel-1','unit':'microliter','events':[
        dict(seconds=55,kind='delivery',opening_microliters=300000,received_microliters=1000000,
             movement_spent_microliters=100000,support_spent_microliters=0,closing_microliters=1200000),
        dict(seconds=120,kind='delivery',opening_microliters=1200000,received_microliters=2000000,
             movement_spent_microliters=50000,support_spent_microliters=200000,closing_microliters=2950000),
        dict(seconds=300,kind='settlement',opening_microliters=2950000,received_microliters=0,
             movement_spent_microliters=50000,support_spent_microliters=0,closing_microliters=2900000)]}


class TimedMicrofuelTests(unittest.TestCase):
    def test_exact_fractional_gross_timeline_is_readonly(self):
        from gentactix import timed_fuel as tf
        value=ledger();saved=copy.deepcopy(value)
        result=tf.validate(300000,value,TIMES,expected_received_microliters=[1000000,2000000,0])
        self.assertEqual(value,saved)
        self.assertEqual(result['received_microliters'],3000000)
        self.assertEqual(result['movement_spent_microliters'],200000)
        self.assertEqual(result['support_spent_microliters'],200000)
        self.assertEqual(result['closing_microliters'],2900000)

    def test_future_arrival_cannot_pay_preceding_interval_even_if_net_balances(self):
        from gentactix import timed_fuel as tf
        value=ledger();row=value['events'][0]
        row.update(movement_spent_microliters=400000,received_microliters=1300000)
        with self.assertRaisesRegex(ValueError,'到货前|透支'):tf.validate(300000,value,TIMES)

    def test_missing_duplicate_wrong_clock_and_forged_carry_are_rejected(self):
        from gentactix import timed_fuel as tf
        for kind in ['missing','duplicate','clock','carry','settlement_credit']:
            value=ledger()
            if kind=='missing':value['events'].pop(0)
            if kind=='duplicate':value['events'].insert(0,copy.deepcopy(value['events'][0]))
            if kind=='clock':value['events'][0]['seconds']=54
            if kind=='carry':value['events'][1]['opening_microliters']+=1
            if kind=='settlement_credit':value['events'][-1]['received_microliters']=1;value['events'][-1]['closing_microliters']+=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):tf.validate(300000,value,TIMES)

    def test_units_versions_boolean_fractional_negative_and_unknown_fields_are_rejected(self):
        from gentactix import timed_fuel as tf
        for field,bad in [('received_microliters',True),('opening_microliters',.3),
                          ('movement_spent_microliters',-1),('closing_microliters',float('nan'))]:
            value=ledger();value['events'][0][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):tf.validate(300000,value,TIMES)
        for field,bad in [('unit','liter'),('version','unknown')]:
            value=ledger();value[field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):tf.validate(300000,value,TIMES)
        value=ledger();value['events'][0]['extra']=0
        with self.assertRaises(ValueError):tf.validate(300000,value,TIMES)

    def test_independent_arrival_receipt_rejects_locally_balanced_invented_fuel(self):
        from gentactix import timed_fuel as tf
        value=ledger();value['events'][0]['received_microliters']+=1
        for i,row in enumerate(value['events']):
            if i:row['opening_microliters']+=1
            row['closing_microliters']+=1
        tf.validate(300000,value,TIMES)
        with self.assertRaisesRegex(ValueError,'到货'):
            tf.validate(300000,value,TIMES,expected_received_microliters=[1000000,2000000,0])

    def test_expected_times_require_a_unique_terminal_settlement(self):
        from gentactix import timed_fuel as tf
        for bad in [[],[(55,'settlement'),(300,'settlement')],[(55,'delivery'),(55,'delivery'),(300,'settlement')],
                    [(300,'delivery')],[(True,'delivery'),(300,'settlement')]]:
            with self.subTest(times=bad),self.assertRaises(ValueError):tf.validate_times(bad,300)
        self.assertEqual(tf.validate_times([(300,'delivery'),(300,'settlement')],300),[(300,'delivery'),(300,'settlement')])
        self.assertEqual(tf.validate_times([(1.001,'delivery'),(300,'settlement')],300),[(1.001,'delivery'),(300,'settlement')])
        with self.assertRaises(ValueError):tf.validate_times([(1.0011,'delivery'),(300,'settlement')],300)


class TimedNativeBindingTests(unittest.TestCase):
    def model(self):
        from backend import afsim_continuous_motion as cm
        from verify_continuous_motion_integration import ContinuousMotionIntegrationTests
        text,old=ContinuousMotionIntegrationTests().support_receipt()
        value=cm.compile_process(old['controls'],300,shared=True,fuel_event_times=TIMES)
        return text.replace(old['token'],value['token']),value

    def test_timed_binding_is_explicit_and_wake_refresh_does_not_schedule(self):
        from backend import afsim_continuous_motion as cm
        text,model=self.model()
        self.assertEqual(model['timed_fuel_revision'],'timed-microfuel-1')
        self.assertIn('GtxCMUpdate(PLATFORM,true,false)', '\n'.join(cm.callbacks(timed=True)))
        self.assertIn('GTXCMTIMEDFUEL|',model['functions'])
        old=cm.compile_process(model['controls'],300,shared=True)
        self.assertNotIn('timed_fuel_revision',old)
        self.assertNotEqual(model['token'],old['token'])

    def receipt(self):
        from backend import afsim_continuous_motion as cm
        from gentactix import motion_state
        text,model=self.model();lines=[]
        for identity,c in model['controls'].items():
            opening=motion_state.fuel_load({'formation':c['formation']})
            for seconds,kind in TIMES:
                spent=5000000 if kind=='settlement' else 0
                lines.append(f'GTXCMTIMEDFUEL|{identity}|{seconds}|{kind}|{opening}|0|0|{spent}|{opening-spent}')
                opening-=spent
        complete=text+'\n'+'\n'.join(lines)
        return complete,model,lines

    def test_timed_receipts_are_required_and_match_cumulative_physical_counters(self):
        from backend import afsim_continuous_motion as cm
        complete,model,lines=self.receipt()
        saved=copy.deepcopy(model)
        rows=cm.parse(complete,model)
        self.assertEqual(model,saved)
        self.assertTrue(all(len(r['fuel_timeline']['events'])==3 for r in rows.values()))
        for bad in [complete.split('\nGTXCMTIMEDFUEL|',1)[0],complete+'\n'+lines[0]]:
            with self.assertRaises(ValueError):cm.parse(bad,model)
        # Preserve interval totals but claim another source for the same expense.
        changed=complete.replace('|0|0|5000000|','|0|1|4999999|')
        with self.assertRaises(ValueError):cm.parse(changed,model)

    def test_whole_liter_native_arrivals_cannot_hide_fractional_event_transfers(self):
        from backend import afsim_continuous_motion as cm
        complete,model,_=self.receipt();lines=[];credits={}
        for line in complete.splitlines():
            p=line.split('|')
            if p[0]=='GTXCMOTION':
                k=2+cm.INTEGER_FIELDS.index('fuel_microliters');p[k]=str(int(p[k])+2000000)
            elif p[0]=='GTXCMRECEIVED':p[2]='2000000'
            elif p[0]=='GTXCMTIMEDFUEL':
                prior=credits.get(p[1],0);got=1000001 if float(p[2])==55 else 999999 if float(p[2])==120 else 0
                p[4]=str(int(p[4])+prior);p[5]=str(got);p[8]=str(int(p[8])+prior+got);credits[p[1]]=prior+got
            lines.append('|'.join(p))
        with self.assertRaisesRegex(ValueError,'整升|到货'):cm.parse('\n'.join(lines),model)


if __name__=='__main__':unittest.main()
