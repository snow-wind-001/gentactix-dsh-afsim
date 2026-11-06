"""Lossless model observation formatting, never an alternative world store."""
import copy
import json
import unittest


class ObservationProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend import scenario_builder
        from gentactix import historical_operations
        cls.basis=scenario_builder.historical_basis(
            '抗日战争-万家岭战役-1938.09下旬至1938.10',force_scope='campaign',
            campaign_window_id='WJL-oct6-10',campaign_window_version='1.4.0',
            time_step='1小时',termination_mode='objectives')
        cls.world=historical_operations.initial(cls.basis['initial'],cls.basis['configuration_template'])

    def test_actual_22_actor_prompt_encodes_sources_without_reducing_force_or_values(self):
        from backend import dsh_simulation
        before=copy.deepcopy(self.world)
        text=dsh_simulation.prompt(self.world)
        view=json.loads(text.split('\n当前态势：',1)[1].split('\n史料：',1)[0])
        self.assertTrue('_provenance' in view,'重复来源尚未通过只读来源表编码')
        from gentactix import observation_codec as codec
        restored=codec.decode(view)
        self.assertEqual(restored,dsh_simulation.observation_view(self.world))
        self.assertEqual(len(restored['red_units'])+len(restored['blue_units']),22)
        self.assertLess(len(json.dumps(view,ensure_ascii=False)),len(json.dumps(restored,ensure_ascii=False))*.8)
        for team in ('red','blue'):
            for actual,original in zip(restored[team+'_units'],self.world[team+'_units']):
                for field in ('name','historical_unit_id','lat','lng','personnel','logistics'):
                    self.assertEqual(actual[field],original[field])
                self.assertEqual([(e['category'],e['committed'],e['operational'],e['destroyed']) for e in actual['equipment']],
                                 [(e['category'],e['committed'],e['operational'],e['destroyed']) for e in original['equipment']])
        self.assertIn('宿主保留原来源',text)
        self.assertEqual(self.world,before)

    def test_roundtrip_preserves_nested_metadata_and_original_reference_literals(self):
        from gentactix import observation_codec as codec
        note='计算先验而非史料实有数；人员装备和位置仍须核查。'*20
        source=dict(units=[dict(id=i,source=note,personnel=dict(current=100,source=note),
            parameter_sources=dict(assumption=note,value=None,limits=[0,1.5,False]),
            name='~source:literal',assumption='~source:literal') for i in range(3)],
            assumptions='~~already escaped',source_note='~ordinary literal')
        before=copy.deepcopy(source);encoded=codec.encode(source)
        self.assertEqual(codec.decode(json.loads(json.dumps(encoded))),source)
        self.assertEqual(source,before)
        self.assertEqual(encoded['units'][0]['name'],'~source:literal')
        self.assertEqual(encoded['units'][0]['personnel']['current'],100)

    def test_non_metadata_text_and_small_or_unique_sources_keep_original_format(self):
        from gentactix import observation_codec as codec
        text='任意很长的单位名称，不能当来源改写。'*50
        value=dict(units=[dict(name=text,source='S1') for _ in range(3)],assumption='唯一来源'*200)
        self.assertEqual(codec.encode(value),value)
        self.assertEqual(codec.decode(value),value)
        encoded=codec.encode(value);encoded['units'][0]['source']='changed'
        self.assertEqual(value['units'][0]['source'],'S1')

    def test_all_45_catalogue_profiles_and_frozen_versions_roundtrip_exactly(self):
        from pathlib import Path
        from gentactix import historical_initial,observation_codec as codec
        catalogue=historical_initial.catalog();versions=0
        self.assertEqual(len(catalogue),45)
        for row in catalogue:
            for path in sorted((Path('data/historical_initial')/row['profile_id']).glob('*.json')):
                with self.subTest(profile=row['profile_id'],version=path.stem):
                    original=json.loads(path.read_text());encoded=codec.encode(original)
                    self.assertEqual(codec.decode(json.loads(json.dumps(encoded))),original)
                    versions+=1
        self.assertGreaterEqual(versions,57)

    def test_current_source_ids_are_stable_when_order_changes_or_other_sources_arrive(self):
        from gentactix import observation_codec as codec
        a='估计来源甲。'*100;b='估计来源乙。'*100
        first=codec.encode(dict(units=[dict(source=a),dict(source=a),dict(source=b),dict(source=b)]))
        second=codec.encode(dict(units=[dict(source=b),dict(source=b),dict(source=a),dict(source=a)]))
        self.assertEqual(first['units'][0]['source'],second['units'][2]['source'])
        self.assertEqual(first['_provenance']['sources'],second['_provenance']['sources'])

    def test_corrupt_or_unknown_references_never_decode_as_different_facts(self):
        from gentactix import observation_codec as codec
        value=dict(units=[dict(source='参数缺载须显式估计。'*100,personnel=100) for _ in range(3)])
        encoded=codec.encode(value)
        for mutate in (
            lambda v:v['_provenance'].update(version='unknown'),
            lambda v:v['_provenance']['sources'].clear(),
            lambda v:v['units'][0].update(source='~source:unknown'),
            lambda v:v['units'][0].update(personnel=101),
            lambda v:v['_provenance'].update(state='injected'),
            lambda v:v['_provenance']['sources'].update({'unused':'伪造文本'})):
            bad=copy.deepcopy(encoded);mutate(bad)
            with self.subTest(value=bad),self.assertRaises(ValueError):codec.decode(bad)
        self.assertEqual(codec.decode(encoded),value)

    def test_invalid_json_trees_and_reserved_envelopes_are_rejected_explicitly(self):
        from gentactix import observation_codec as codec
        for value in (dict(source=float('nan')),{1:'non-string key'},dict(a=(1,2)),dict(_provenance={})):
            with self.subTest(value=value),self.assertRaises(ValueError):codec.encode(value)

    def test_source_reference_or_table_cannot_be_submitted_as_new_battle_state(self):
        from backend import dsh_simulation
        from gentactix import observation_codec as codec
        from verify_campaign_plan_backends import proposal
        view=codec.encode(dsh_simulation.observation_view(self.world))
        self.assertTrue(view['red_units'][0]['personnel']['source'].startswith('~source:'))
        candidate=proposal(self.world)
        name=view['red_units'][0]['name']
        update=next(u for u in candidate['unit_updates'] if u['unit']==name)
        update.setdefault('personnel',{})['source']=view['red_units'][0]['personnel']['source']
        before=copy.deepcopy(self.world)
        with self.assertRaisesRegex(ValueError,'来源'):
            dsh_simulation.apply(self.world,candidate,'1小时')
        self.assertEqual(self.world,before)
        candidate=proposal(self.world);candidate['_provenance']=view['_provenance']
        with self.assertRaises(ValueError):dsh_simulation.apply(self.world,candidate,'1小时')
        self.assertEqual(self.world,before)

    def test_mutable_source_note_cannot_keep_an_unresolved_observation_reference(self):
        from backend import dsh_simulation
        from gentactix import observation_codec as codec
        from verify_campaign_plan_backends import proposal
        from tools.qa.campaign_plan_fixture import inputs
        from gentactix import historical_operations
        source,parameters=inputs()
        for actor in parameters['actors'].values():actor['assumption']='软件验收来源估计，未作历史标定。'*30
        world=historical_operations.initial(source,parameters)
        candidate=proposal(world)
        # Establish a valid physical/account proposal before changing provenance.
        dsh_simulation.apply(world,candidate,'30分钟')
        view=codec.encode(dsh_simulation.observation_view(world))
        candidate['source_note']='模型估计，来源 '+view['red_units'][0]['personnel']['source']
        before=copy.deepcopy(world)
        with self.assertRaisesRegex(ValueError,'来源引用'):
            dsh_simulation.apply(world,candidate,'30分钟')
        self.assertEqual(world,before)


class NativeSourceDetailTests(unittest.TestCase):
    def setUp(self):
        from tools.qa.turn_preview_page_fixture import session
        self.session=session()

    def resolver(self, query):
        from backend import afsim_state
        return afsim_state.observation(self.session, query)

    def encoded(self):
        from backend import afsim_state,dsh_simulation
        from gentactix import commands,observation_codec as codec
        return codec.encode(dsh_simulation.observation_view(self.session['war_state']),
            source_queries=afsim_state.source_queries(self.session),
            world_version=commands.world_version(self.session))

    def test_all22_facts_roundtrip_through_existing_native_detail_queries(self):
        from backend import dsh_simulation
        from gentactix import observation_codec as codec
        before=copy.deepcopy(self.session);value=self.encoded()
        self.assertEqual(value['_provenance']['version'],'observation-provenance-2')
        self.assertTrue(value['_provenance']['deferred'])
        self.assertEqual(codec.decode(value,resolve=self.resolver),
                         dsh_simulation.observation_view(self.session['war_state']))
        self.assertEqual(self.session,before)

    def test_all_numeric_identity_and_unknown_fields_keep_original_paths(self):
        from backend import dsh_simulation
        from gentactix import observation_codec as codec
        original=dsh_simulation.observation_view(self.session['war_state']);value=self.encoded()
        old=codec.encode(original)
        self.assertLess(len(json.dumps(value,ensure_ascii=False)),len(json.dumps(old,ensure_ascii=False)))
        def visit(a,b,metadata=False):
            if isinstance(a,dict):
                for k,v in a.items():visit(v,b[k],metadata or k in codec.SOURCE_FIELDS)
            elif isinstance(a,list):
                self.assertEqual(len(a),len(b))
                for x,y in zip(a,b):visit(x,y,metadata)
            elif not metadata or not isinstance(a,str):
                self.assertEqual(a,b);self.assertIs(type(a),type(b))
        visit(original,value)

    def test_missing_resolver_or_wrong_world_cannot_silently_restore_sources(self):
        from gentactix import observation_codec as codec
        value=self.encoded()
        with self.assertRaises(ValueError):codec.decode(value)
        def wrong(query):
            response=self.resolver(query);response['world_version']='0'*64;return response
        with self.assertRaises(ValueError):codec.decode(value,resolve=wrong)

    def test_changed_source_text_missing_unit_or_other_id_is_rejected(self):
        from gentactix import observation_codec as codec
        for kind in ('text','missing','id','invalid_unit'):
            def corrupt(query):
                response=self.resolver(query)
                if kind=='text':response['units'][0]={k:v for k,v in response['units'][0].items() if k in ('id','name')}
                elif kind=='missing':response['units']=[]
                elif kind=='id':response['units'][0]['id']='other'
                else:response['units'][0]=None
                return response
            with self.subTest(kind=kind),self.assertRaises(ValueError):codec.decode(self.encoded(),resolve=corrupt)

    def test_malformed_reference_query_or_digest_is_not_a_valid_source(self):
        from gentactix import observation_codec as codec
        original=self.encoded()
        for change in ('hash','query','version','numeric'):
            value=copy.deepcopy(original);entry=next(iter(value['_provenance']['deferred'].values()))
            if change=='hash':entry['digest']='0'*64
            elif change=='query':entry['query']['detail']=False
            elif change=='version':value['_provenance']['world_version']='wrong'
            else:value['red_units'][0]['lat']+=.01
            with self.subTest(change=change),self.assertRaises(ValueError):codec.decode(value,resolve=self.resolver)

    def test_detail_query_catalogue_contains_only_retrievable_source_text(self):
        from backend import afsim_state
        from gentactix import observation_codec as codec
        before=copy.deepcopy(self.session);queries=afsim_state.source_queries(self.session)
        self.assertTrue(queries)
        for text,query in queries.items():
            self.assertEqual(set(query),{'ids','limit','detail'})
            detail=self.resolver(query)
            self.assertIn(text,codec.source_texts(detail['units'][0]))
        self.assertEqual(self.session,before)

    def test_legacy_json_prompt_still_has_self_contained_sources(self):
        from backend import dsh_simulation
        from gentactix import observation_codec as codec
        world=self.session['war_state'];message=dsh_simulation.prompt(world)
        value=json.loads(message.split('\n当前态势：',1)[1].split('\n史料：',1)[0])
        self.assertEqual(codec.decode(value),dsh_simulation.observation_view(world))
        self.assertNotIn('deferred',value['_provenance'])

    def test_all_frozen_catalogue_versions_roundtrip_with_optional_detail_references(self):
        from pathlib import Path
        from gentactix import historical_initial,observation_codec as codec
        query=dict(ids=['catalogue-codec-fixture'],limit=1,detail=True)
        versions=deferred=0;catalogue=historical_initial.catalog()
        for row in catalogue:
            for path in sorted((Path('data/historical_initial')/row['profile_id']).glob('*.json')):
                with self.subTest(profile=row['profile_id'],version=path.stem):
                    original=json.loads(path.read_text())
                    value=codec.encode(original,source_queries={t:query for t in codec.source_texts(original)},
                                       world_version='a'*64)
                    def resolve(_query):
                        self.assertEqual(_query,query)
                        return dict(world_version='a'*64,units=[dict(id=query['ids'][0],source_note=original)])
                    self.assertEqual(codec.decode(value,resolve=resolve),original)
                    deferred+=value.get('_provenance',{}).get('version')==codec.DETAIL_VERSION
                    versions+=1
        # Frozen source definitions need not contain repeated long source text;
        # the codec must retain their original representation when none saves space.
        self.assertEqual(len(catalogue),45);self.assertGreaterEqual(versions,57)

    def test_wuhan79_runtime_world_keeps_all_identities_arrivals_and_values(self):
        from backend import afsim_state,dsh_simulation
        from gentactix import commands,historical_operations,observation_codec as codec
        from tools.qa.large_formation_fixture import inputs
        source,parameters=inputs()
        session=dict(id='source-detail79-qa',role_epoch=0,turn_count=0,time_step='30分钟',
                     war_state=historical_operations.initial(source,parameters))
        saved=copy.deepcopy(session);view=dsh_simulation.observation_view(session['war_state'])
        value=codec.encode(view,source_queries=afsim_state.source_queries(session),
                           world_version=commands.world_version(session))
        restored=codec.decode(value,resolve=lambda q:afsim_state.observation(session,q))
        self.assertEqual(restored,view)
        self.assertEqual(len(restored['red_units'])+len(restored['blue_units']),79)
        self.assertEqual(session,saved)

    def test_native_advance_binds_detail_sources_but_json_advance_does_not(self):
        from backend import dsh_simulation,harness_engine as h
        from gentactix import commands
        from unittest.mock import patch
        class Captured(Exception):pass
        for mode in ('native','json'):
            session=copy.deepcopy(self.session);session['agent_mode']=mode;messages=[]
            def capture(message,**kwargs):messages.append(message);raise Captured()
            with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=capture):
                with self.assertRaises(Captured):
                    dsh_simulation.advance(session,commands.prepare(session),h.RunObserver('source detail QA'))
            value=json.loads(messages[0].split('\n当前态势：',1)[1].split('\n史料：',1)[0])
            self.assertEqual('deferred' in value['_provenance'],mode=='native')
            if mode=='native':self.assertIn('get_afsim_observation',messages[0])
            self.assertEqual(session['war_state'],self.session['war_state'])


if __name__=='__main__':unittest.main()
