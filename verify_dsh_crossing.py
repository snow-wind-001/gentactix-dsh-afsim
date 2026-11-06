"""DSH-only crossing proposals must obey the same frozen route/work boundaries."""
import copy,unittest
from unittest.mock import patch
from backend import dsh_simulation
from gentactix import crossings
import verify_afsim_crossing as native_fixture
from verify_dsh_resources import model_result


def proposal(world,done=300,complete=False,target=None):
 v=model_result(world);u=world['red_units'][0];target=target or {'lat':27.303,'lng':107.4};site=world['combined_arms']['bridge']
 plan=crossings.plan(site,u,target);previous=plan['task']['served_work'];events=[{'phase':'entered','seconds':1,**plan['entry']}]
 if complete:events.append({'phase':'exited','seconds':1500,**plan['exit']})
 v['orders'][0].update(action='move',**target)
 v['unit_updates'][0].update(**(target if complete else plan['entry']),crossing={'served_work':done,'last_work':done-previous,'status':'completed' if complete else 'queued','events':events})
 v['unit_updates'][0]['logistics']['food']-=2;v['resource_ledger']['units'][0]['food_spent']=4
 v['combined_arms']={'bridge':{'crossing_receipt':{'used_work':done-previous,'cargo_work':0,'budget_work':500}}}
 return v


class DSHCrossingTests(unittest.TestCase):
 def setUp(self):
  self.fixture=native_fixture.NativeCrossingTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.world=self.fixture.world

 def test_queue_and_cross_round_progress_do_not_teleport_the_formation(self):
  first=dsh_simulation.apply(self.world,proposal(self.world),'30分钟')
  self.assertEqual(first['red_units'][0]['crossing']['served_work'],300)
  self.assertEqual(first['red_units'][0]['lat'],27.299)
  second=dsh_simulation.apply(first,proposal(first,600,True),'30分钟')
  self.assertEqual(second['red_units'][0]['lat'],27.303)
  self.assertEqual(second['red_units'][0]['crossing']['source'],'dsh_model_estimate')

 def test_confirmed_move_and_fixed_branch_accept_valid_queue_without_claiming_arrival(self):
  from gentactix import commands
  session={'id':'qa-crossing','war_state':self.world,'turn_count':0,'time_step':'30分钟','simulation_mode':'open','execution_backend':'narrative'}
  row=commands.view(session)['units'][0];view=commands.view(session)
  session['command_state']=commands.replace_queue(session,[{'unit_id':row['id'],'action':'move','destination':{'lat':27.303,'lng':107.4},'duration':'next'}],control_team='red',director=False,no_fire=False,intent='')
  prepared=commands.prepare(session);value=proposal(self.world)
  with patch.object(dsh_simulation.h,'get_ai_response',return_value=value):
   result,orders,_=dsh_simulation.advance(session,prepared,None)
  state,_=commands.finish(session,prepared,result['updated_state'],executed=orders)
  receipt=next(r for r in state['receipts'] if r['unit_id']==row['id'])
  self.assertEqual(receipt['status'],'blocked');self.assertIn('渡运',receipt['reason'])
  self.assertEqual(receipt['crossing']['served_work'],300)
  with patch.object(dsh_simulation.h,'get_ai_response',return_value=value):
   branch,_,_=dsh_simulation.advance(session,None,None,fixed_orders=value['orders'])
  self.assertEqual(branch['updated_state']['red_units'][0]['crossing']['status'],'queued')

 def test_prompt_supplies_effective_speed_and_gate_arrival_bounds(self):
  from tools.qa.historical_crossing_fixture import inputs
  from gentactix import historical_operations as ho
  world=ho.initial(*inputs());observation=crossings.observation(world)
  limit=observation['unit_limits'][0]
  self.assertEqual(limit['move_budget_km'],1);self.assertGreaterEqual(limit['entry_earliest_s']['a'],139)
  self.assertGreaterEqual(limit['bank_travel_min_s'],119)
  self.assertIn('crossing_constraints',dsh_simulation.prompt(world))

 def test_retry_carries_the_rejected_typed_draft_without_changing_world(self):
  bad=proposal(self.world);bad['unit_updates'][0]['crossing']['events'][0]['seconds']=1799;original=copy.deepcopy(self.world)
  with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,proposal(self.world)]) as model:
   result,_,_=dsh_simulation.advance({'war_state':self.world,'time_step':'30分钟'},None,None)
  self.assertEqual(model.call_count,2);self.assertIn('上次候选（未执行的模型草稿',model.call_args.args[0])
  self.assertIn('resource_ledger',model.call_args.args[0]);self.assertEqual(self.world,original)
  self.assertEqual(result['updated_state']['red_units'][0]['crossing']['served_work'],300)

 def test_malformed_draft_does_not_crash_the_existing_retry(self):
  bad=proposal(self.world);bad.update(unit_updates=None,combined_arms='invalid model field')
  with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,proposal(self.world)]):
   result,_,_=dsh_simulation.advance({'war_state':self.world,'time_step':'30分钟'},None,None)
  self.assertEqual(result['updated_state']['red_units'][0]['crossing']['served_work'],300)

 def test_persistent_far_move_keeps_the_same_crossing_task_until_serviced(self):
  from gentactix import commands
  s={'id':'qa-crossing','war_state':self.world,'turn_count':0,'time_step':'30分钟','simulation_mode':'open','execution_backend':'narrative'}
  row=commands.view(s)['units'][0]
  s['command_state']=commands.replace_queue(s,[{'unit_id':row['id'],'action':'move','destination':{'lat':27.33,'lng':107.4},'duration':'until_arrived'}],control_team='red',director=False,no_fire=False,intent='')
  first=commands.prepare(s);order=first['manual'][0]['order'];target={k:order[k] for k in ('lat','lng')}
  v=proposal(self.world,target=target);after=dsh_simulation.apply(self.world,v,'30分钟')
  commands.verify_open(s,first,after);cs,_=commands.finish(s,first,after,executed=v['orders'])
  s.update(command_state=cs,war_state=after,turn_count=1)
  again=commands.prepare(s)['manual'][0]['order']
  self.assertEqual({k:again[k] for k in ('lat','lng')},target)
  self.assertEqual(crossings.plan(after['combined_arms']['bridge'],after['red_units'][0],again)['task']['served_work'],300)

 def test_missing_receipt_unpaid_crossing_or_extra_capacity_rejects(self):
  for kind in ('missing_task','missing_ledger','teleport','capacity','wrong_site','no_entry','unpaid_transit','late_entry','closed'):
   v=proposal(self.world)
   if kind=='missing_task':v['unit_updates'][0].pop('crossing')
   if kind=='missing_ledger':v.pop('combined_arms')
   if kind=='teleport':v['unit_updates'][0]['lat']=27.303
   if kind=='capacity':v['unit_updates'][0]['crossing'].update(served_work=550,last_work=550);v['combined_arms']['bridge']['crossing_receipt']['used_work']=550
   if kind=='wrong_site':v['unit_updates'][0]['crossing']['site_id']='invented'
   if kind=='no_entry':v['unit_updates'][0]['crossing']['events']=[]
   if kind=='unpaid_transit':v['unit_updates'][0]['crossing'].update(served_work=600,last_work=600,status='queued');v['unit_updates'][0]['lat']=27.3005;v['combined_arms']['bridge']['crossing_receipt']['used_work']=600
   if kind=='late_entry':v['unit_updates'][0]['crossing']['events'][0]['seconds']=1799
   world=copy.deepcopy(self.world)
   if kind=='closed':world['combined_arms']['bridge']['progress']=0
   with self.subTest(kind=kind),self.assertRaises(ValueError):dsh_simulation.apply(world,v,'30分钟')

 def test_open_service_cannot_stall_all_confirmed_moves_by_omitting_entry_events(self):
  v=proposal(self.world,0);v['unit_updates'][0]['crossing']['events']=[]
  with self.assertRaisesRegex(ValueError,'服务'):dsh_simulation.apply(self.world,v,'30分钟')

 def test_closed_facility_can_legitimately_return_zero_service(self):
  world=copy.deepcopy(self.world);world['combined_arms']['bridge']['progress']=0
  v=proposal(world,0);v['unit_updates'][0]['crossing']['events']=[]
  after=dsh_simulation.apply(world,v,'30分钟')
  self.assertEqual(after['red_units'][0]['crossing']['served_work'],0)

 def test_crossing_cargo_receipt_matches_gross_delivery_and_shared_work(self):
  self.fixture.spec['initial_state']['red_units'][0]['equipment'][-1].update(committed=10,operational=10)
  world=native_fixture.missions.from_definition(copy.deepcopy(self.fixture.spec));u=world['red_units'][0];u.update(lat=27.303,lng=107.4)
  world['supply_nodes'][0]['stock']=10
  v=model_result(world);v['resource_ledger']['units'][0].update(delivery=2,supply_status='未切断')
  v['unit_updates'][0].update(logistics={'food':u['logistics']['food'],'ammo':u['logistics']['ammo']+2})
  v['supply_nodes']=copy.deepcopy(world['supply_nodes']);v['supply_nodes'][0]['stock']-=2
  v['combined_arms']={'bridge':{'crossing_receipt':{'used_work':0,'cargo_work':200,'budget_work':500}}}
  actual=dsh_simulation.apply(world,v,'30分钟')
  self.assertEqual(actual['combined_arms']['bridge']['crossing_receipt']['cargo_work'],200)
  for bad in ('wrong_work','no_transport','closed'):
   prior=copy.deepcopy(world);wrong=copy.deepcopy(v)
   if bad=='wrong_work':wrong['combined_arms']['bridge']['crossing_receipt']['cargo_work']=0
   if bad=='no_transport':prior['red_units'][0]['equipment'][-1].update(operational=0,damaged=10)
   if bad=='closed':prior['combined_arms']['bridge']['integrity']=0
   with self.subTest(bad=bad),self.assertRaises(ValueError):dsh_simulation.apply(prior,wrong,'30分钟')

 def test_construction_is_bounded_by_engineer_hours_and_materials(self):
  initial=self.fixture.spec['initial_state'];initial['combined_arms']['bridge'].update(progress=0,integrity=0)
  initial['red_units'][0]['equipment'][3].update(committed=6,operational=6)
  initial['red_units'][0]['formation']['materials']=20
  world=native_fixture.missions.from_definition(copy.deepcopy(self.fixture.spec));v=model_result(world)
  v['orders'][0]['action']='build_bridge';v['unit_updates'][0]['formation'].update(materials=14)
  v['resource_ledger']['units'][0]['spent']={'materials':6}
  v['combined_arms']={'bridge':{'progress':30,'integrity':30,'materials':world['combined_arms']['bridge']['materials']-6}}
  result=dsh_simulation.apply(world,v,'30分钟');self.assertEqual(result['combined_arms']['bridge']['progress'],30)
  for bad in ('free','too_fast','no_order'):
   wrong=copy.deepcopy(v)
   if bad=='free':wrong['unit_updates'][0]['formation']['materials']=20;wrong['resource_ledger']['units'][0]['spent']={};wrong['combined_arms']['bridge']['materials']=world['combined_arms']['bridge']['materials']
   if bad=='too_fast':wrong['combined_arms']['bridge'].update(progress=60,integrity=60)
   if bad=='no_order':wrong['orders'][0]['action']='hold'
   with self.subTest(bad=bad),self.assertRaises(ValueError):dsh_simulation.apply(world,wrong,'30分钟')

if __name__=='__main__':unittest.main()
