"""Native continuous-motion component contracts; never a Python turn executor."""
import copy
import unittest

from gentactix import commands, missions, motion_state
from verify_continuous_motion import world


class NativeContinuousMotionTests(unittest.TestCase):
    def test_repeated_native_settlement_without_elapsed_time_cannot_charge_motion(self):
        from backend import afsim_continuous_motion as cm
        # WSF GroundRangeTo can report a small distance for coincident points.
        # Repeated endpoint sampling must return before any distance or cost.
        code=cm.functions().split('script void GtxCMSettle(',1)[1].split('end_script',1)[0]
        guard=code.index('if (dt<=0) { return; }')
        for operation in ('double lat=', 'if (mode==2)', 'old.GroundRangeTo(current)'):
            self.assertLess(guard,code.index(operation))

    def test_persistent_goal_is_not_recut_at_each_external_round(self):
        value=world();session={'id':'ce2200000001','role_epoch':0,'turn_count':0,
            'war_state':value,'time_step':'30分钟','product_mode':'historical',
            'simulation_mode':'open','execution_backend':'afsim'}
        entry=commands.view(session)['units'][0];unit=commands.resolve_units(session)[entry['id']][1]
        destination={'lat':unit['lat']+.05,'lng':unit['lng']}
        cs=commands.replace_queue(session,[{'unit_id':entry['id'],'action':'move',
            'duration':'until_arrived','destination':destination}],control_team='red',
            director=True,no_fire=False,intent='QA continuous goal, not historical deployment')
        raw=commands.step_order(session,cs['orders'][0],cs)
        self.assertEqual({k:raw[k] for k in ('lat','lng')},destination)
        self.assertTrue(missions.validate_orders(value,[raw],'30分钟'))

    def test_next_round_request_keeps_its_existing_short_route_bound(self):
        value=world();session={'id':'ce2200000001','role_epoch':0,'turn_count':0,
            'war_state':value,'time_step':'30分钟','simulation_mode':'open','execution_backend':'afsim'}
        entry=commands.view(session)['units'][0];unit=commands.resolve_units(session)[entry['id']][1]
        with self.assertRaisesRegex(ValueError,'预算'):
            commands.replace_queue(session,[{'unit_id':entry['id'],'action':'move','duration':'next',
                'destination':{'lat':unit['lat']+.05,'lng':unit['lng']}}],control_team='red',
                director=True,no_fire=False,intent='QA')

    def test_control_carries_remaining_wait_only_for_the_same_intent_and_goal(self):
        from backend import afsim_continuous_motion as cm
        value=world();u=value['red_units'][0]
        order={'unit':u['name'],'action':'move','lat':u['lat']+.001,'lng':u['lng'],'intent_id':'a'*32}
        old=cm.intent(u,order,750000)
        self.assertEqual(old['wait_remaining_ms'],750000)
        old.update(wait_remaining_ms=450000,status='waiting')
        u['formation']['motion_task']=copy.deepcopy(old)
        saved=copy.deepcopy(u)
        self.assertEqual(cm.intent(u,order,750000),old)
        self.assertEqual(u,saved)
        other=cm.intent(u,{**order,'intent_id':'b'*32},750000)
        self.assertEqual(other['wait_remaining_ms'],750000)
        with self.assertRaisesRegex(ValueError,'目标|意图'):
            cm.intent(u,{**order,'lat':order['lat']+.001},750000)

    def test_task_precision_rejects_missing_fields_and_invalid_motion_status(self):
        from backend import afsim_continuous_motion as cm
        value=world();u=value['red_units'][0]
        task=cm.intent(u,{'unit':u['name'],'action':'move','lat':u['lat']+.001,'lng':u['lng'],'intent_id':'a'*32},30000)
        motion_state.validate_task(task)
        for key,bad in [('wait_remaining_ms',True),('status','teleported'),('speed_mps',float('nan')),
                        ('feedback_remaining_ms',10001)]:
            changed=copy.deepcopy(task);changed[key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):motion_state.validate_task(changed)
        changed=copy.deepcopy(task);changed.pop('target')
        with self.assertRaises(ValueError):motion_state.validate_task(changed)

    def test_component_requires_complete_identity_and_explicit_prepared_profile(self):
        from backend import afsim_continuous_motion as cm
        value=world();entities={str(i):{'name':u['name'],'team':t} for i,(t,u) in enumerate(missions.units(value))}
        # Entity names are compiled identifiers, not arbitrary source/display text.
        entities={'g'+i:row for i,row in entities.items()}
        inputs=cm.inputs(value,[],entities)
        self.assertEqual(set(inputs),set(entities))
        bad=copy.deepcopy(entities);bad.pop(next(iter(bad)))
        with self.assertRaises(ValueError):cm.inputs(value,[],bad)
        old=copy.deepcopy(value);old['mission']['definition'].pop('movement_feedback')
        with self.assertRaises(ValueError):cm.inputs(old,[],entities)

    def test_fractional_fuel_conservation_uses_microliters(self):
        from backend import afsim_continuous_motion as cm
        initial={'formation':{'fatigue':60,'fatigue_carry_ticks':125000,
            'fuel_liters':0,'fuel_credit_microliters':300000}}
        closing={'formation':{'fatigue':60,'fatigue_carry_ticks':200000,
            'fuel_liters':0,'fuel_credit_microliters':250001}}
        cm.check_fuel(initial,closing,49999)
        with self.assertRaisesRegex(ValueError,'燃油|微升'):cm.check_fuel(initial,closing,50000)
        with self.assertRaises(ValueError):cm.check_fuel(initial,closing,True)

    def test_paged_observation_keeps_precision_and_actual_motion_task(self):
        from backend import afsim_continuous_motion as cm, afsim_state
        value=world();u=value['red_units'][0]
        u['formation'].update(fatigue_carry_ticks=123456,fuel_credit_microliters=789123)
        task=cm.intent(u,{'unit':u['name'],'action':'move','lat':u['lat']+.001,'lng':u['lng'],'intent_id':'a'*32},750000)
        u['formation']['motion_task']=copy.deepcopy(task);saved=copy.deepcopy(value)
        session={'id':'ce2200000001','role_epoch':0,'turn_count':0,'war_state':value,
            'time_step':'30分钟','simulation_mode':'open','execution_backend':'afsim'}
        row=afsim_state.observation(session,{'limit':1})['units'][0]
        self.assertEqual(row['formation']['fatigue_carry_ticks'],123456)
        self.assertEqual(row['formation']['fuel_credit_microliters'],789123)
        self.assertEqual(row['formation']['motion_task'],task)
        row['formation']['motion_task']['wait_remaining_ms']=1
        self.assertEqual(value,saved)

    def receipt(self,change=None,*,drop=False,duplicate=False,extra=''):
        from backend import afsim_continuous_motion as cm
        value=world();entities={'g'+str(i):{'name':u['name'],'team':t} for i,(t,u) in enumerate(missions.units(value))}
        controls=cm.inputs(value,[],entities);model=cm.compile_process(controls,300)
        lines=['GTXCMODEL|'+model['token']]
        for i,c in controls.items():
            r={k:0 for k in (*cm.INTEGER_FIELDS,*cm.REAL_FIELDS)}
            r.update(elapsed_ms=300000,rest_ms=300000,
                fatigue_ticks=max(0,motion_state.fatigue_load({'formation':c['formation']})-2000000),
                fuel_microliters=motion_state.fuel_load({'formation':c['formation']}),
                lat=c['origin']['lat'],lng=c['origin']['lng'])
            if i==next(iter(controls)) and change:change(r)
            line='GTXCMOTION|'+i+'|'+'|'.join(str(r[k]) for k in (*cm.INTEGER_FIELDS,*cm.REAL_FIELDS))
            if not(drop and i==next(iter(controls))):lines.append(line)
            if duplicate and i==next(iter(controls)):lines.append(line)
            lines.append('GTXCMKINEMATIC|'+i+'|0')
        return '\n'.join(lines)+'\n'+extra,model

    def test_decoding_is_readonly_and_covers_all_compiled_entities(self):
        from backend import afsim_continuous_motion as cm
        text,model=self.receipt();saved=copy.deepcopy(model);rows=cm.parse(text,model)
        self.assertEqual(set(rows),set(model['controls']));self.assertEqual(model,saved)

    def test_invalid_clock_cost_fatigue_and_position_never_create_a_candidate(self):
        from backend import afsim_continuous_motion as cm
        for field,bad in [('elapsed_ms',300001),('moving_ms',1),('fuel_spent_microliters',1),
                           ('fatigue_ticks',99999999),('lat',float('nan')),('mode',8)]:
            text,model=self.receipt(lambda r:r.update({field:bad}))
            with self.subTest(field=field),self.assertRaises(ValueError):cm.parse(text,model)

    def test_missing_duplicate_token_or_identity_is_rejected(self):
        from backend import afsim_continuous_motion as cm
        for options in [{'drop':True},{'duplicate':True},{'extra':'GTXCMODEL|other\n'},
                        {'extra':'GTXCMKINEMATIC|other|0\n'}]:
            text,model=self.receipt(**options)
            with self.subTest(options=options),self.assertRaises(ValueError):cm.parse(text,model)

    def test_native_error_is_rejected_even_if_closing_fields_balance(self):
        from backend import afsim_continuous_motion as cm
        text,model=self.receipt(extra='GTXERROR|failed_native_command\n')
        with self.assertRaisesRegex(ValueError,'原生过程'):cm.parse(text,model)

    def test_active_motion_cannot_be_duplicated_by_unimplemented_reorganization(self):
        from backend import afsim_continuous_motion as cm
        from gentactix import formation_conversion as fc
        from verify_formation_conversion import ConversionTests,damaged
        u=damaged();u['formation'].update(fatigue_carry_ticks=0,fuel_credit_microliters=0)
        u['formation']['motion_task']=cm.intent(u,{'action':'move','lat':u['lat']+.001,
            'lng':u['lng'],'intent_id':'a'*32},750000)
        saved=copy.deepcopy(u)
        with self.assertRaisesRegex(ValueError,'在途意图'):ConversionTests().split(u)
        self.assertEqual(u,saved)


if __name__=='__main__':unittest.main()
