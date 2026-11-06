"""Whole Cheqiao source coverage must not be replaced by four-hour QA inputs."""
import copy
import unittest

from gentactix import historical_initial as hi, historical_operations as ho
from gentactix import campaign,missions,commands,combined_arms

BATTLE='抗日战争-车桥战役-1944.03.05至1944.03.06'


class CheqiaoCampaignTests(unittest.TestCase):
    def departure_inputs(self):
        s,p,i=self.constrained_inputs()
        phase=next(x for x in s['definition']['phases'] if x['id']==s['phase_id'])
        rules=phase['input_constraints'];rules['version']='historical-input-2'
        rules['entries'][0].update(reference_kind='departure',region=None,
            earliest='1938-03-31T01:00',latest='1938-03-31T02:00')
        p['campaign']['arrivals'][i]['event_kind']='departure'
        s['definition_hash']=hi.digest(s['definition'])
        return s,p,i

    def test_departure_window_cannot_be_treated_as_contact_or_early_release(self):
        s,p,i=self.departure_inputs();original=copy.deepcopy(s)
        hi.validate_definition(s['definition']);ho.initial(s,p)
        for release in ('1938-03-31T00:00','1938-03-31T02:01'):
            bad=copy.deepcopy(p);bad['campaign']['arrivals'][i]['not_before']=release
            with self.subTest(release=release),self.assertRaisesRegex(ValueError,'启程.*时间窗'):
                ho.initial(s,bad)
        p['campaign']['arrivals'][i]['event_kind']='battlefield_entry'
        with self.assertRaisesRegex(ValueError,'启程参考.*departure'):ho.initial(s,p)
        self.assertEqual(s,original)

    def test_departure_reference_does_not_invent_contact_location_or_force_motion(self):
        s,p,i=self.departure_inputs();p['actors'][i]['position']['lat']+=.01
        world=ho.initial(s,p);actor=world['blue_units'][-1]
        self.assertEqual(actor['lat'],p['actors'][i]['position']['lat'])
        self.assertFalse(world['campaign']['actors'][actor['name']]['active'])
        self.assertEqual(campaign.observation(world)['actors'][-1]['event_kind'],'departure')

    def test_v2_reference_types_are_explicit_and_old_contact_semantics_survive(self):
        s,p,i=self.constrained_inputs();phase=next(x for x in s['definition']['phases'] if x['id']==s['phase_id'])
        rules=phase['input_constraints'];rules['version']='historical-input-2'
        rules['entries'][0]['reference_kind']='contact';s['definition_hash']=hi.digest(s['definition'])
        hi.validate_definition(s['definition']);ho.initial(s,p)
        p['actors'][i]['position']['lat']+=.01
        with self.assertRaisesRegex(ValueError,'前沿入场.*区域'):ho.initial(s,p)
        for kind,region in [('unknown',None),('departure',{'center':{'lat':0,'lng':0},'radius_km':1}),('contact',None)]:
            broken=copy.deepcopy(s['definition'])
            row=next(x for x in broken['phases'] if x['id']==s['phase_id'])['input_constraints']['entries'][0]
            row.update(reference_kind=kind,region=region)
            with self.subTest(kind=kind),self.assertRaises(ValueError):hi.validate_definition(broken)

    def test_references_on_another_actor_cannot_forge_source_binding(self):
        s,p,i=self.constrained_inputs()
        other=next(k for k in p['actors'] if k!=i)
        p['campaign']['arrivals'][other].update(event_kind='departure',reference_id='qa_relief')
        with self.assertRaisesRegex(ValueError,'参考.*本单位'):ho.initial(s,p)

    def test_cheqiao_departure_source_version_preserves_old_frozen_contract(self):
        old=hi.definition(BATTLE,'1.2.0');record=hi.definition(BATTLE,'1.3.0')
        hi.validate_definition(record)
        for phase in record['phases']:
            if not phase['id'].startswith('core_'):continue
            refs=phase['input_constraints']['entries'];self.assertEqual(len(refs),5)
            row=next(r for r in refs if r['unit_id']=='ww2.jp.caodian_relief')
            self.assertEqual(row['reference_kind'],'departure');self.assertIsNone(row['region'])
            self.assertEqual((row['earliest'],row['latest']),('1944-03-05T12:00','1944-03-05T18:00'))
            self.assertIn('并非史料',row['assumption'])
            self.assertTrue(all(r['reference_kind']=='contact' for r in refs if r!=row))
        self.assertEqual(hi.definition(BATTLE,'1.2.0'),old)
        self.assertTrue(all('reference_kind' not in r for p in old['phases'] for r in p.get('input_constraints',{}).get('entries',[])))
        self.assertTrue(all(u['facts'][field]['value'] is None for u in record['units'] for field in ('personnel','equipment','position')))

    def constrained_inputs(self):
        from tools.qa.campaign_fixture import inputs, NOTE
        s,p=inputs();phase=next(x for x in s['definition']['phases'] if x['id']==s['phase_id'])
        identity='ww2.jp.sakamoto_detachment';actor=p['actors'][identity]
        phase['input_constraints']={'version':'historical-input-1','personnel':[
            {'unit_id':identity,'minimum':actor['personnel'],'maximum':actor['personnel']*2,
             'reported':'QA规模参考，不是史实','assumption':NOTE,'evidence':copy.deepcopy(phase['evidence'])}],
            'entries':[{'id':'qa_relief','unit_id':identity,'label':'QA前沿接触参考',
                'earliest':'1938-03-31T01:00','latest':'1938-03-31T01:00',
                'region':{'center':copy.deepcopy(actor['position']),'radius_km':.05},
                'assumption':NOTE,'evidence':copy.deepcopy(phase['evidence'])}]}
        p['campaign']['arrivals'][identity].update(event_kind='battlefield_entry',reference_id='qa_relief')
        s['definition_hash']=hi.digest(s['definition'])
        return s,p,identity

    def test_sourced_input_bounds_do_not_turn_estimates_into_facts(self):
        s,p,i=self.constrained_inputs();before=copy.deepcopy(s)
        ho.initial(s,p)
        p['actors'][i]['personnel']*=3
        with self.assertRaisesRegex(ValueError,'兵力.*建模范围'):ho.initial(s,p)
        self.assertEqual(s,before)
        self.assertIsNone(next(u for u in s['definition']['units'] if u['id']==i)['facts']['personnel']['value'])

    def test_contact_time_cannot_unlock_a_unit_still_at_a_distant_base(self):
        s,p,i=self.constrained_inputs();p['actors'][i]['position']['lat']+=.01
        with self.assertRaisesRegex(ValueError,'前沿入场.*区域'):ho.initial(s,p)
        p['campaign']['arrivals'][i]['event_kind']='departure'
        with self.assertRaisesRegex(ValueError,'启程.*时间'):ho.initial(s,p)
        p['campaign']['arrivals'][i]['not_before']='1938-03-31T00:00'
        ho.initial(s,p)  # Necessary travel-time feasibility, not a forced contact result.

    def test_entry_reference_must_not_be_dropped_duplicated_or_swapped(self):
        for key,value in [('event_kind',None),('event_kind','contact'),('reference_id','unknown')]:
            s,p,i=self.constrained_inputs()
            if value is None:p['campaign']['arrivals'][i].pop(key)
            else:p['campaign']['arrivals'][i][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):ho.initial(s,p)
        s,p,i=self.constrained_inputs();p['campaign']['arrivals'][i]['not_before']='1938-03-31T00:30'
        with self.assertRaisesRegex(ValueError,'入场.*时间'):ho.initial(s,p)

    def test_bad_reference_sources_and_unknown_units_are_rejected(self):
        for kind in ('source','unit','bounds','region','date'):
            s,p,i=self.constrained_inputs();phase=next(x for x in s['definition']['phases'] if x['id']==s['phase_id'])
            rules=phase['input_constraints']
            if kind=='source':rules['entries'][0]['evidence'][0]['source_id']='invented'
            elif kind=='unit':rules['personnel'][0]['unit_id']='invented'
            elif kind=='bounds':rules['personnel'][0]['minimum']=10000000
            elif kind=='region':rules['entries'][0]['region']['radius_km']=float('nan')
            else:rules['entries'][0]['latest']='1938-04-02T00:00'
            with self.subTest(kind=kind),self.assertRaises(ValueError):hi.validate_definition(s['definition'])

    def test_partial_actor_configuration_still_checks_its_source_bounds(self):
        s,p,i=self.constrained_inputs();p['actors'][i]['personnel']*=3
        with self.assertRaisesRegex(ValueError,'兵力.*建模范围'):ho._validate(s,p,actor_ids=[i])
        ho._validate(s,p,actor_ids=[])

    def test_old_frozen_configuration_has_no_new_inferred_constraints(self):
        from tools.qa.campaign_fixture import inputs
        s,p=inputs();p['actors']['ww2.jp.sakamoto_detachment']['personnel']*=3
        ho.initial(s,p)

    def test_cheqiao_new_version_retains_null_facts_and_explicit_model_bounds(self):
        record=hi.definition(BATTLE,'1.2.0')
        self.assertTrue(hi.validate_definition(record))
        self.assertTrue(all(u['facts'][field]['value'] is None for u in record['units']
                            for field in ('personnel','equipment','position')))
        for phase in record['phases']:
            if not phase['id'].startswith('core_'):continue
            inputs=phase['input_constraints']
            self.assertEqual(len(inputs['entries']),4)
            self.assertEqual(inputs['personnel'][0]['reported'].count('40'),2)
            self.assertIn('并非史料',inputs['personnel'][0]['assumption'])
            self.assertEqual((inputs['personnel'][0]['minimum'],inputs['personnel'][0]['maximum']),(40,60))
        self.assertTrue(all('input_constraints' not in p for p in hi.definition(BATTLE,'1.1.0')['phases']))

    def test_unbound_schedule_metadata_is_not_a_valid_source_claim(self):
        from tools.qa.campaign_fixture import inputs
        s,p=inputs()
        p['campaign']['arrivals']['ww2.jp.sakamoto_detachment'].update(event_kind='departure',reference_id='invented')
        with self.assertRaisesRegex(ValueError,'没有接敌参考'):ho.initial(s,p)

    def test_partition_arrival_references_are_distinct_and_observed(self):
        s,p,i=self.constrained_inputs();phase=next(x for x in s['definition']['phases'] if x['id']==s['phase_id'])
        second=copy.deepcopy(phase['input_constraints']['entries'][0]);second.update(id='qa_relief2',earliest='1938-03-31T01:30',latest='1938-03-31T01:30')
        phase['input_constraints']['entries'].append(second);s['definition_hash']=hi.digest(s['definition'])
        actor=p['actors'][i];parts=[]
        for index,count in enumerate((actor['personnel']-5,5)):
            parts.append({'id':f'p{index}','label':f'QA分队{index}','personnel':count,
                'position':copy.deepcopy(actor['position']),
                'equipment':{k:(v if index==0 else 0) for k,v in actor['equipment'].items()},
                'resources':{k:(actor['formation'][k] if index==0 else 0) for k in ('fuel_liters','spares','materials','shells','aa_rounds')},
                'dispersion_km2':.1,'assumption':'QA分队并非历史编制'})
        p['partitions']={'version':'formation-partitions-1','groups':{i:{'parts':parts,'assumption':'QA互斥拆分'}}}
        p['campaign']['arrivals'][i]['parts']={
            'p0':{'not_before':'1938-03-31T01:00','assumption':'QA','event_kind':'battlefield_entry','reference_id':'qa_relief'},
            'p1':{'not_before':'1938-03-31T01:30','assumption':'QA','event_kind':'battlefield_entry','reference_id':'qa_relief2'}}
        world=ho.initial(s,p)
        observed=[r for r in campaign.observation(world)['actors'] if r.get('reference_id')]
        self.assertEqual({r['reference_id'] for r in observed},{'qa_relief','qa_relief2'})
        self.assertTrue(all(r['event_kind']=='battlefield_entry' for r in observed))
        bad=copy.deepcopy(p);bad['campaign']['arrivals'][i]['parts'].pop('p1')
        with self.assertRaisesRegex(ValueError,'不同.*参考'):ho.initial(s,bad)
        bad=copy.deepcopy(p);bad['partitions']['groups'][i]['parts'][1]['position']['lat']+=.01
        with self.assertRaisesRegex(ValueError,'前沿入场.*区域'):ho.initial(s,bad)

    def test_staged_tool_keeps_schedule_semantics_and_validates_source_bounds(self):
        from backend import scenario_builder,scenario_assembly
        from unittest.mock import patch
        s,p,i=self.constrained_inputs();battle=s['definition']['battle']
        for actor in p['actors'].values():actor['formation'].setdefault('motorized',True)
        basis=scenario_builder.historical_basis(battle,s['phase_id']);basis['initial']=s
        basis['phase']=next(x for x in s['definition']['phases'] if x['id']==s['phase_id'])
        # This fixture adds QA-only input constraints to a published source.
        # It must not borrow that source version's historical objective guide.
        with self.assertRaisesRegex(ValueError,'完整历史初态'):
            ho.configuration_template(s)
        with patch.object(ho,'objective_guidance',return_value=None):
            basis['configuration_template']=ho.configuration_template(s)
        basis['objective_guidance']=None
        assembly=scenario_assembly.create(basis);self.addCleanup(scenario_assembly.close,assembly.id)
        view=assembly.tool('globals','get_scenario_basis',{})
        self.assertIn('input_constraints',view['phase'])
        p['goal']['team']=basis['configuration_template']['goal']['team']
        result=assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':{k:v for k,v in p.items() if k not in ('actors','format','phase_id')}})
        self.assertTrue(result['updated'],result.get('error'))
        self.assertEqual(assembly.configuration['campaign']['arrivals'][i]['event_kind'],'battlefield_entry')
        bad=copy.deepcopy(p['actors']);bad[i]['personnel']*=3
        result=assembly.tool('actors:0','update_scenario_configuration',{'revision':1,'patch':{'actors':bad}})
        self.assertFalse(result['updated']);self.assertIn('兵力',result['error'])
        self.assertEqual(assembly.revision,1)

    def test_partitioned_campaign_compiles_all_referenced_goal_counters_without_crossing(self):
        from tools.qa.campaign_fixture import inputs
        from backend import afsim_world
        import re
        snapshot,params=inputs();identity='ww2.cn.division31';parent=params['actors'][identity]
        parts=[]
        for index,count in enumerate((parent['personnel']-5,5)):
            parts.append({'id':f'part{index}','label':f'QA分队{index}','personnel':count,
                'position':copy.deepcopy(parent['position']),
                'equipment':{k:(v if index==0 else 0) for k,v in parent['equipment'].items()},
                'resources':{k:(parent['formation'][k] if index==0 else 0) for k in ('fuel_liters','spares','materials','shells','aa_rounds')},
                'dispersion_km2':.1,'assumption':'明确QA互斥划分，不是史实分队部署'})
        params['partitions']={'version':'formation-partitions-1','groups':{identity:{'parts':parts,'assumption':'QA'}}}
        world=ho.initial(snapshot,params)
        script=afsim_world.compile_scene(world,[],.001,native_rules=True)['script']
        self.assertNotIn('crossing_model',params['facility'])
        for name in ('redCrossed','blueCrossed'):
            self.assertRegex(script,r'int\s+'+name+r'\s*=')

    def test_generation_feedback_distinguishes_arrival_maps_from_partition_lists(self):
        from tools.qa.campaign_fixture import inputs
        snapshot,params=inputs();identity='ww2.cn.division31'
        bad=copy.deepcopy(params)
        bad['campaign']['arrivals'][identity]['parts']=[{'id':'first','not_before':params['clock']['start'],'assumption':'QA'}]
        with self.assertRaisesRegex(ValueError,'parts.*对象'):
            campaign.validate_parameters(snapshot,bad)
        bad=copy.deepcopy(params)
        bad['campaign']['objective']['relief_regions'][0]['assumption']='误把依据放到区域内部'
        with self.assertRaisesRegex(ValueError,'多余.*assumption'):
            campaign.validate_parameters(snapshot,bad)
        bad=copy.deepcopy(params)
        bad['campaign']['objective']['relief_regions'][0].pop('radius_km')
        with self.assertRaisesRegex(ValueError,'缺少.*radius_km'):
            campaign.validate_parameters(snapshot,bad)
        for groups in (None,{identity:None},{identity:{'parts':{'first':{}}}}):
            bad=copy.deepcopy(params)
            bad['campaign']['arrivals'][identity]['parts']={'first':{'not_before':params['clock']['start'],'assumption':'QA'}}
            bad['partitions']={'version':'formation-partitions-1','groups':groups}
            with self.assertRaises(ValueError):
                campaign.validate_parameters(snapshot,bad)

    def source(self):
        return hi.definition(BATTLE,version='1.1.0')

    def test_complete_core_window_is_a_new_version_and_old_definition_stays_available(self):
        old=hi.definition(BATTLE,version='1.0.0')
        new=self.source()
        self.assertEqual(old['version'],'1.0.0')
        phases={p['id']:p for p in new['phases']}
        self.assertIn('core_march5_6',phases)
        self.assertIn('core_march5_7',phases)
        self.assertEqual(phases['cheqiao_mar5'],next(p for p in old['phases'] if p['id']=='cheqiao_mar5'))
        self.assertTrue(hi.validate_definition(new))

    def test_source_disagreements_are_explicit_and_not_summed_into_facts(self):
        value=self.source()
        notes=' '.join(value['coverage']['notes'])+' '+str(value['sources'])
        for text in ('50','52','6日','7日','192','238'):
            self.assertIn(text,notes)
        self.assertTrue(all(u['facts'][f]['value'] is None for u in value['units']
                            for f in ('personnel','equipment','position')))

    def test_whole_core_has_assault_relief_southern_screen_and_reserve_identities(self):
        value=self.source();index={u['id']:u for u in value['units']}
        for phase in ('core_march5_6','core_march5_7'):
            # Use the public snapshot factory once the explicit version is installed;
            # validate identity partition on the same frozen source content here.
            snap=hi.initial(BATTLE,phase,version='1.1.0')['historical_initial']
            ids=set(ho.partition(snap))
            self.assertTrue({'ww2.cn.new4_regiment7','ww2.cn.new4_artillery_battalion',
                'ww2.cn.new4_regiment1','ww2.cn.regiment52','ww2.jp.huaian_relief'}<=ids)
            self.assertGreaterEqual(len([i for i in ids if index[i]['team']=='red']),8)
            self.assertIn('ww2.jp.caodian_relief',ids)
            self.assertNotIn('ww2.jp.division65',ids)

    def test_full_phase_demands_process_features_before_ready_claims(self):
        value=self.source()
        for phase in value['phases']:
            if not phase['id'].startswith('core_'):continue
            kinds={r['kind'] for r in phase['process_requirements']}
            self.assertIn('combined_operation',kinds)
            self.assertTrue(all(r['evidence'] and r['scope'] for r in phase['process_requirements']))

    def test_full_phase_template_requires_a_separate_campaign_process_contract(self):
        snapshot=hi.initial(BATTLE,'core_march5_6',version='1.1.0')['historical_initial']
        template=ho.configuration_template(snapshot)
        self.assertEqual(template['campaign']['version'],'combined-operation-1')
        self.assertTrue(template['campaign']['arrivals'])
        self.assertIsNone(template['goal']['radius_km'])
        self.assertIsNone(template['campaign']['surrender']['range_m'])
        self.assertNotIn('campaign',ho.configuration_template(hi.initial(BATTLE,'cheqiao_mar5',version='1.0.0')['historical_initial']))

    def test_missing_or_out_of_window_process_inputs_are_rejected(self):
        from tools.qa.campaign_fixture import inputs
        s,p=inputs();before=copy.deepcopy(s)
        for kind in ('missing','early','late','missing_relief','missing_actor','unknown_actor'):
            bad=copy.deepcopy(p)
            if kind=='missing':bad.pop('campaign')
            elif kind=='early':bad['campaign']['arrivals']['ww2.cn.division31']['not_before']='1938-03-30T23:00'
            elif kind=='late':bad['campaign']['arrivals']['ww2.cn.division31']['not_before']='1938-04-02T00:00'
            elif kind=='missing_relief':bad['campaign']['objective']['relief_regions']=[]
            elif kind=='missing_actor':bad['campaign']['arrivals'].pop('ww2.cn.division31')
            else:bad['campaign']['arrivals']['invented']=bad['campaign']['arrivals'].pop('ww2.cn.division31')
            with self.subTest(kind=kind),self.assertRaises(ValueError):ho.initial(s,bad)
        self.assertEqual(s,before)

    def test_binding_preserves_process_and_waiting_actor_is_not_lost_or_early(self):
        from tools.qa.campaign_fixture import inputs
        s,p=inputs();w=ho.initial(s,p);before=copy.deepcopy(w)
        self.assertEqual(w['mission']['definition']['campaign_definition']['arrivals'],p['campaign']['arrivals'])
        self.assertEqual(w['mission']['definition']['campaign_definition']['objective']['town'],
            {'center':p['goal']['objective'],'radius_km':p['goal']['radius_km']})
        self.assertEqual(len(w['red_units'])+len(w['blue_units']),3)
        later=w['blue_units'][-1]
        self.assertEqual(campaign.release_seconds(w,later),3600)
        self.assertNotIn('fire',combined_arms.actions(w,later,'blue'))
        with self.assertRaisesRegex(ValueError,'尚.*集结|尚未入场'):
            missions.validate_orders(w,[{'unit':later['name'],'action':'fire','target':w['red_units'][0]['name']}],p['clock']['time_step'])
        self.assertEqual(w,before)

    def test_capture_requires_opt_in_and_real_target_constraints(self):
        from tools.qa.campaign_fixture import inputs
        s,p=inputs();w=ho.initial(s,p);actor=w['red_units'][0];target=w['blue_units'][0]
        self.assertIn('capture',combined_arms.actions(w,actor,'red'))
        order={'unit':actor['name'],'action':'capture','target':target['name']}
        with self.assertRaisesRegex(ValueError,'受降条件'):missions.validate_orders(w,[order],p['clock']['time_step'])
        target['logistics']['ammo']=0
        self.assertTrue(missions.validate_orders(w,[order],p['clock']['time_step']))
        from tools.qa.historical_operational_fixture import inputs as old_inputs
        old_s,old_p=old_inputs();old=ho.initial(old_s,old_p)
        self.assertNotIn('capture',combined_arms.actions(old,old['red_units'][0],'red'))

    def test_native_process_telemetry_is_mandatory_and_compiler_does_not_drop_it(self):
        from tools.qa.campaign_fixture import inputs
        from backend import afsim_world
        s,p=inputs();w=ho.initial(s,p);before=copy.deepcopy(w)
        scene=afsim_world.compile_scene(w,[{'unit':u['name'],'action':'hold'} for _,u in missions.units(w)],1800,native_rules=True)
        self.assertIn('GTXCAMPAIGN',scene['script'])
        self.assertIn('campaign_revision',scene['native_model'])
        self.assertEqual(w,before)
        from backend import afsim_campaign
        with self.assertRaisesRegex(ValueError,'回执'):afsim_campaign.parse('',scene['native_model'],scene)

    def test_campaign_state_cannot_lose_units_or_lie_about_arrival(self):
        from tools.qa.campaign_fixture import inputs
        s,p=inputs();world=ho.initial(s,p)
        for kind in ('missing','actor','arrival','captured','goal'):
            w=copy.deepcopy(world);name=w['blue_units'][-1]['name']
            if kind=='missing':w.pop('campaign')
            elif kind=='actor':w['campaign']['actors'].pop(name)
            elif kind=='arrival':w['campaign']['actors'][name]['active']=True
            elif kind=='captured':w['campaign']['actors'][name]['captured_this_turn']=1
            else:w['campaign']['objective']['town_control']='true'
            with self.subTest(kind=kind),self.assertRaises(ValueError):missions.validate(w)


if __name__=='__main__':unittest.main()
