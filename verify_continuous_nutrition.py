"""Actual-time nutrition shares Native motion time; old action contracts persist."""
import copy
import unittest

from backend import afsim_continuous_motion as cm
from gentactix import historical_operations as ho, missions, support_dynamics as sd
from tools.qa.historical_operational_fixture import inputs
from verify_continuous_motion import CONFIG
from verify_support_dynamics import config


def world(*,incapacity_fraction=None):
    source,p=inputs()
    nutrition=config()
    if incapacity_fraction is not None:nutrition['incapacity_fraction_per_hour']=incapacity_fraction
    p.update(movement_feedback=copy.deepcopy(CONFIG),
        fire_dynamics={'version':'live-footprint-density-2','assumption':CONFIG['assumption']},
        support_dynamics=nutrition)
    p['rules'].update(command_base_s=30,command_signal_s=0,command_distance_s_per_km=0)
    return ho.initial(source,p)


class ContinuousNutritionTests(unittest.TestCase):
    def receipt(self):
        from backend import afsim_motion_nutrition as cn
        value=world();entities={'g'+str(i):{'name':u['name'],'team':t} for i,(t,u) in enumerate(missions.units(value))}
        model=cm.compile_process(cm.inputs(value,[],entities),20,shared=True);lines=[]
        for identity,c in model['controls'].items():
            u=copy.deepcopy(c['nutrition']['unit']);cfg=c['nutrition']['config']
            for start in (0,10000):
                wanted=sd.expected(cfg,u,'hold',10)
                r={k:0 for k in cn.FIELDS};r.update(start_ms=start,end_ms=start+10000,people=u['personnel']['current'],
                    **{k:wanted[k] for k in ('demand','consumed','shortage_hours','noncombat_remainder','fatigue_floor','noncombat_delta')})
                lines.append('GTXCNSEG|'+identity+'|'+'|'.join(str(r[k]) for k in cn.FIELDS))
                u['logistics']['food']-=wanted['consumed'];u['sustainment'].update({k:wanted[k] for k in ('shortage_hours','noncombat_remainder')})
        return '\n'.join(lines),model

    def test_actual_moving_time_does_not_charge_waiting_and_arrived_time_as_marching(self):
        u=world()['red_units'][0];cfg=config()
        legacy=sd.expected(cfg,u,'move',3600)
        row=sd.expected(cfg,u,'move',3600,moving_seconds=600)
        expected=cfg['food_work_per_hour']*(3000+600*cfg['move_factor'])/3600
        self.assertAlmostEqual(row['demand'],expected)
        self.assertLess(row['demand'],legacy['demand'])
        for bad in [-1,3601,True,float('nan')]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):sd.expected(cfg,u,'move',3600,moving_seconds=bad)

    def test_continuous_compiler_freezes_the_existing_food_and_support_inputs(self):
        value=world();saved=copy.deepcopy(value)
        entities={'g'+str(i):{'name':u['name'],'team':t} for i,(t,u) in enumerate(missions.units(value))}
        controls=cm.inputs(value,[],entities)
        for c in controls.values():self.assertEqual(c['nutrition']['config'],value['mission']['definition']['support_dynamics'])
        self.assertEqual(value,saved)

    def test_valid_time_support_world_can_bind_the_shared_native_compiler(self):
        from verify_continuous_motion_integration import compile_world
        _,_,_,model=compile_world(world())
        self.assertTrue(model['continuous_motion']['nutrition_revision'])
        self.assertTrue('GtxCMNourish(' in model['script'])
        self.assertTrue('GTXCNSEG|' in model['script'])

    def test_interval_decoder_is_readonly_and_rejects_missing_or_duplicated_time(self):
        from backend import afsim_motion_nutrition as cn
        text,model=self.receipt();saved=copy.deepcopy(model);rows=cn.parse(text,model)
        self.assertEqual(model,saved)
        self.assertTrue(all(r['elapsed_ms']==20000 and r['interval_count']==2 for r in rows.values()))
        first=text.splitlines()[0]
        for bad in [text.replace(first,''),text+'\n'+first]:
            with self.subTest(kind=bad[-20:]),self.assertRaises(ValueError):cn.parse(bad,model)

    def test_unknown_contract_and_fabricated_zero_floor_gain_are_rejected(self):
        from backend import afsim_motion_nutrition as cn
        text,model=self.receipt();bad=copy.deepcopy(model);bad['nutrition_revision']='unknown'
        with self.assertRaises(ValueError):cn.parse(text,bad)
        rows=text.splitlines();r=rows[0].split('|');r[2+cn.FIELDS.index('fatigue_floor_gain_ticks')]='1'
        rows[0]='|'.join(r)
        with self.assertRaises(ValueError):cn.parse('\n'.join(rows),model)


if __name__=='__main__':unittest.main()
