"""Opt-in facility v2 must use real paths and native queue evidence."""
import copy,unittest
from unittest.mock import patch
from gentactix import combined_arms,missions
from backend import afsim_world
from verify_crossings import model


def fixture():
 spec=combined_arms.demo_definition();spec['id']='QA-crossing-v2';spec['map_center']={'lat':27.3,'lng':107.4};spec['map_radius_km']=5
 spec.update(objective={'lat':27.303,'lng':107.4},exit={'lat':27.304,'lng':107.4},deadline_turn=12,goal_radius_km=.05)
 spec['combined_rules'].update(air_support=False,motorized=False,command_base_s=0,command_signal_s=0,command_distance_s_per_km=0,
                             bridge_enabled=True,goal_profile='assault',required_survivors=1)
 cfg=spec['combined_rules'];w=spec['initial_state'];w['combined_arms']['rules_hash']=missions.digest(cfg)
 site=w['combined_arms']['bridge'];site.update(lat=27.3,lng=107.4,progress=100,integrity=100,capacity=2,used=0,crossing_model=model())
 for team in ('red','blue'):
  for i,u in enumerate(w[team+'_units']):
   u.update(lat=27.299 if team=='red' else 27.32,lng=107.4+i*.0002,speed=3)
   u['personnel'].update(committed=600,current=600)
   u['formation'].update(fatigue=0,suppression=0,motorized=False)
   for e in u['equipment']:e.update(committed=0,operational=0,damaged=0,destroyed=0)
  for node in w['supply_nodes']:
   if node['team']==team:node.update(lat=27.298 if team=='red' else 27.322,lng=107.4,stock=0)
 spec['rules']['move_km']=3
 return spec


class NativeCrossingTests(unittest.TestCase):
 def setUp(self):
  self.spec=fixture();original=missions.definition
  p=patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(self.spec) if i==self.spec['id'] else original(i));p.start();self.addCleanup(p.stop)
  self.world=missions.from_definition(copy.deepcopy(self.spec))

 def test_crossing_route_uses_both_banks_and_native_arrival_callbacks(self):
  u=self.world['red_units'][0];o={'unit':u['name'],'action':'move','lat':27.303,'lng':107.4}
  before=copy.deepcopy(self.world);scene=afsim_world.compile_scene(self.world,[o],1800,native_rules=True)
  self.assertIn('GtxCrossEnter',scene['script']);self.assertIn('GtxCrossExit',scene['script'])
  self.assertIn('GTXCROSS|',scene['script']);self.assertIn('GTXCROSSCAP|',scene['script'])
  entity=next(e for e in scene['entities'].values() if e['name']==u['name'])
  self.assertEqual(entity['waypoints'][0],self.spec['initial_state']['combined_arms']['bridge']['crossing_model']['banks']['a'])
  self.assertEqual(before,self.world)

 def test_new_goal_is_not_forced_to_the_east_of_the_facility(self):
  w=copy.deepcopy(self.world);w['red_units'][0].update(**self.spec['objective']);missions.evaluate(w)
  self.assertEqual(w['mission']['progress'],1)

 def test_legacy_scenes_do_not_gain_the_new_crossing_protocol(self):
  w=missions.initial('CA-AJ18-v1');scene=afsim_world.compile_scene(w,[],1800,native_rules=True)
  self.assertNotIn('GTXCROSS|',scene['script']);self.assertNotIn('crossing_model',scene['native_model']['before_combined']['bridge'])

 def test_crossing_objective_requires_completed_route_not_just_location(self):
  self.spec['combined_rules']['goal_profile']='crossing';self.spec['initial_state']['combined_arms']['rules_hash']=missions.digest(self.spec['combined_rules'])
  w=missions.from_definition(copy.deepcopy(self.spec));w['red_units'][0].update(**self.spec['objective']);missions.evaluate(w)
  self.assertEqual(w['mission']['progress'],0)
  scene=afsim_world.compile_scene(w,[],1800,native_rules=True)
  self.assertEqual(scene['motion_revision'],7);self.assertIn('redCrossed>=1',scene['script'])

 def test_historical_ingress_accepts_optional_model_and_freezes_it(self):
  from gentactix import historical_operations as op
  from tools.qa.historical_operational_fixture import inputs
  from backend.scenario_assembly import _merge_known
  snapshot,params=inputs();center=params['area']['center'];m=model()
  for key in ('barrier','banks'):
   for point in m[key].values():point['lat']+=center['lat']-27.3;point['lng']+=center['lng']-107.4
  params['facility'].update(**center,crossing_model=m,progress=100,integrity=100)
  params['rules'].update(bridge_enabled=True,goal_profile='crossing');params['goal']['profile']='crossing'
  merged=_merge_known(op.configuration_template(snapshot),{'facility':params['facility']})
  self.assertEqual(merged['facility']['crossing_model'],m)
  world=op.initial(snapshot,params);self.assertIn('完成登记通道渡运',op.goal_text(params));missions.validate(world)
  world['combined_arms']['bridge']['crossing_model']['throughput_work_per_hour']*=2
  with self.assertRaises(ValueError):missions.validate(world)

 def test_sourced_wujiang_phase_requires_crossing_not_generic_capture(self):
  from tools.qa.historical_crossing_fixture import inputs
  from gentactix import historical_operations as op
  snapshot,params=inputs();before=copy.deepcopy(snapshot);world=op.initial(snapshot,params)
  self.assertEqual(len(missions.units(world)),5);self.assertEqual(snapshot,before)
  self.assertTrue(all(f['value'] is None for u in snapshot['definition']['units'] for f in u['facts'].values()))
  params['facility'].pop('crossing_model');params['rules']['goal_profile']=params['goal']['profile']='assault'
  with self.assertRaisesRegex(ValueError,'本阶段主任务'):op.initial(snapshot,params)

 def test_new_process_requirement_is_typed_and_evidenced(self):
  from tools.qa.historical_crossing_fixture import inputs
  from gentactix import historical_initial as hi
  snapshot,_=inputs();definition=snapshot['definition']
  for kind in ('unsupported','no_source'):
   value=copy.deepcopy(definition);r=value['phases'][1]['process_requirements'][0]
   if kind=='unsupported':r['kind']='magical_water_physics'
   if kind=='no_source':r['evidence']=[]
   with self.subTest(kind=kind),self.assertRaises(ValueError):hi.validate_definition(value)

 def test_synthetic_derivation_keeps_crossing_and_source_facts(self):
  from tools.qa.historical_crossing_fixture import inputs
  from gentactix import historical_operations as op,synthetic_history
  snapshot,params=inputs();original=copy.deepcopy(snapshot);base=op.definition(snapshot,params)
  seed=synthetic_history.seed(base['historical_calculation']);seed['configuration']['teams']['red'][0]['personnel']=2000
  spec=synthetic_history.definition(base['historical_calculation'],seed['configuration']);world=missions.from_definition(spec)
  self.assertEqual(world['historical_initial'],original);self.assertEqual(world['red_units'][0]['personnel']['current'],2000)
  self.assertEqual(world['combined_arms']['bridge']['crossing_model'],params['facility']['crossing_model'])
  self.assertEqual(spec['combined_rules']['goal_profile'],'crossing')

 def test_post_bridge_initial_report_does_not_claim_a_battle_is_about_to_start(self):
  from tools.qa.historical_crossing_fixture import inputs
  from gentactix import historical_operations as op,reporting
  world=op.initial(*inputs());text,_=reporting.render(reporting.initial_status(world),world,turn=0)
  self.assertNotIn('战役即将打响',text);self.assertNotIn('教学规则结算',text)
  self.assertIn('历史部队',text)

if __name__=='__main__':unittest.main()
