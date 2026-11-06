"""Regimental models must have real contracts before the native implementation."""
import copy
import unittest
from gentactix import combined_arms, missions, commands
from backend import afsim_world


class CombinedTests(unittest.TestCase):
    def setUp(self):
        self.spec=combined_arms.demo_definition()
        self.world=missions.initial(self.spec['id'])

    def test_all_catalog_battles_have_era_appropriate_model(self):
        specs=combined_arms.catalog()
        self.assertEqual(len(specs),45)
        for spec in specs:
            world=missions.initial(spec['id']);combined_arms.validate(world)
            self.assertIn('教学',spec['assumptions'])
            if spec['combined_rules']['era']=='ancient':
                self.assertEqual(sum(e['operational'] for _,u in missions.units(world) for e in u['equipment'] if e['category'] in ('armor','artillery','air_defense')),0)
                self.assertFalse(combined_arms.air_enabled(world))

    def test_classified_equipment_and_state_are_conserved(self):
        combined_arms.validate(self.world)
        categories={e['category'] for e in self.world['red_units'][0]['equipment']}
        self.assertEqual(categories,{'armor','artillery','air_defense','engineer','transport'})
        self.assertGreater(self.world['red_units'][0]['personnel']['current'],100)
        self.assertIn('intel_age_min',self.world['red_units'][0]['formation'])

    def test_native_scene_owns_equipment_and_facility_calculations(self):
        before=copy.deepcopy(self.world)
        scene=afsim_world.compile_scene(self.world,[],1800,native_rules=True)
        self.assertIn('GTXCEQUIP|',scene['script'])
        self.assertIn('GTXCFAC|',scene['script'])
        self.assertIn('GtxCAAirDefense',scene['script'])
        self.assertEqual(before,self.world)

    def test_no_shells_or_no_engineers_disable_their_actions(self):
        u=self.world['red_units'][2]
        self.assertIn('bombard',combined_arms.actions(self.world,u,'red'))
        u['formation']['shells']=0
        self.assertNotIn('bombard',combined_arms.actions(self.world,u,'red'))
        next(e for e in u['equipment'] if e['category']=='engineer').update(operational=0,destroyed=6)
        self.assertNotIn('build_bridge',combined_arms.actions(self.world,u,'red'))

    def test_legacy_python_executor_cannot_replace_combined_native_model(self):
        with self.assertRaisesRegex(ValueError,'AFSIM'):missions.advance(self.world,[],'30分钟')

    def test_tampered_model_or_inventory_is_rejected(self):
        for mutate in (lambda w:w['combined_arms'].update(rules_hash='bad'),
                       lambda w:w['red_units'][0]['equipment'][0].update(operational=10000)):
            w=copy.deepcopy(self.world);mutate(w)
            with self.assertRaises(ValueError):combined_arms.validate(w)

    def session(self):
        return {'id':'c01234567890','war_state':self.world,'time_step':'30分钟','turn_count':0,
                'simulation_mode':'open','execution_backend':'afsim'}

    def test_native_action_validation_is_read_only(self):
        from backend import agent_tools
        s=self.session();v=commands.view(s);red=next(u for u in v['units'] if u['team']=='red')
        before=copy.deepcopy(s)
        result=agent_tools.execute_tool_call(s,self.world,{'tool':'evaluate_action','args':{
            'orders':[{'unit_id':red['id'],'action':'build_bridge','duration':'next'}]}})
        self.assertFalse(result['all_valid'])
        self.assertIn('700',result['checks'][0]['reason'])
        self.assertEqual(s,before)

    def test_waiting_for_bridge_does_not_falsely_complete_continuous_order(self):
        s=self.session();v=commands.view(s);red=next(u for u in v['units'] if u['team']=='red')
        b=self.world['combined_arms']['bridge']
        draft={'unit_id':red['id'],'action':'move','duration':'until_arrived',
               'destination':{'lat':b['lat'],'lng':b['lng']+.004}}
        s['command_state']=commands.replace_queue(s,[draft],control_team='red',director=False,no_fire=False,intent='')
        prepared=commands.prepare(s);after=copy.deepcopy(self.world)
        after['red_units'][0]['formation']['last_execution']={'turn':1,'blocked':1}
        result,_=commands.finish(s,prepared,after,executed=[prepared['manual'][0]['order']])
        self.assertEqual(result['orders'][0]['status'],'executing')
        self.assertIn('桥梁未开放',result['orders'][0]['reason'])

    def test_no_fire_also_blocks_artillery(self):
        s=self.session();view=commands.view(s)
        actor=next(u for u in view['units'] if u['name']==self.world['red_units'][2]['name'])
        target=next(u for u in view['units'] if u['team']=='blue')
        with self.assertRaises(ValueError):commands.replace_queue(s,[{'unit_id':actor['id'],'action':'bombard','target_id':target['id'],'duration':'next'}],control_team='red',director=False,no_fire=True,intent='')


if __name__=='__main__':unittest.main()
