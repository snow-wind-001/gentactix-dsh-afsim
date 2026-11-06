"""Independent passage sites must share one world, never duplicate its forces."""
import copy
import unittest
from unittest.mock import patch
from gentactix import missions, combined_arms, crossings
from backend import afsim_world
from verify_afsim_crossing import fixture as single_fixture


def fixture():
    spec = single_fixture()
    spec['id'] = 'QA-crossing-network-v1'
    bridge = spec['initial_state']['combined_arms']['bridge']
    bridge['id'] = 'west'
    bridge['name'] = '西侧估计渡点'
    # Same declared river, two independent passage sites. These are QA inputs.
    bridge['crossing_model']['barrier'] = {
        'a': {'lat':27.3,'lng':107.38}, 'b': {'lat':27.3,'lng':107.42}}
    other = copy.deepcopy(bridge)
    other.update(id='east', name='东侧估计渡点', lng=107.41)
    for p in other['crossing_model']['banks'].values():
        p['lng'] = 107.41
    other['crossing_model']['throughput_work_per_hour'] = 600
    bridge['crossing_network'] = {'version':'formation-crossing-network-1','sites':[other]}
    red = spec['initial_state']['red_units']
    red[0].update(lat=27.299, lng=107.4)
    red[1].update(lat=27.299, lng=107.41)
    return spec


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture()
        original=missions.definition
        registered=patch.object(missions,'definition',side_effect=lambda i:copy.deepcopy(self.spec) if i==self.spec['id'] else original(i))
        registered.start();self.addCleanup(registered.stop)
        self.world=missions.from_definition(copy.deepcopy(self.spec))

    def test_both_routes_use_own_entry_and_capacity_platform(self):
        orders=[{'unit':u['name'],'action':'move','lat':27.303,'lng':u['lng']}
                for u in self.world['red_units'][:2]]
        scene=afsim_world.compile_scene(self.world,orders,1800,native_rules=True)
        actors=[e for e in scene['entities'].values() if e['name'] in {o['unit'] for o in orders}]
        self.assertEqual([e['crossing_plan']['task']['site_id'] for e in actors],['west','east'])
        self.assertEqual(scene['motion_revision'],10)
        self.assertIn('platform gtx_cross_site_1 WSF_PLATFORM',scene['script'])
        self.assertIn('GTXNETCAP|1|',scene['script'])
        self.assertEqual(len(scene['entities']),len(missions.units(self.world)))

    def test_network_identity_and_capacity_are_frozen(self):
        w=copy.deepcopy(self.world)
        w['combined_arms']['bridge']['crossing_network']['sites'][0]['crossing_model']['throughput_work_per_hour']*=2
        with self.assertRaisesRegex(ValueError,'冻结'): missions.validate(w)

    def test_duplicate_site_and_different_river_rejected(self):
        for mode in ('duplicate','river'):
            with self.subTest(mode=mode):
                spec=copy.deepcopy(self.spec)
                site=spec['initial_state']['combined_arms']['bridge']['crossing_network']['sites'][0]
                if mode=='duplicate':site['id']='west'
                else:site['crossing_model']['barrier']['a']['lat']+=.0001
                with self.assertRaises(ValueError): missions.from_definition(spec)

    def test_pending_task_is_pinned_to_its_site(self):
        from gentactix import crossing_network as network
        u=self.world['red_units'][1]
        order={'unit':u['name'],'action':'move','lat':27.303,'lng':107.41,'intent_id':'a'*32}
        task=network.plan(self.world,u,order)['task']
        u['crossing']=task
        u['lng']=107.4 # Changing apparent proximity must not transfer a queue.
        task['served_work']=50
        result=network.plan(self.world,u,order)
        self.assertEqual(result['task']['site_id'],'east')
        self.assertEqual(result['task']['served_work'],50)

    def test_engineering_selects_nearby_site(self):
        from gentactix import crossing_network as network
        u=self.world['red_units'][1]
        self.assertEqual(network.engineering_site(self.world,u)['id'],'east')

    def test_observation_names_both_sites_without_duplicating_state(self):
        view=crossings.observation(self.world)
        self.assertEqual([s['site_id'] for s in view['sites']],['west','east'])
        self.assertIn('同一河线',view['scope'])

    def test_historical_parameter_ingress_preserves_network(self):
        from tools.qa.historical_operational_fixture import inputs
        from gentactix import historical_operations as op
        source,params=inputs()
        bridge=copy.deepcopy(self.spec['initial_state']['combined_arms']['bridge'])
        center=params['area']['center']
        for s in [bridge]+bridge['crossing_network']['sites']:
            for p in [s]+list(s['crossing_model']['barrier'].values())+list(s['crossing_model']['banks'].values()):
                p['lat']+=center['lat']-27.3;p['lng']+=center['lng']-107.4
        params['facility']=bridge
        params['rules']['bridge_enabled']=True
        w=op.initial(source,params)
        self.assertEqual(w['combined_arms']['bridge'],bridge)
        from backend.scenario_assembly import _merge_known
        merged=_merge_known(op.configuration_template(source),{'facility':bridge})
        self.assertEqual(merged['facility']['crossing_network'],bridge['crossing_network'])

    def proposal(self):
        from gentactix import crossing_network as network
        from verify_dsh_resources import model_result
        output=model_result(self.world)
        bridge=copy.deepcopy(self.world['combined_arms']['bridge'])
        for i,(site,work) in enumerate(zip(network.sites(self.world),(200,100))):
            unit=self.world['red_units'][i];target={'lat':27.303,'lng':unit['lng']}
            route=network.plan(self.world,unit,target)
            output['orders'][i].update(action='move',**target)
            output['unit_updates'][i].update(**route['entry'],crossing={'served_work':work,'last_work':work,
                'status':'queued','events':[{'phase':'entered','seconds':1,**route['entry']}]})
            output['unit_updates'][i]['logistics']['food']-=2
            output['resource_ledger']['units'][i]['food_spent']=4
            dest=bridge if i==0 else bridge['crossing_network']['sites'][i-1]
            dest['crossing_receipt']={'used_work':work,'cargo_work':0,
                'budget_work':site['crossing_model']['throughput_work_per_hour']/2}
        output['combined_arms']={'bridge':bridge}
        return output

    def test_dsh_receipts_remain_separate_and_do_not_call_afsim(self):
        from backend import dsh_simulation
        value=self.proposal()
        with patch.object(afsim_world,'run_scene',side_effect=AssertionError('DSH-only')):
            after=dsh_simulation.apply(self.world,value,'30分钟')
        self.assertEqual([u['crossing']['site_id'] for u in after['red_units'][:2]],['west','east'])
        self.assertEqual([u['crossing']['served_work'] for u in after['red_units'][:2]],[200,100])
        self.assertEqual(after['combined_arms']['bridge']['crossing_network']['sites'][0]['crossing_receipt']['used_work'],100)

    def test_dsh_cannot_borrow_other_site_capacity_or_events(self):
        from backend import dsh_simulation
        for kind in ('capacity','wrong_bank','missing_site_ledger','reorder'):
            with self.subTest(kind=kind):
                value=self.proposal()
                site=value['combined_arms']['bridge']['crossing_network']['sites'][0]
                if kind=='capacity':site['crossing_receipt']['budget_work']=500
                if kind=='wrong_bank':value['unit_updates'][1]['crossing']['events'][0]['lng']=107.4
                if kind=='missing_site_ledger':site.pop('crossing_receipt')
                if kind=='reorder':site['id']='west'
                original=copy.deepcopy(self.world)
                with self.assertRaises(ValueError):dsh_simulation.apply(self.world,value,'30分钟')
                self.assertEqual(self.world,original)

    def test_human_control_inputs_name_selected_site(self):
        from gentactix import commands
        session={'id':'network-qa','war_state':self.world,'turn_count':0,'time_step':'30分钟','simulation_mode':'open','execution_backend':'afsim'}
        view=commands.view(session);u=self.world['red_units'][1]
        row=next(r for r in view['units'] if r['name']==u['name'])
        session['command_state']=commands.replace_queue(session,[{'unit_id':row['id'],'action':'move',
            'duration':'until_arrived','destination':{'lat':27.303,'lng':107.41}}],control_team='red',director=False,no_fire=False,intent='')
        prepared=commands.prepare(session)
        self.assertEqual(next(x for x in prepared['crossing_inputs'] if x['unit']==u['name'])['site_id'],'east')

    def test_new_network_does_not_allow_boat_fallback(self):
        from verify_ferries import ferry_inputs
        _,p=ferry_inputs();spec=copy.deepcopy(self.spec)
        spec['initial_state']['combined_arms']['bridge']['crossing_model']['ferry']=p['facility']['crossing_model']['ferry']
        from gentactix import crossing_network as network
        with self.assertRaisesRegex(ValueError,'舟艇'):network.validate(spec['initial_state']['combined_arms']['bridge'])

    def test_incomplete_network_inputs_are_rejected_as_validation_errors(self):
        from gentactix import crossing_network as network
        for kind in ('null_network','no_primary_model','null_other_model'):
            with self.subTest(kind=kind):
                b=copy.deepcopy(self.world['combined_arms']['bridge'])
                if kind=='null_network':b['crossing_network']=None
                elif kind=='no_primary_model':b.pop('crossing_model')
                else:b['crossing_network']['sites'][0]['crossing_model']=None
                with self.assertRaises(ValueError):network.validate(b)

    def test_native_requires_complete_unborrowed_site_evidence(self):
        from backend import afsim_crossing
        scene=afsim_world.compile_scene(self.world,[],1800,native_rules=True)
        rows=['GTXCLOCK|1800','GTXCROSSCAP|0|0|0|0|500|0','GTXNETCAP|1|0|0|0|0|300|0','GTXNETFAC|1|100|100|40|0']
        for identity,e in scene['entities'].items():
            a,b=e['origin']['lat'],e['origin']['lng']
            rows.extend([f'GTXPOS|{identity}|{int(a)}|{round((a-int(a))*1e8)}|{int(b)}|{round((b-int(b))*1e8)}',
                         f'GTXCROSS|{identity}|0|0|0|0|0|0|0'])
        text='\n'.join(rows)
        result=afsim_crossing.parse(text,scene,self.world)
        self.assertEqual([r['capacity']['budget_work'] for r in result['sites']],[500,300])
        for kind in ('missing','duplicate','capacity','unknown_actor','unknown_site'):
            with self.subTest(kind=kind):
                changed=text
                if kind=='missing':changed=changed.replace('GTXNETFAC|1|100|100|40|0','')
                if kind=='duplicate':changed+='\nGTXNETCAP|1|0|0|0|0|300|0'
                if kind=='capacity':changed=changed.replace('GTXNETCAP|1|0|0|0|0|300|0','GTXNETCAP|1|0|0|0|0|500|0')
                if kind=='unknown_actor':changed+='\nGTXCROSS|unknown|0|0|0|0|0|0|0'
                if kind=='unknown_site':changed=changed.replace('GTXNETFAC|1|','GTXNETFAC|7|')
                with self.assertRaises(ValueError):afsim_crossing.parse(changed,scene,self.world)


if __name__=='__main__':unittest.main()
