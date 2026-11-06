"""Observation age follows real elapsed time; contact physics remains in engines."""
import copy
import json
import unittest

from backend import dsh_simulation
from gentactix import historical_operations, missions
from tools.qa.historical_operational_fixture import inputs
from verify_dsh_resources import model_result


def proposal(world, seconds=1800):
    value=model_result(world)
    for row,(_,unit) in zip(value['unit_updates'],missions.units(world)):
        row['formation']={'intel_age_min':unit['formation']['intel_age_min']+seconds/60}
    return value


class C2ObservationTests(unittest.TestCase):
    def setUp(self):self.world=historical_operations.initial(*inputs())

    def test_actual_minutes_seconds_jump_is_rejected_without_repair(self):
        self.world['red_units'][0]['formation']['intel_age_min']=180
        value=proposal(self.world);value['unit_updates'][0]['formation']['intel_age_min']=1830
        before=copy.deepcopy(self.world);candidate=copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,'情报时效'):
            dsh_simulation.apply(self.world,value,'30分钟')
        self.assertEqual(before,self.world);self.assertEqual(candidate,value)

    def test_waiting_cannot_silently_keep_stale_age(self):
        value=proposal(self.world);value['unit_updates'][0].pop('formation')
        with self.assertRaisesRegex(ValueError,'情报时效'):
            dsh_simulation.apply(self.world,value,'30分钟')

    def test_recon_order_alone_does_not_prove_information_refresh(self):
        value=proposal(self.world);value['orders'][0]['action']='recon'
        value['unit_updates'][0]['formation']['intel_age_min']=0
        with self.assertRaisesRegex(ValueError,'情报时效|侦察回执'):
            dsh_simulation.apply(self.world,value,'30分钟')

    def test_native_telemetry_keeps_fractional_minutes(self):
        from backend import afsim_world
        scene=afsim_world.compile_scene(self.world,[],30,native_rules=True)
        self.assertIn('Format.Fixed(p0.AuxDataDouble("ca_intel_age_min"),12)',scene['script'])
        self.assertNotIn('ca_intel_age_min")+30)',scene['script'])

    def test_confidence_is_a_continuous_score_and_native_output_keeps_it(self):
        from backend import afsim_world
        snapshot,parameters=inputs();identity=next(iter(parameters['actors']))
        parameters['actors'][identity]['formation']['intel_confidence']=79.5
        world=historical_operations.initial(snapshot,parameters)
        self.assertTrue(missions.validate(json.loads(json.dumps(world))))
        scene=afsim_world.compile_scene(world,[],900,native_rules=True)
        self.assertIn('Format.Fixed(p0.AuxDataDouble("ca_intel_confidence"),12)',scene['script'])

    def test_actual_duration_including_subminute_survives_json_restore(self):
        for label,seconds in [('0.5分钟',30),('5分钟',300),('15分钟',900),('1小时',3600),('6小时',21600)]:
            with self.subTest(label=label):
                snapshot,parameters=inputs();parameters['clock']['time_step']=label
                world=historical_operations.initial(snapshot,parameters);value=proposal(world,seconds)
                before=copy.deepcopy(world);candidate=copy.deepcopy(value)
                after=dsh_simulation.apply(world,value,label)
                self.assertEqual(after['red_units'][0]['formation']['intel_age_min'],10+seconds/60)
                self.assertTrue(missions.validate(json.loads(json.dumps(after))))
                self.assertEqual(world,before);self.assertEqual(value,candidate)
                self.assertEqual(after['dsh_execution']['intelligence']['elapsed_seconds'],seconds)

    def recon(self,seconds=300.5,status=0):
        value=proposal(self.world);unit=self.world['red_units'][0]
        value['orders'][0]['action']='recon'
        value['combined_arms']={'events':[dict(unit=unit['name'],action='recon',seconds=seconds,status_code=status,model_estimate=True)]}
        value['unit_updates'][0]['formation'].update(intel_age_min=(1800-seconds)/60,intel_confidence=100)
        return value

    def test_successful_recon_ages_again_after_the_actual_refresh_time(self):
        value=self.recon();after=dsh_simulation.apply(self.world,value,'30分钟')
        self.assertAlmostEqual(after['red_units'][0]['formation']['intel_age_min'],24.991666666666667)
        self.assertEqual(after['dsh_execution']['intelligence']['refreshed_units'],1)
        tail=proposal(after);continued=dsh_simulation.apply(json.loads(json.dumps(after)),tail,'30分钟')
        self.assertAlmostEqual(continued['red_units'][0]['formation']['intel_age_min'],54.99166666666667)

    def test_failed_recon_receipt_does_not_refresh_or_raise_confidence(self):
        value=self.recon(status=1)
        value['unit_updates'][0]['formation'].update(intel_age_min=40,intel_confidence=70)
        after=dsh_simulation.apply(self.world,value,'30分钟')
        self.assertEqual(after['dsh_execution']['intelligence']['refreshed_units'],0)
        value['unit_updates'][0]['formation']['intel_age_min']=0
        with self.assertRaisesRegex(ValueError,'情报时效'):dsh_simulation.apply(self.world,value,'30分钟')

    def test_recon_before_delivery_duplicate_wrong_order_or_future_is_rejected(self):
        for kind in ('early','duplicate','wrong_order','future','missing_status'):
            value=self.recon();event=value['combined_arms']['events'][0]
            if kind=='early':event['seconds']=0
            elif kind=='duplicate':value['combined_arms']['events'].append(copy.deepcopy(event))
            elif kind=='wrong_order':value['orders'][0]['action']='restore_comms'
            elif kind=='future':event['seconds']=1801
            else:event.pop('status_code')
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                dsh_simulation.apply(self.world,value,'30分钟')

    def test_confidence_cannot_improve_without_new_information(self):
        value=proposal(self.world);value['unit_updates'][0]['formation']['intel_confidence']=100
        with self.assertRaisesRegex(ValueError,'可信度'):dsh_simulation.apply(self.world,value,'30分钟')

    def test_restore_comms_does_not_erase_intelligence_age(self):
        value=proposal(self.world);value['orders'][0]['action']='restore_comms'
        value['unit_updates'][0]['formation']['intel_age_min']=0
        with self.assertRaisesRegex(ValueError,'情报时效'):dsh_simulation.apply(self.world,value,'30分钟')

    def test_fractional_initial_age_is_not_a_personnel_or_resource_count(self):
        snapshot,parameters=inputs();identity=next(iter(parameters['actors']))
        parameters['actors'][identity]['formation']['intel_age_min']=.25
        world=historical_operations.initial(snapshot,parameters)
        unit=next(u for _,u in missions.units(world) if u['historical_unit_id']==identity)
        self.assertEqual(unit['formation']['intel_age_min'],.25)
        for bad in (True,-1,float('nan'),float('inf'),'2'):
            other=copy.deepcopy(world);other['red_units'][0]['formation']['intel_age_min']=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):missions.validate(other)

    def test_prompt_describes_units_delivery_and_refresh_receipt(self):
        text=dsh_simulation.prompt(self.world,time_step='15分钟')
        self.assertIn('900/60',text);self.assertIn('本轮实际发生秒数',text)
        self.assertIn('restore_comms只恢复联络',text)


if __name__=='__main__':unittest.main()
