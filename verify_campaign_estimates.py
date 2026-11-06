"""Numerical priors constrain generated inputs without becoming historical facts."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi, historical_operations as ho, campaign_windows as cw
from tools.upgrade_wanjialing import BATTLE


class CampaignEstimateTests(unittest.TestCase):
    def test_optional_goal_regions_reject_another_direction_inside_the_whole_area(self):
        from gentactix import campaign_estimates as ce
        from tools.qa.wanjialing_estimate_fixture import inputs
        s,p=inputs();cfg=p['campaign_scope']['window']['definition']['parameter_estimates']
        regional=[n for n in p['campaign_plan']['nodes']if 'region'in n['condition']]
        cfg['goal_regions']={n['id']:dict(center=copy.deepcopy(n['condition']['region']['center']),
            radius_km=n['condition']['region']['radius_km']+.5,assumption='仅QA方向范围，非历史阵位')for n in regional}
        ce.validate_definition(cfg,p['campaign_scope']['window']['definition'],s,list(p['actors']))
        ce.validate_parameters(s,p)
        node=regional[0];region=node['condition']['region'];center=region['center']
        choices=[dict(lat=center['lat']+a,lng=center['lng']+b)for a,b in [(0.08,0),(-0.08,0),(0,.08),(0,-.08)]]
        from gentactix import missions
        wrong=next(point for point in choices if missions.distance(point,p['area']['center'])+region['radius_km']<p['area']['radius_km'])
        region['center']=wrong;before=copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError,'目标地域超出.*'+node['id']):ce.validate_parameters(s,p)
        self.assertEqual(p,before,'validation cannot move the goal into a valid direction')

    def test_optional_goal_regions_reject_unknown_nodes_and_invalid_envelopes(self):
        from gentactix import campaign_estimates as ce
        from tools.qa.wanjialing_estimate_fixture import inputs
        for invalid in ['unknown_node','outside_area']:
            s,p=inputs();window=p['campaign_scope']['window']['definition'];cfg=window['parameter_estimates']
            node=next(n for n in p['campaign_plan']['nodes']if 'region'in n['condition'])
            cfg['goal_regions']={node['id']if invalid!='unknown_node'else 'unknown':dict(
                center=copy.deepcopy(cfg['area']['center']),radius_km=cfg['area']['radius_km']+1 if invalid=='outside_area'else 1,
                assumption='QA估计边界')}
            with self.subTest(invalid=invalid),self.assertRaisesRegex(ValueError,'目标地域'):
                ce.validate_definition(cfg,window,s,list(p['actors']))

    def test_new_motion_window_preserves_all_source_and_numerical_priors_and_is_required(self):
        from backend import scenario_builder as sb, scenario_assembly as sa
        from gentactix import movement_feedback as mf
        from tools.build_wanjialing_motion import build
        before=cw.load('WJL-oct6-10','1.4.0');new=build()
        self.assertEqual(cw.load('WJL-oct6-10','1.5.0'),new)
        self.assertEqual(new['historical_initial'],before['historical_initial'])
        self.assertEqual(new['units'],before['units'])
        self.assertEqual(new['parameter_estimates']['actors'],before['parameter_estimates']['actors'])
        old_globals=before['parameter_estimates']['global_priors']
        self.assertEqual({k:v for k,v in new['parameter_estimates']['global_priors'].items() if k!='movement_feedback'},old_globals)
        b=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',
            campaign_window_version='1.5.0',termination_mode='objectives',time_step='1小时')
        p=b['configuration_template'];w=ho.initial(b['initial'],p)
        self.assertEqual(len(mf.observation(w)['units']),22)
        a=sa.create(b);self.addCleanup(sa.close,a.id)
        result=a.tool('globals','update_scenario_configuration',{'revision':0,'patch':{'assumptions':'显式核对新计算规则；非历史标定'}})
        self.assertTrue(result['updated'],result)
        for part in a.parts:
            result=a.tool(part,'update_scenario_configuration',{'revision':a.revision,
                'patch':{'actors':{i:{'assumption':p['actors'][i]['assumption']} for i in a.assigned(part)}}})
            self.assertTrue(result['updated'],result)
        self.assertTrue(a.tool('final','validate_scenario_configuration',{})['valid'])
        p=copy.deepcopy(p);p.pop('movement_feedback')
        with self.assertRaisesRegex(ValueError,'运动反馈|movement-feedback'):ho.initial(b['initial'],p)
        old=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',
            campaign_window_version='1.4.0',termination_mode='objectives',time_step='1小时')
        self.assertNotIn('movement_feedback',old['configuration_template'])

    def setUp(self):
        self.pin=cw.pin('WJL-oct6-10','1.1.0')
        self.s=hi.initial(BATTLE,'oct6_orders',version='1.3.0')['historical_initial']

    def test_new_window_carries_explicit_priors_over_the_same_unknown_source(self):
        e=self.pin['definition']['parameter_estimates']
        self.assertEqual(e['version'],'campaign-estimates-1')
        self.assertFalse(e['historically_calibrated'])
        self.assertEqual(set(e['actors']),set(cw.select(self.s,self.pin)))
        self.assertTrue(all(u['facts']['personnel']['value'] is None and u['facts']['equipment']['value'] is None
                            for u in self.s['definition']['units']))

    def test_objective_mode_gets_both_sides_and_time_sustainment_templates(self):
        from backend.scenario_builder import historical_basis
        b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version='1.1.0',termination_mode='objectives')
        p=b['configuration_template'];self.assertIn('campaign_plan',p);self.assertIn('support_dynamics',p)
        self.assertEqual({n['team'] for n in p['campaign_plan']['nodes']},{'red','blue'})
        self.assertTrue(all(a['personnel'] is None for a in p['actors'].values()))
        self.assertTrue(all(p['support_dynamics'][k] is None for k in ('food_work_per_hour','move_factor')))
        self.assertTrue(all(a['window_scope']['parameter_estimates'] for a in b['actors']))

    def test_legacy_window_and_deadline_mode_do_not_silently_gain_objective_graph(self):
        from backend.scenario_builder import historical_basis
        for version,mode in [('1.0.0','objectives'),('1.1.0','deadline')]:
            b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version=version,termination_mode=mode)
            self.assertNotIn('campaign_plan',b['configuration_template'])

    def test_explicit_inputs_form_a_world_and_restore_without_current_registries(self):
        from tools.qa.wanjialing_estimate_fixture import inputs
        s,p=inputs();w=ho.initial(s,p)
        self.assertEqual(len(w['red_units'])+len(w['blue_units']),22)
        self.assertEqual(set(w['campaign_plan']['outcomes']),{'red','blue'})
        with patch.object(cw,'load',side_effect=AssertionError('frozen restore must not load live priors')):
            self.assertEqual(ho.from_binding(w['mission']['definition']['historical_calculation']),w['mission']['definition'])

    def test_strength_equipment_deployment_and_missing_sustainment_are_rejected(self):
        from tools.qa.wanjialing_estimate_fixture import inputs
        for kind in ('strength','equipment','position','sustainment','goal'):
            s,p=inputs();i='ww2.cn.artillery1.company6'
            if kind=='strength':p['actors'][i]['personnel']=8000
            if kind=='equipment':p['actors'][i]['equipment']['artillery']=0
            if kind=='position':p['actors'][i]['position']={'lat':30.0,'lng':116.0}
            if kind=='sustainment':p.pop('support_dynamics')
            if kind=='goal':p.pop('campaign_plan')
            with self.subTest(kind=kind),self.assertRaises(ValueError):ho.initial(s,p)

    def test_model_cannot_swap_goal_actors_or_remove_a_required_direction(self):
        from tools.qa.wanjialing_estimate_fixture import inputs
        for kind in ('member','missing','source','team','latch'):
            s,p=inputs();n=p['campaign_plan']['nodes'][0]
            if kind=='member':n['unit_ids']=['ww2.cn.artillery1.company6']
            if kind=='missing':p['campaign_plan']['nodes'].pop()
            if kind=='source':n['operation_ids']=[]
            if kind=='team':n['team']='blue'
            if kind=='latch':n['latch']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):ho.initial(s,p)

    def test_native_globals_and_actor_pages_expose_only_the_assigned_estimates(self):
        from backend import scenario_builder as sb,scenario_assembly as sa
        from tools.qa.wanjialing_estimate_fixture import inputs
        _,p=inputs();b=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version='1.1.0',termination_mode='objectives')
        a=sa.create(b);self.addCleanup(sa.close,a.id)
        v=a.tool('globals','get_scenario_basis',{})
        self.assertIn('parameter_estimates',v['readonly_campaign_window'])
        self.assertNotIn('actors',v['readonly_campaign_window']['parameter_estimates'])
        g={k:copy.deepcopy(v) for k,v in p.items() if k not in ('format','phase_id','actors')};g['campaign_scope'].pop('window')
        r=a.tool('globals','update_scenario_configuration',{'revision':0,'patch':g});self.assertTrue(r['updated'],r)
        for part in a.parts:
            v=a.tool(part,'get_scenario_basis',{})
            self.assertTrue(all(u['window_scope']['parameter_estimates'] for u in v['actors']))
            r=a.tool(part,'update_scenario_configuration',{'revision':a.revision,'patch':{'actors':{i:p['actors'][i] for i in a.assigned(part)}}})
            self.assertTrue(r['updated'],r)
        self.assertTrue(a.tool('final','validate_scenario_configuration',{})['valid'])

    def test_globals_reject_missing_goal_numbers_before_six_actor_calls(self):
        from backend import scenario_builder as sb,scenario_assembly as sa
        from tools.qa.wanjialing_estimate_fixture import inputs
        _,p=inputs();b=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version='1.1.0',termination_mode='objectives')
        a=sa.create(b);self.addCleanup(sa.close,a.id)
        g={k:copy.deepcopy(v) for k,v in p.items() if k not in ('format','phase_id','actors')}
        g['campaign_plan']['nodes'][0]['condition']['region']['center']['lat']=None
        before=copy.deepcopy(a.configuration)
        r=a.tool('globals','update_scenario_configuration',{'revision':0,'patch':g})
        self.assertFalse(r['updated']);self.assertEqual(a.configuration,before);self.assertEqual(a.revision,0)

    def test_reviewable_global_priors_are_valid_without_inventing_actor_values(self):
        from backend import scenario_builder as sb,scenario_assembly as sa
        b=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version='1.2.0',termination_mode='objectives',time_step='1小时')
        p=b['configuration_template'];self.assertTrue(all(a['personnel'] is None for a in p['actors'].values()))
        self.assertEqual(p['goal']['deadline_turn'],120)
        a=sa.create(b);self.addCleanup(sa.close,a.id)
        v=a.tool('globals','get_scenario_basis',{})
        self.assertTrue(v['readonly_campaign_window']['review_ready_global_priors'])
        r=a.tool('globals','update_scenario_configuration',{'revision':0,'patch':{'assumptions':'明确复核公共计算先验，未把估计当史实。'}})
        self.assertTrue(r['updated'],r);self.assertTrue(a.global_ready)
        self.assertEqual(a.configuration['campaign_scope']['window']['version'],'1.2.0')
        self.assertEqual(a.filled,set())

    def test_default_prior_mode_and_native_goal_guidance_match_the_bilateral_graph(self):
        from backend.scenario_builder import historical_basis
        b=historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version='1.2.0')
        p=b['configuration_template']
        self.assertEqual(p['goal']['termination_mode'],'objectives')
        self.assertTrue('campaign_plan' in p,'Default objective mode lost the bilateral graph')
        self.assertIn('蓝方',b['goal_semantics']['assault'])

    def test_explicit_actor_priors_are_reviewed_with_small_valid_patches(self):
        from backend import scenario_builder as sb,scenario_assembly as sa
        b=sb.historical_basis(BATTLE,force_scope='campaign',campaign_window_id='WJL-oct6-10',campaign_window_version='1.3.0',termination_mode='objectives',time_step='1小时')
        p=b['configuration_template'];self.assertTrue(all(type(a['personnel']) is int for a in p['actors'].values()))
        self.assertTrue(all(u['facts']['personnel']['value'] is None for u in b['initial']['definition']['units']))
        a=sa.create(b);self.addCleanup(sa.close,a.id)
        r=a.tool('globals','update_scenario_configuration',{'revision':0,'patch':{'assumptions':'复核明确的模型基线，非历史事实。'}});self.assertTrue(r['updated'],r)
        for part in a.parts:
            v=a.tool(part,'get_scenario_basis',{})
            self.assertTrue(v['review_ready_actor_priors'])
            r=a.tool(part,'update_scenario_configuration',{'revision':a.revision,'patch':{'actors':{i:{'assumption':'已核对本模型先验与来源限制，不宣称史实实有数。'} for i in a.assigned(part)}}})
            self.assertTrue(r['updated'],r)
        self.assertTrue(a.tool('final','validate_scenario_configuration',{})['valid'])

    def test_initial_parts_keep_goal_members_and_stocks_without_parent_double_count(self):
        from tools.qa.wanjialing_estimate_fixture import inputs
        from gentactix import campaign_estimates as ce,formation_parts
        s,p=inputs();identity='ww2.jp.division106';parent=p['actors'][identity];parts=[]
        for n in range(2):
            parts.append(dict(id='part'+str(n),label='计算投入部'+str(n),personnel=parent['personnel']//2,
                position={'lat':parent['position']['lat']+.001*n,'lng':parent['position']['lng']},
                equipment={k:v//2 for k,v in parent['equipment'].items()},
                resources={k:parent['formation'][k]//2 for k in formation_parts.RESOURCES},dispersion_km2=2,
                assumption='互斥计算划分，非新增史实团营。'))
        p['partitions']={'version':'formation-partitions-2','groups':{identity:{'parts':parts,'assumption':'仅划分本模型当前初态，不复制父级。'}}}
        for node in p['campaign_plan']['nodes']:node['unit_ids']=ce.goal_members(p,node['unit_ids'])
        w=ho.initial(s,p);self.assertEqual(len(w['blue_units']),6)
        split=[u for u in w['blue_units'] if u.get('historical_unit_id')==identity]
        self.assertEqual(sum(u['personnel']['current'] for u in split),parent['personnel'])
        self.assertAlmostEqual(sum(formation_parts.scale(u)*u['logistics']['food'] for u in split),parent['logistics']['food'])
        p['partitions']['groups'][identity]['parts'][0]['position']['lat']+=.2
        with self.assertRaisesRegex(ValueError,'分队初始部署'):ho.initial(s,p)


if __name__=='__main__':unittest.main()
