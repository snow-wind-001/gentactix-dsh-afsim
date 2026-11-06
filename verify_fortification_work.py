"""Time-based construction conservation; explicit QA rates, not historical facts."""
import copy
import unittest

from gentactix import fortification_work as work


CONFIG = {'version': 'fixed-time-fortification-1', 'gain_points_per_hour': 20,
          'material_points_per_packet': 20,
          'assumption': '软件QA估计；归一化工作量不是历史工兵人数或材料吨数。'}


def state(**changes):
    return {**work.initial_state(root_id='a'*64, root_committed=3000, committed=3000,
                                base_ticks=10_000_000, materials=16), **changes}


def control(before=None, **changes):
    return {'entity_id': 'g00000000000000000001', 'configuration': copy.deepcopy(CONFIG),
            'state': state() if before is None else copy.deepcopy(before),
            'current': 3000, 'fortify': True, 'intent_id': 'a'*32,
            'command_delay_ms': 0, **changes}


def receipt(before=None, *, ms=900000, base=15_000_000, materials=15,
            credit=45000, added=15000, reserved=1, **changes):
    after=state(base_ticks=base, materials=materials, material_credit_work=credit,
                intent_id='a'*32)
    if before is not None:
        after.update(root_committed=before['root_committed'], committed=before['committed'])
    return {'version': work.RECEIPT_VERSION, 'entity_id': 'g00000000000000000001',
            'elapsed_ms': ms, 'waited_ms': 0, 'available_ms': ms,
            'work_added': added, 'packets_reserved': reserved,
            'discarded_numerator': 0, 'cap_excess_micro_work': 0,
            'after': after, **changes}


class FortificationWorkTests(unittest.TestCase):
    def test_full_hour_and_four_quarters_have_identical_effects_and_material_stock(self):
        start=state();hour=receipt(ms=3600000,base=30_000_000,credit=0,added=60000)
        self.assertTrue(work.check_transition(control(start),hour))
        current=copy.deepcopy(start)
        for number in range(1,5):
            r=receipt(current,base=10_000_000+number*5_000_000,
                      credit=(4-number)*15000,reserved=int(number==1))
            self.assertTrue(work.check_transition(control(current),r))
            current=r['after']
        self.assertEqual(current,hour['after'])

    def test_checker_is_readonly_and_returns_no_repaired_candidate(self):
        c,r=control(),receipt();saved=copy.deepcopy((c,r))
        self.assertIs(work.check_transition(c,r),True)
        self.assertEqual((c,r),saved)

    def test_rejects_free_entrenchment_extra_materials_or_forged_work(self):
        for path,value in [('base_ticks',16_000_000),('materials',16),
                           ('material_credit_work',45001),('point_remainder',1),
                           ('work_remainder',1)]:
            r=receipt();r['after'][path]=value
            with self.subTest(field=path),self.assertRaises(ValueError):
                work.check_transition(control(),r)
        for key in ('work_added','packets_reserved','available_ms'):
            r=receipt();r[key]+=1
            with self.subTest(field=key),self.assertRaises(ValueError):
                work.check_transition(control(),r)

    def test_quarter_strength_produces_quarter_work_not_full_strength_gain(self):
        r=receipt(base=11_250_000,credit=56250,added=3750)
        self.assertTrue(work.check_transition(control(current=750),r))

    def test_credit_is_physical_stock_shared_by_disjoint_parts(self):
        before=state(root_committed=6000,committed=3000)
        r=receipt(before,credit=105000)
        self.assertTrue(work.check_transition(control(before),r))
        summary=work.stock_work(r['after'],CONFIG)
        self.assertEqual(summary,15*120000+105000)

    def test_a_valid_balance_cannot_change_its_root_identity(self):
        r=receipt();r['after']['root_id']='b'*64
        with self.assertRaisesRegex(ValueError,'身份'):work.check_transition(control(),r)

    def test_same_intent_carries_wait_but_new_intent_pays_new_command_delay(self):
        before=state(intent_id='a'*32,wait_remaining_ms=300000)
        r=receipt(before,ms=900000,base=13_333_333,credit=50000,added=10000,
                  waited_ms=300000,available_ms=600000)
        r['after']['point_remainder']=1000
        self.assertTrue(work.check_transition(control(before,command_delay_ms=600000),r))
        r=receipt(ms=900000,base=11_666_666,credit=55000,added=5000,
                  waited_ms=600000,available_ms=300000)
        r['after'].update(intent_id='b'*32,point_remainder=2000)
        self.assertTrue(work.check_transition(control(before,intent_id='b'*32,
                                                      command_delay_ms=600000),r))

    def test_paid_credit_can_continue_without_an_unopened_material_packet(self):
        before=state(materials=0,material_credit_work=15000,intent_id='a'*32)
        r=receipt(before,materials=0,credit=0,reserved=0)
        self.assertTrue(work.check_transition(control(before),r))

    def test_empty_material_stock_cannot_build_and_reports_unused_potential(self):
        before=state(materials=0)
        r=receipt(before,base=10_000_000,materials=0,credit=0,added=0,reserved=0,
                  discarded_numerator=15000*3600000)
        self.assertTrue(work.check_transition(control(before),r))

    def test_entrenchment_cap_keeps_unused_prepaid_work_in_the_stock(self):
        before=state(base_ticks=99_000_000)
        r=receipt(before,base=100_000_000,credit=57000,added=3000,
                  discarded_numerator=12000*3600000)
        self.assertTrue(work.check_transition(control(before),r))

    def test_zero_time_cannot_create_work_or_consume_material(self):
        before=state(intent_id='a'*32)
        r=receipt(before,ms=0,base=10_000_000,materials=16,credit=0,added=0,reserved=0)
        self.assertTrue(work.check_transition(control(before),r))

    def test_idle_preserves_unspent_credit_and_partial_work(self):
        before=state(intent_id='a'*32,work_remainder=123,point_remainder=456,
                     material_credit_work=100)
        after=copy.deepcopy(before);after.update(intent_id=None,wait_remaining_ms=0)
        r=receipt(before,available_ms=0,work_added=0,packets_reserved=0,after=after)
        self.assertTrue(work.check_transition(control(before,fortify=False,intent_id=None),r))

    def test_state_contract_rejects_partial_invalid_or_ambiguous_units(self):
        for key,value in [('root_committed',0),('committed',3001),('base_ticks',100_000_001),
                          ('point_remainder',3000),('work_remainder',3600000),
                          ('material_credit_work',-1),('materials',True)]:
            candidate=state();candidate[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):work.validate_state(candidate)
        candidate=state();candidate.pop('work_remainder')
        with self.assertRaises(ValueError):work.validate_state(candidate)

    def test_config_and_time_budget_are_explicit_and_finite(self):
        for key,value in [('gain_points_per_hour',0),('material_points_per_packet',1.5),
                          ('assumption',''),('version','guess')]:
            cfg=copy.deepcopy(CONFIG);cfg[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):work.validate_config(cfg)
        for ms in (-1,True,work.MAX_ELAPSED_MS+1):
            r=receipt(ms=ms)
            with self.subTest(ms=ms),self.assertRaises(ValueError):work.check_transition(control(),r)


if __name__=='__main__':unittest.main()
