"""Canonical read-only nutrition with chronological arrivals, no allocator."""
import copy
import unittest

from gentactix import support_dynamics as sd
from verify_continuous_nutrition import world


def fixture(*,credit_at=10000,split=True):
    value=world();u=copy.deepcopy(value['red_units'][0]);cfg=value['mission']['definition']['support_dynamics']
    u['logistics']['food']=0;original=copy.deepcopy(u);rows=[]
    cuts=[0,credit_at,20000] if split else [0,20000]
    for start,end in zip(cuts,cuts[1:]):
        if start==credit_at:u['logistics']['food']+=1
        wanted=sd.expected(cfg,u,'move',(end-start)/1000,moving_seconds=0 if start==0 else (end-start)/1000)
        row=dict(start_ms=start,end_ms=end,moving_ms=0 if start==0 else end-start,
                 people=u['personnel']['current'],fatigue_floor_gain_ticks=0,
                 **{k:wanted[k] for k in ['demand','consumed','shortage_hours','noncombat_remainder','fatigue_floor','noncombat_delta']})
        rows.append(row);u['logistics']['food']-=wanted['consumed'];u['sustainment'].update({k:wanted[k] for k in ['shortage_hours','noncombat_remainder']})
    events=[dict(seconds=credit_at/1000,kind='delivery',food_received=1),dict(seconds=20,kind='settlement',food_received=0)]
    return cfg,original,rows,events


class SustainmentIntervalTests(unittest.TestCase):
    def test_arrivals_follow_prior_consumption_and_reference_is_readonly(self):
        from gentactix import sustainment_intervals as si
        cfg,u,rows,events=fixture();saved=copy.deepcopy((cfg,u,rows,events))
        checked=si.validate(cfg,u,20,rows,events=events)
        self.assertEqual((cfg,u,rows,events),saved)
        self.assertGreater(checked['summary']['unmet'],0)
        self.assertAlmostEqual(checked['events'][0]['food_before'],0)
        self.assertAlmostEqual(checked['events'][0]['food_after'],1)
        self.assertAlmostEqual(checked['food_after'],1-rows[-1]['consumed'])

    def test_future_food_cannot_pay_the_preceding_segment(self):
        from gentactix import sustainment_intervals as si
        cfg,u,rows,events=fixture();rows[0]['consumed']=rows[0]['demand']
        with self.assertRaises(ValueError):si.validate(cfg,u,20,rows,events=events)

    def test_delivery_in_the_middle_of_a_segment_requires_a_real_boundary(self):
        from gentactix import sustainment_intervals as si
        cfg,u,rows,events=fixture(credit_at=5000)
        si.validate(cfg,u,20,rows,events=events,max_segment_ms=20000)
        cfg,u,rows,events=fixture(credit_at=5000,split=False)
        with self.assertRaises(ValueError):si.validate(cfg,u,20,rows,events=events,max_segment_ms=20000)

    def test_end_time_delivery_and_settlement_do_not_add_another_food_interval(self):
        from gentactix import sustainment_intervals as si
        cfg,u,rows,_=fixture();rows=rows[:1]
        events=[dict(seconds=10,kind='delivery',food_received=1),dict(seconds=10,kind='settlement',food_received=0)]
        checked=si.validate(cfg,u,10,rows,events=events)
        self.assertAlmostEqual(checked['food_after'],1)
        self.assertEqual(checked['summary']['consumed'],0)
        self.assertEqual(checked['summary']['elapsed_ms'],10000)

    def test_missing_duplicated_population_and_over_capacity_receipts_are_rejected(self):
        from gentactix import sustainment_intervals as si
        for kind in ['missing','duplicate','people','capacity']:
            cfg,u,rows,events=fixture()
            if kind=='missing':rows.pop()
            if kind=='duplicate':rows.insert(0,copy.deepcopy(rows[0]))
            if kind=='people':rows[-1]['people']+=1
            if kind=='capacity':events[0]['food_received']=1000
            with self.subTest(kind=kind),self.assertRaises(ValueError):si.validate(cfg,u,20,rows,events=events)

    def test_native_decoder_uses_the_same_explicit_arrival_contract(self):
        from backend import afsim_motion_nutrition as cn
        from gentactix import sustainment_intervals as si
        cfg,u,rows,events=fixture();value=world()
        model=dict(nutrition_revision=cn.VERSION,seconds=20,
            controls={'u0':{'nutrition':cn.inputs(value,u)}})
        text='\n'.join('GTXCNSEG|u0|'+'|'.join(str(r[k]) for k in cn.FIELDS) for r in rows)
        saved=copy.deepcopy(model)
        self.assertEqual(cn.read_segments(text,model),{'u0':rows})
        self.assertEqual(cn.parse(text,model,delivery_events={'u0':events})['u0'],
            si.validate(cfg,u,20,rows,events=events)['summary'])
        self.assertEqual(model,saved)
        for invalid in [{},{'unknown':events}]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                cn.parse(text,model,delivery_events=invalid)
        # A delivery is not inferred from a better-looking terminal stock.
        with self.assertRaises(ValueError):cn.parse(text,model)


if __name__=='__main__':unittest.main()
