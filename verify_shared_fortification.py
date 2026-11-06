"""Shared paid-work contract regression; not whole-world runtime acceptance."""
import copy
import unittest
from gentactix import shared_fortification as work

CFG=dict(version='shared-fortification-work-1',gain_points_per_worker_hour=20,
    material_work_units_per_packet=120000,fatigue_per_work_hour=20,activity_food_factor=1.5,
    assumption='Explicit QA estimates; not historical tonnage or engineering efficiency.')

def state(**changes):
    return dict(version='shared-fortification-state-1',root_id='a'*64,root_committed=6000,
        committed=6000,site_id='b'*64,base_ticks=10000000,point_remainder=0,work_remainder=0,
        material_credit_work=0,material_credit_fraction=0,intent_id='c'*32,wait_remaining_ms=0,**changes)

def changed_state(**changes):
    value=state();value.update(changes);return value

def control(before=None,**changes):
    value=dict(entity_id='g00000000000000000001',configuration=copy.deepcopy(CFG),state=state()if before is None else copy.deepcopy(before),materials=16,current=6000,fortify=True,intent_id='c'*32,command_delay_ms=0);value.update(changes);return value

def receipt(after,*,elapsed=3600000,available=None,waited=0,productive=None,paid=120000*3600000,added=120000,reserved=1,materials=15,excess=0):
    return dict(version='shared-fortification-receipt-1',entity_id='g00000000000000000001',elapsed_ms=elapsed,waited_ms=waited,available_ms=elapsed-waited if available is None else available,productive_ms=float(elapsed-waited if productive is None else productive),paid_work_numerator=paid,work_added=added,packets_reserved=reserved,materials_after=materials,cap_excess_micro_work=excess,after=after)

class SharedContractTests(unittest.TestCase):
    def test_one_material_packet_has_same_capacity_for_different_roots(self):
        first=control(materials=1);second=control(changed_state(root_id='d'*64,root_committed=3000,committed=3000),materials=1,current=3000)
        self.assertEqual(work.material_balance(first),120000*3600000)
        self.assertEqual(work.material_balance(second),work.material_balance(first))
        self.assertNotIn('materials',first['state'])
    def test_full_hour_and_four_quarters_preserve_exact_state_and_materials(self):
        c=control();full=receipt(changed_state(base_ticks=30000000));self.assertTrue(work.check_segment(c,full));current=c
        for n in range(1,5):
            after=changed_state(base_ticks=10000000+n*5000000,material_credit_work=(4-n)*30000)
            r=receipt(after,elapsed=900000,paid=30000*3600000,added=30000,reserved=int(n==1),materials=15)
            self.assertTrue(work.check_segment(current,r));current=control(after,materials=15)
        self.assertEqual(current['state'],full['after'])
    def test_partial_work_reserves_material_before_whole_work_is_completed(self):
        c=control(materials=1,current=2000)
        after=changed_state(work_remainder=1800000,material_credit_work=119999,material_credit_fraction=1800000)
        r=receipt(after,elapsed=45,paid=1800000,added=0,materials=0)
        self.assertTrue(work.check_segment(c,r));self.assertEqual(work.material_balance(c)-work.material_balance(control(after,materials=0,current=2000)),1800000)
    def test_exhausted_material_cannot_carry_unfunded_fraction_into_a_later_delivery(self):
        c=control(changed_state(material_credit_work=3001),materials=0,current=2001)
        after=changed_state(base_ticks=10500166,point_remainder=4000)
        r=receipt(after,elapsed=270000,paid=3001*3600000,added=3001,reserved=0,materials=0,productive=3001*3600000/40020)
        self.assertTrue(work.check_segment(c,r))
        bad=copy.deepcopy(r);bad['after']['work_remainder']=1800000
        with self.assertRaises(ValueError):work.check_segment(c,bad)
        # A later explicit packet is an input to a separate interval, never retroactive.
        c=control(after,materials=1,current=2001)
        final=changed_state(base_ticks=10666833,point_remainder=2000,work_remainder=1800000,material_credit_work=118999,material_credit_fraction=1800000)
        self.assertTrue(work.check_segment(c,receipt(final,elapsed=90000,paid=1000*3600000+1800000,added=1000,materials=0)))
    def test_material_and_cap_stops_reduce_actual_work_time(self):
        c=control(changed_state(base_ticks=99000000),materials=1)
        after=changed_state(base_ticks=100000000,material_credit_work=114000)
        self.assertTrue(work.check_segment(c,receipt(after,paid=6000*3600000,added=6000,materials=0,productive=180000)))
        bad=receipt(after,paid=6000*3600000,added=6000,materials=0,productive=3600000)
        with self.assertRaisesRegex(ValueError,'工作时间'):work.check_segment(c,bad)
    def test_no_workers_or_no_materials_produce_no_free_progress(self):
        for c in [control(current=0),control(materials=0),control(changed_state(base_ticks=100000000))]:
            r=receipt(copy.deepcopy(c['state']),paid=0,added=0,reserved=0,materials=c['materials'],productive=0)
            with self.subTest(current=c['current'],materials=c['materials']):self.assertTrue(work.check_segment(c,r))
    def test_wait_is_carried_once_for_same_intent(self):
        before=changed_state(wait_remaining_ms=300000);c=control(before)
        after=changed_state(base_ticks=11666666,point_remainder=4000,material_credit_work=110000)
        r=receipt(after,elapsed=600000,waited=300000,paid=10000*3600000,added=10000)
        self.assertTrue(work.check_segment(c,r))
        bad=copy.deepcopy(r);bad['after']['intent_id']='d'*32
        with self.assertRaises(ValueError):work.check_segment(c,bad)
    def test_checker_is_readonly_and_rejects_resource_or_identity_forgery(self):
        c=control();r=receipt(changed_state(base_ticks=30000000));saved=copy.deepcopy((c,r));self.assertIs(work.check_segment(c,r),True);self.assertEqual((c,r),saved)
        for key,value in [('root_id','f'*64),('site_id','d'*64),('base_ticks',30000001),('material_credit_fraction',1)]:
            broken=copy.deepcopy(r);broken['after'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):work.check_segment(c,broken)
    def test_large_unopened_stock_does_not_force_a_native_unsafe_stock_product(self):
        cfg={**CFG,'material_work_units_per_packet':1000000000};c=control(materials=10000000);c['configuration']=cfg
        after=changed_state(base_ticks=30000000,material_credit_work=999880000)
        self.assertTrue(work.check_segment(c,receipt(after,materials=9999999)))
    def test_legacy_component_configuration_cannot_be_reinterpreted(self):
        c=control();c['configuration']=dict(version='fixed-time-fortification-1',gain_points_per_hour=20,material_points_per_packet=20,assumption='Legacy')
        with self.assertRaises(ValueError):work.material_balance(c)

if __name__=='__main__':unittest.main(verbosity=2)
