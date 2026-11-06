"""Event-bound Native work preview; not complete campaign admission."""
import copy
import re
import unittest

from backend import afsim_continuous_motion as motion, afsim_rules, afsim_shared_fortification as native
from gentactix import formation_registry, missions
from verify_afsim_shared_fortification import output
from verify_continuous_motion_integration import compile_world
from verify_shared_fortification import control, changed_state, receipt


def event_text(model,segments,materials,current):
    lines=[]
    for start,stock,people,row in segments:
        values={**{k:v for k,v in row.items()if k!='after'},**row['after'],'current':people}
        lines.append('GTXSFWSEG|'+row['entity_id']+'|'+str(start)+'|'+str(start+row['elapsed_ms'])+'|'+str(stock)+'|'+'|'.join(str(values[k])for k in native.FIELDS))
    identity=model['controls'][0]['entity_id']
    lines.append('GTXSFWEND|'+identity+'|'+str(materials)+'|'+str(current))
    lines.append('GTXSFWEVENTMETA|'+model['binding_digest'])
    return '\n'.join(lines)


def world_binding():
    from verify_continuous_motion import CONFIG
    from backend import afsim_world
    from tools.qa.historical_operational_fixture import inputs
    from gentactix import historical_operations as ho
    from verify_support_dynamics import config as support_config
    from verify_split_supply import config as split_config
    from verify_supply_schedule import config as schedule_config
    source,parameters=inputs()
    parameters.update(movement_feedback=copy.deepcopy(CONFIG),
        fire_dynamics={'version':'live-footprint-density-2','assumption':CONFIG['assumption']},
        support_dynamics=support_config(),supply_distribution=split_config(),supply_schedule=schedule_config())
    parameters['rules'].update(command_base_s=30,command_signal_s=0,command_distance_s_per_km=0)
    value=ho.initial(source,parameters)
    team,unit=missions.units(value)[0]
    orders=[{'unit':unit['name'],'action':'fortify'}]
    scene=afsim_world.compile_scene({team+'_units':copy.deepcopy(value[team+'_units'])for team in ('red','blue')},orders,300)
    identity=next(i for i,e in scene['entities'].items()if e['name']==unit['name'])
    c=control();c.update(entity_id=identity,current=unit['personnel']['current'],materials=unit['formation']['materials'],command_delay_ms=30000)
    c['state'].update(root_id=formation_registry.key(team,unit),root_committed=unit['personnel']['committed'],committed=unit['personnel']['committed'],site_id=native.site_identity(unit['lat'],unit['lng']),intent_id=None)
    return value,scene,c,orders


class EventWorkTests(unittest.TestCase):
    def compile(self,c=None,ms=3600000):
        c=c or control()
        site={c['entity_id']:{'lat':29.0,'lng':115.0}}
        c=copy.deepcopy(c);c['state']['site_id']=native.site_identity(29.0,115.0)
        return native.compile_events([c],ms,site)

    def test_clock_is_closed_before_motion_and_uses_one_physical_stock(self):
        value,scene,c,orders=world_binding()
        model=afsim_rules.compile_model(scene,value,orders,shared_work_controls=[c])
        compiled=model['continuous_motion'];script=model['script']
        self.assertLess(script.index(' GtxSharedFortificationSettle(a);'),script.index(' double mode=GtxCMGet(a,"mode");'))
        self.assertIn('GTXSFWSEG|',script)
        self.assertIn('ca_materials',script)
        self.assertNotIn('gfw_materials"',script)
        self.assertIn('ca_entrenchment',script)
        self.assertIn('shared_fortification',compiled)
        old=afsim_rules.compile_model(scene,value,orders)
        gain=value['mission']['definition']['combined_rules']['fortify_gain']
        legacy=r'Math\.Min\(100,[A-Za-z]+\d+\.AuxDataDouble\("ca_entrenchment"\)\+'+str(gain)+r'\)'
        self.assertIsNotNone(re.search(legacy,old['script']),'control program really contains the legacy increment')
        self.assertIsNone(re.search(legacy,model['script']),'event work must not also execute legacy fortify')

    def test_personnel_changes_do_not_backdate_over_the_old_interval(self):
        bound=self.compile();c=bound['model']['controls'][0];identity=c['entity_id']
        a=changed_state(base_ticks=20000000,material_credit_work=60000,site_id=c['state']['site_id'])
        first=receipt(a,elapsed=1800000,paid=60000*3600000,added=60000,materials=15);first['entity_id']=identity
        b=changed_state(base_ticks=25000000,material_credit_work=30000,site_id=c['state']['site_id'])
        second=receipt(b,elapsed=1800000,paid=30000*3600000,added=30000,reserved=0,materials=15);second['entity_id']=identity
        raw=event_text(bound['model'],[(0,16,6000,first),(1800000,15,3000,second)],15,3000)
        result=native.parse_events(raw,bound['model'])
        self.assertEqual(result[identity]['after'],b)
        self.assertEqual(result[identity]['paid_work_numerator'],90000*3600000)
        self.assertEqual(result[identity]['materials_after'],15)

    def test_late_material_arrival_cannot_fund_earlier_work(self):
        bound=self.compile(control(materials=0));c=bound['model']['controls'][0];sid=c['state']['site_id']
        a=changed_state(site_id=sid)
        first=receipt(a,elapsed=1800000,paid=0,added=0,reserved=0,materials=0,productive=0)
        b=changed_state(base_ticks=20000000,material_credit_work=60000,site_id=sid)
        second=receipt(b,elapsed=1800000,paid=60000*3600000,added=60000,reserved=1,materials=0)
        raw=event_text(bound['model'],[(0,0,6000,first),(1800000,1,6000,second)],0,6000)
        with self.assertRaises(ValueError):native.parse_events(raw,bound['model'])
        result=native.parse_events(raw,bound['model'],material_events={c['entity_id']:[{'at_ms':1800000,'received':1}]})
        self.assertEqual(result[c['entity_id']]['after']['base_ticks'],20000000)

    def test_segment_gaps_duplicates_unknown_people_or_end_stock_are_rejected(self):
        bound=self.compile();c=bound['model']['controls'][0]
        state=changed_state(base_ticks=30000000,site_id=c['state']['site_id']);r=receipt(state)
        raw=event_text(bound['model'],[(0,16,6000,r)],15,6000)
        self.assertTrue(native.parse_events(raw,bound['model']))
        row=raw.splitlines()[0]
        for bad in [raw.replace('|0|3600000|','|1|3600000|'),raw+'\n'+row,raw.replace('|16|3600000|','|16|3599999|'),raw.replace('GTXSFWEND|'+c['entity_id']+'|15|','GTXSFWEND|'+c['entity_id']+'|16|')]:
            with self.subTest(bad=bad[-80:]),self.assertRaises(ValueError):native.parse_events(bad,bound['model'])

    def test_binding_rejects_wrong_source_root_site_stock_action_or_strength(self):
        value,scene,c,orders=world_binding()
        for field,new in [('root_id','f'*64),('site_id','f'*64),('root_committed',7000)]:
            bad=copy.deepcopy(c);bad['state'][field]=new
            with self.subTest(field=field),self.assertRaises(ValueError):afsim_rules.compile_model(scene,value,orders,shared_work_controls=[bad])
        for field,new in [('current',c['current']-1),('materials',c['materials']-1),('command_delay_ms',0)]:
            bad=copy.deepcopy(c);bad[field]=new
            with self.subTest(field=field),self.assertRaises(ValueError):afsim_rules.compile_model(scene,value,orders,shared_work_controls=[bad])
        with self.assertRaises(ValueError):afsim_rules.compile_model(scene,value,[],shared_work_controls=[c])

    def test_continuing_work_does_not_repeat_c2_wait(self):
        value,scene,c,orders=world_binding();c['state'].update(intent_id=c['intent_id'],wait_remaining_ms=7000)
        model=afsim_rules.compile_model(scene,value,orders,shared_work_controls=[c])
        self.assertTrue('SetAuxData("ca_delay_s",(double)(7))'in model['script'],'continued C2 uses seven seconds')
        self.assertIn('"waiting",7000', '\n'.join(model['continuous_motion']['shared_fortification']['setup_lines']))

    def test_preview_cannot_be_accepted_as_complete_world_effects(self):
        value,scene,c,orders=world_binding();model=afsim_rules.compile_model(scene,value,orders,shared_work_controls=[c])
        from backend import afsim_combined
        with self.assertRaisesRegex(ValueError,'共享施工.*未.*验收'):
            afsim_combined.parse('',model,scene)

    def test_fractional_work_carries_while_physical_integer_entrenchment_agrees(self):
        value,scene,c,orders=world_binding();c['state'].update(base_ticks=10333333,point_remainder=2000)
        model=afsim_rules.compile_model(scene,value,orders,shared_work_controls=[c])
        state=model['continuous_motion']['shared_fortification']['model']['controls'][0]['state']
        self.assertEqual(state['base_ticks'],10333333)
        self.assertEqual(state['point_remainder'],2000)

    def test_work_receipt_cannot_be_interpreted_as_a_legacy_motion_result(self):
        _,_,_,model=compile_world()
        with self.assertRaisesRegex(ValueError,'没有绑定'):
            motion.parse('GTXSFWSEG|foreign',model['continuous_motion'])

    def test_work_configuration_is_part_of_the_normal_world_input_digest(self):
        value,scene,c,orders=world_binding()
        first=afsim_rules.compile_model(scene,value,orders,shared_work_controls=[c])
        c['configuration']['gain_points_per_worker_hour']+=1
        second=afsim_rules.compile_model(scene,value,orders,shared_work_controls=[c])
        self.assertNotEqual(first['input_digest'],second['input_digest'])
        self.assertNotEqual(first['continuous_motion']['token'],second['continuous_motion']['token'])

    def test_existing_default_native_program_is_unchanged_by_opt_in_keyword(self):
        value,orders,scene,old=compile_world()
        saved=copy.deepcopy((value,orders,scene,old))
        self.assertEqual(afsim_rules.compile_model(scene,value,orders,shared_work_controls=None),old)
        self.assertEqual((value,orders,scene,old),saved)


if __name__=='__main__':unittest.main(verbosity=2)
