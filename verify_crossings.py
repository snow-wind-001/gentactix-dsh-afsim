"""Finite river geometry and frozen formation-service contracts."""
import copy,unittest
from gentactix import crossings


def model():
 return {'version':'formation-crossing-1','barrier':{'a':{'lat':27.3,'lng':107.35},'b':{'lat':27.3,'lng':107.45}},
  'banks':{'a':{'lat':27.299,'lng':107.4},'b':{'lat':27.301,'lng':107.4}},
  'throughput_work_per_hour':1000,'equipment_work':{'armor':10,'artillery':5,'air_defense':5,'engineer':0,'transport':2},
  'build_progress_per_engineer_hour':10,'supply_work_per_unit':100,'assumption':'QA估计河线和能力，不是1935年河槽、历史渡口或交通标定。'}


class CrossingTests(unittest.TestCase):
 def test_confirmed_intent_resumes_but_cancelled_and_reissued_intent_restarts(self):
  site={'id':'qa','crossing_model':model()};u={'name':'QA','lat':27.299,'lng':107.4,'personnel':{'current':600},'equipment':[]}
  target={'lat':27.303,'lng':107.4,'intent_id':'a'*32};first=crossings.plan(site,u,target)
  self.assertEqual(first['task']['intent_id'],'a'*32)
  u['crossing']={**first['task'],'served_work':300,'last_work':300,'turn':1,'source':'afsim_native_estimate'}
  self.assertEqual(crossings.plan(site,u,target)['task']['served_work'],300)
  restarted=crossings.plan(site,u,{**target,'intent_id':'b'*32})
  self.assertEqual(restarted['task']['served_work'],0)
  self.assertEqual(restarted['task']['intent_id'],'b'*32)

 def test_in_channel_retask_cannot_undo_the_serviced_work_or_return_instantly(self):
  site={'id':'qa','crossing_model':model()};u={'name':'QA','lat':27.299,'lng':107.4,'personnel':{'current':600},'equipment':[]}
  first=crossings.plan(site,u,{'lat':27.303,'lng':107.4,'intent_id':'a'*32})
  u['lat']=27.3002;u['crossing']={**first['task'],'served_work':600,'last_work':600,'status':'transit','turn':1,'source':'afsim_native_estimate'}
  continued=crossings.plan(site,u,{'lat':27.303,'lng':107.4,'intent_id':'b'*32})
  self.assertEqual(continued['task']['served_work'],600);self.assertFalse(continued['enter_required'])
  with self.assertRaisesRegex(ValueError,'抵岸'):crossings.plan(site,u,{'lat':27.298,'lng':107.4,'intent_id':'b'*32})

 def test_horizontal_and_rotated_barriers_do_not_depend_on_longitude(self):
  m=model();crossings.validate_model(m)
  self.assertTrue(crossings.intersects({'lat':27.299,'lng':107.4},{'lat':27.301,'lng':107.4},m))
  self.assertFalse(crossings.intersects({'lat':27.299,'lng':107.399},{'lat':27.299,'lng':107.401},m))
  self.assertFalse(crossings.intersects({'lat':27.299,'lng':107.5},{'lat':27.301,'lng':107.5},m))
  m['barrier']={'a':{'lat':27.29,'lng':107.39},'b':{'lat':27.31,'lng':107.41}}
  m['banks']={'a':{'lat':27.299,'lng':107.401},'b':{'lat':27.301,'lng':107.399}}
  self.assertTrue(crossings.intersects(m['banks']['a'],m['banks']['b'],m));crossings.validate_model(m)

 def test_invalid_geometry_and_nonphysical_rates_are_rejected(self):
  for kind in ('same_bank','zero_line','zero_rate','nan','boolean','missing_explanation'):
   m=model()
   if kind=='same_bank':m['banks']['b']=copy.deepcopy(m['banks']['a'])
   if kind=='zero_line':m['barrier']['b']=copy.deepcopy(m['barrier']['a'])
   if kind=='zero_rate':m['throughput_work_per_hour']=0
   if kind=='nan':m['banks']['a']['lat']=float('nan')
   if kind=='boolean':m['build_progress_per_engineer_hour']=True
   if kind=='missing_explanation':m['assumption']=''
   with self.subTest(kind=kind),self.assertRaises(ValueError):crossings.validate_model(m)

 def test_task_route_resumes_same_work_but_cannot_reuse_for_a_new_destination(self):
  m=model();unit={'name':'QA','lat':27.299,'lng':107.4,'personnel':{'current':600},'equipment':[]}
  site={'id':'qa-site','crossing_model':m};target={'lat':27.302,'lng':107.4}
  first=crossings.plan(site,unit,target);self.assertEqual(first['task']['required_work'],600)
  task=first['task'];task.update(served_work=300,status='queued',last_work=300,turn=1,source='afsim_native_estimate',events=[])
  unit['crossing']=task;again=crossings.plan(site,unit,target)
  self.assertEqual(again['task']['served_work'],300);self.assertTrue(again['enter_required'])
  changed=crossings.plan(site,unit,{'lat':27.302,'lng':107.401})
  self.assertEqual(changed['task']['served_work'],0)
  unit['crossing'].update(served_work=600,status='transit');unit['lat']=27.3005
  continued=crossings.plan(site,unit,target)
  self.assertFalse(continued['enter_required']);self.assertNotIn(m['banks']['a'],continued['waypoints'])

 def test_work_is_an_explicit_capacity_measure_not_extra_or_missing_personnel(self):
  m=model();unit={'name':'QA','lat':27.299,'lng':107.4,'personnel':{'current':600},
   'equipment':[{'category':'artillery','operational':4},{'category':'transport','operational':2}]}
  self.assertEqual(crossings.required_work(unit,m),624)
  before=copy.deepcopy(unit);crossings.plan({'id':'qa','crossing_model':m},unit,{'lat':27.302,'lng':107.4})
  self.assertEqual(before,unit)

if __name__=='__main__':unittest.main()
