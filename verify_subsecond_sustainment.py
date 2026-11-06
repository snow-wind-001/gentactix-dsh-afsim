"""Physical subsecond exposure is distinct from validation-only Native loading."""
import copy
import re
import unittest

from gentactix import support_dynamics as sd, sustainment_intervals as si, missions
from backend import afsim_motion_nutrition as cn, afsim_continuous_motion as cm
import verify_deferred_support as deferred_fixture


def fixture():
    case=deferred_fixture.DeferredSupportTests();case.setUp()
    proposal=case.merge();unit=proposal['after'][0]
    unit['logistics']['food']=0;unit['sustainment']['shortage_hours']=49
    return case.world,case.cfg,unit


def segment(unit,row,*,end=1,moving=0):
    return dict(start_ms=0,end_ms=end,moving_ms=moving,people=unit['personnel']['current'],
        fatigue_floor_gain_ticks=0,**{k:row[k] for k in si.FIELDS if k in row})


class SubsecondSustainmentTests(unittest.TestCase):
    def test_real_half_second_hold_and_movement_consume_exposure_once(self):
        _,cfg,u=fixture();saved=copy.deepcopy(u)
        for moving in (0,.25):
            with self.subTest(moving=moving):
                row=sd.expected(cfg,u,'move',.5,moving_seconds=moving)
                self.assertGreater(row['demand'],0)
                self.assertEqual(row['noncombat_delta'],1)
                self.assertGreater(row['shortage_hours'],49)
                self.assertGreater(row['noncombat_remainder'],.2)
                self.assertLess(row['noncombat_remainder'],1)
        self.assertEqual(u,saved)

    def test_one_millisecond_physical_fragment_is_not_a_load_probe(self):
        _,cfg,u=fixture()
        loaded=sd.expected(cfg,u,'hold',.001)
        physical=sd.expected(cfg,u,'move',.001,moving_seconds=0)
        self.assertEqual(loaded['demand'],0)
        self.assertEqual(loaded['noncombat_delta'],0)
        self.assertEqual(loaded['noncombat_remainder'],1.2)
        self.assertGreater(physical['demand'],0)
        self.assertEqual(physical['noncombat_delta'],1)

    def test_ordinary_half_second_hold_is_physical_without_movement_metadata(self):
        _,cfg,u=fixture()
        held=sd.expected(cfg,u,'hold',.5)
        explicit=sd.expected(cfg,u,'move',.5,moving_seconds=0)
        self.assertEqual(held,explicit)
        self.assertEqual(held['noncombat_delta'],1)

    def test_legacy_native_emitter_uses_the_same_real_elapsed_food_demand(self):
        from backend import afsim_sustainment
        _,cfg,u=fixture()
        for seconds in (.001,.5,1):
            with self.subTest(seconds=seconds):
                lines=afsim_sustainment.finish(cfg,u,'hold',seconds,0,'u0','actor')
                emitted=float(re.search(r'double foodNeed0=([^;]+);','\n'.join(lines)).group(1))
                self.assertAlmostEqual(emitted,sd.expected(cfg,u,'hold',seconds)['demand'],places=12)

    def test_real_interval_decoder_rejects_omitted_subsecond_consumption(self):
        _,cfg,u=fixture();row=sd.expected(cfg,u,'move',.5,moving_seconds=.25)
        actual=segment(u,row,end=500,moving=250)
        checked=si.validate(cfg,u,.5,[actual])
        self.assertEqual(checked['summary']['noncombat_delta'],1)
        self.assertEqual(checked['summary']['moving_ms'],250)
        omitted=copy.deepcopy(actual);omitted['demand']=0
        with self.assertRaises(ValueError):si.validate(cfg,u,.5,[omitted])

    def test_explicit_load_receipt_preserves_pending_load_and_is_readonly(self):
        _,cfg,u=fixture();row=segment(u,sd.expected(cfg,u,'hold',.001))
        saved=copy.deepcopy((u,row))
        checked=si.validate(cfg,u,.001,[row],load_probe=True)
        self.assertEqual(checked['summary']['noncombat_delta'],0)
        self.assertEqual(checked['summary']['noncombat_remainder'],1.2)
        self.assertEqual(checked['summary']['demand'],0)
        self.assertEqual((u,row),saved)
        with self.assertRaises(ValueError):si.validate(cfg,u,.001,[row])
        for seconds,flag in ((.5,True),(1,True),(.001,1),(.001,'true')):
            with self.subTest(seconds=seconds,flag=flag),self.assertRaises(ValueError):
                si.validate(cfg,u,seconds,[row],load_probe=flag)
        moving={**row,'moving_ms':1}
        with self.assertRaises(ValueError):si.validate(cfg,u,.001,[moving],load_probe=True)

    def test_native_compiler_binds_probe_only_to_deferred_initial_loading(self):
        from verify_scheduled_physical import world
        w=world();entities={'u'+str(i):dict(team=t,name=u['name']) for i,(t,u) in enumerate(missions.units(w))}
        controls=cm.inputs(w,[],entities);normal=cm.compile_process(controls,.001,shared=True)
        self.assertNotIn('nutrition_load_probe',normal)
        original,cfg,u=fixture();first=next(iter(controls.values()));first['nutrition']=cn.inputs(original,u)
        loaded=cm.compile_process(controls,.001,shared=True)
        self.assertTrue(loaded.get('nutrition_load_probe'))
        self.assertIn('hours=0; active=0;',loaded['functions'])
        running=cm.compile_process(controls,300,shared=True)
        self.assertNotIn('nutrition_load_probe',running)
        self.assertNotIn('hours=0; active=0;',running['functions'])
        self.assertNotEqual(loaded['token'],normal['token'])

    def test_native_decoder_uses_the_same_explicit_probe_contract(self):
        world,cfg,u=fixture();row=segment(u,sd.expected(cfg,u,'hold',.001))
        model=dict(nutrition_revision=cn.VERSION,nutrition_load_probe=True,seconds=.001,
            controls={'u0':{'nutrition':cn.inputs(world,u)}})
        raw='GTXCNSEG|u0|'+'|'.join(str(row[k]) for k in cn.FIELDS)
        loaded=cn.parse(raw,model)['u0']
        self.assertEqual(loaded['noncombat_delta'],0)
        self.assertEqual(loaded['noncombat_remainder'],1.2)
        model.pop('nutrition_load_probe')
        with self.assertRaises(ValueError):cn.parse(raw,model)


if __name__=='__main__':unittest.main()
