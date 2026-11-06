"""Scheduled logistics shares physical clocks/stocks; no host-side executor."""
import copy
import unittest

from gentactix import historical_operations as ho, missions, motion_state, support_dynamics as sd
from tools.qa.historical_operational_fixture import inputs
from verify_continuous_motion import CONFIG
from verify_split_supply import config as split_config
from verify_supply_schedule import config as schedule_config
from verify_support_dynamics import config as nutrition_config


def world(*,cut=False,personnel=False,incapacity=False):
    source,p=inputs()
    schedule=schedule_config();schedule['period_seconds']=60
    p.update(movement_feedback=copy.deepcopy(CONFIG),
        fire_dynamics={'version':'live-footprint-density-2','assumption':CONFIG['assumption']},
        support_dynamics=nutrition_config(),supply_distribution=split_config(),supply_schedule=schedule)
    p['clock']['time_step']='5分钟'
    for a in p['actors'].values():
        a['logistics']={'food':0,'ammo':100};a['ground_control_radius_km']=0
    if personnel:
        from verify_personnel_rations import config
        p['support_dynamics']=config()
    if incapacity:p['support_dynamics']['incapacity_fraction_per_hour']=.1
    if cut:
        red=p['actors']['ww2.cn.division31'];blue=p['actors']['ww2.jp.seya_detachment']
        node=p['support']['red']['position']
        blue['position']={k:(node[k]+red['position'][k])/2 for k in ('lat','lng')}
        blue['ground_control_radius_km']=.2
    return ho.initial(source,p)


def receipt(value,seconds=120,*,food=0,fuel=0):
    from gentactix import supply_schedule as ss, timed_fuel as tf
    from backend import afsim_motion_nutrition as cn
    times=ss.event_times(value,seconds);items=[]
    for _,original in missions.units(value):
        u=copy.deepcopy(original);events=[];segments=[];timeline=[]
        cfg=value['mission']['definition']['support_dynamics'];opening=motion_state.fuel_load(u)
        for start in range(0,seconds*1000,10000):
            r=sd.expected(cfg,u,'hold',10)
            segments.append(dict(start_ms=start,end_ms=start+10000,moving_ms=0,
                people=u['personnel']['current'],fatigue_floor_gain_ticks=0,
                **{k:r[k] for k in cn.FIELDS if k in r}))
            u['logistics']['food']-=r['consumed'];u['personnel']['current']-=r['noncombat_delta']
            u['sustainment'].update({k:r[k] for k in ('shortage_hours','noncombat_remainder')})
            if (start+10000)/1000 in [t for t,kind in times if kind=='delivery']:u['logistics']['food']+=food
        for when,kind in times:
            f=food if kind=='delivery' else 0;g=fuel if kind=='delivery' else 0
            events.append(dict(seconds=when,kind=kind,supply_status='未切断',
                position={k:original[k] for k in ('lat','lng')},food_received=f,
                ammo_received=0,ammo_spent=0,received={'fuel_liters':g},spent={}))
            timeline.append(dict(seconds=when,kind=kind,opening_microliters=opening,
                received_microliters=g*motion_state.SCALE,movement_spent_microliters=0,
                support_spent_microliters=0,closing_microliters=opening+g*motion_state.SCALE))
            opening+=g*motion_state.SCALE
        items.append(dict(unit=original['name'],events=events,nutrition_segments=segments,
            fuel_timeline=dict(version=tf.VERSION,unit='microliter',events=timeline)))
    return dict(version='scheduled-supply-2',units=items)


class ScheduledPhysicalTests(unittest.TestCase):
    def test_version_is_derived_from_existing_physical_profile_without_changing_config(self):
        from gentactix import supply_schedule as ss
        from verify_supply_schedule import world as old_world
        self.assertEqual(ss.receipt_version(world()),'scheduled-supply-2')
        self.assertEqual(ss.receipt_version(old_world()),ss.VERSION)

    def test_chronological_food_and_fuel_contract_is_readonly(self):
        from gentactix import supply_schedule as ss
        value=world();ledger=receipt(value,food=.05,fuel=1);saved=copy.deepcopy((value,ledger))
        checked=ss.validate_ledger(value,ledger,[],120)
        self.assertEqual((value,ledger),saved)
        for row in checked.values():
            self.assertGreater(row['nutrition']['unmet'],0)
            self.assertEqual(row['fuel_timeline']['received_microliters'],2000000)
            self.assertNotIn('fuel_liters',row['spent'])

    def test_old_integer_bucket_drop_cannot_replace_physical_fuel_spending(self):
        from gentactix import supply_schedule as ss
        value=world();ledger=receipt(value);ledger['units'][0]['events'][0]['spent']['fuel_liters']=1
        with self.assertRaises(ValueError):ss.validate_ledger(value,ledger,[],120)
        ledger=receipt(value);ledger['version']=ss.VERSION
        with self.assertRaises(ValueError):ss.validate_ledger(value,ledger,[],120)

    def test_future_deliveries_do_not_pay_prior_food_or_fuel(self):
        from gentactix import supply_schedule as ss
        for kind in ('food','fuel','credit'):
            value=world();ledger=receipt(value,food=.05,fuel=1);item=ledger['units'][0]
            if kind=='food':item['nutrition_segments'][0]['consumed']=item['nutrition_segments'][0]['demand']
            else:
                r=item['fuel_timeline']['events'][0]
                if kind=='fuel':r['movement_spent_microliters']=r['opening_microliters']+1
                else:r['received_microliters']+=1;r['closing_microliters']+=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):ss.validate_ledger(value,ledger,[],120)

    def test_summary_avoids_raw_interval_context_and_cannot_be_resubmitted_as_full_evidence(self):
        from gentactix import supply_schedule as ss
        value=world();ledger=receipt(value);checked=ss.validate_ledger(value,ledger,[],120)
        saved=copy.deepcopy(ledger);compact=ss.compact_ledger(ledger,checked)
        self.assertEqual(ledger,saved)
        self.assertEqual(compact['representation'],'validated-summary-1')
        self.assertNotIn('nutrition_segments',compact['units'][0])
        self.assertEqual(compact['units'][0]['nutrition_summary']['interval_count'],12)
        self.assertEqual(compact['units'][0]['events'],ledger['units'][0]['events'])
        with self.assertRaises(ValueError):ss.validate_ledger(value,compact,[],120)

    def test_shared_warehouse_and_known_route_cut_still_bound_physical_receipts(self):
        from gentactix import supply_schedule as ss
        value=world();ledger=receipt(value,food=.05)
        for k in value['mission']['definition']['supply_schedule']['warehouse_tons_per_hour']:
            value['mission']['definition']['supply_schedule']['warehouse_tons_per_hour'][k]=0
        with self.assertRaisesRegex(ValueError,'装卸'):
            ss.validate_ledger(value,ledger,[],120)
        value=world(cut=True)
        with self.assertRaisesRegex(ValueError,'切断'):
            ss.validate_ledger(value,receipt(value),[],120)

    def test_component_binding_uses_existing_allocator_and_one_nutrition_stock(self):
        from verify_continuous_motion_integration import compile_world
        value=world();u=value['red_units'][0]
        _,_,_,model=compile_world(value,[{'unit':u['name'],'action':'resupply'}],seconds=120)
        script=model['script'];component=model['continuous_motion']
        self.assertTrue(component['timed_fuel_revision'])
        self.assertTrue(component['nutrition_schedule_revision'])
        self.assertIn('GtxCNReceiveFood(',script)
        self.assertIn('GtxCMReceiveFuel(',script)
        self.assertIn('GTXSCHEDULE2|',script)
        self.assertNotIn('"sl_food"',script)
        self.assertIn('budget0',script)

    def test_agent_instruction_names_the_physical_receipt_and_actual_moving_time(self):
        from gentactix import supply_schedule as ss
        text=ss.instruction(world(),120)
        for word in ['scheduled-supply-2','nutrition_segments','fuel_timeline','moving_ms','微升']:
            with self.subTest(word=word):self.assertIn(word,text)

    def test_observation_exposes_units_and_totals_without_raw_ten_second_segments(self):
        from backend import afsim_state
        from gentactix import supply_schedule as ss
        value=world();ledger=receipt(value,fuel=1);checked=ss.validate_ledger(value,ledger,[],120)
        value['supply_schedule']=dict(version=ss.PHYSICAL_VERSION,turn=1,source='afsim_native_estimate',
            ledger=ss.compact_ledger(ledger,checked))
        session=dict(id='a123456789ab',war_state=value,turn_count=1,execution_backend='narrative',time_step='5分钟')
        saved=copy.deepcopy(session);page=afsim_state.observation(session)
        row=page['units'][0]['supply_schedule']
        self.assertEqual(row['fuel_flow']['unit'],'microliter')
        self.assertEqual(row['fuel_flow']['received_microliters'],2000000)
        self.assertEqual(row['nutrition_summary']['interval_count'],12)
        self.assertNotIn('events',row)
        self.assertEqual(session,saved)


if __name__=='__main__':unittest.main()
