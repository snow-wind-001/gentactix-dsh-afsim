"""A sourced action involving elements must not imply the whole parent moved."""
import copy
import re
import unittest

from gentactix import historical_initial as hi, historical_links as links
from gentactix import historical_operations as ho
from verify_historical_links import BATTLE, linked_definition, snapshot


def scoped_definition():
    definition=linked_definition();event=definition['phases'][1]['operations'][0]
    event['unit_scopes']={identity:{'extent':'elements','scope':'只关联本地投入部，不证明全建制到场或同时行动。',
                                  'evidence':copy.deepcopy(event['evidence'])}
                          for identity in event['unit_ids']}
    return definition,event


class HistoricalParticipationScopeTests(unittest.TestCase):
    def test_scoped_event_validates_without_adding_executing_units_or_facts(self):
        old=linked_definition();definition,event=scoped_definition()
        self.assertTrue(hi.validate_definition(definition))
        self.assertEqual(definition['units'],old['units'])
        self.assertEqual(ho.partition(snapshot(definition)),ho.partition(snapshot(old)))
        self.assertTrue(all(u['facts']['personnel']['value']is None for u in definition['units']))

    def test_scope_requires_exact_event_identity_coverage(self):
        for defect in ['missing','extra','empty','not_mapping']:
            definition,event=scoped_definition()
            if defect=='missing':event['unit_scopes'].pop(event['unit_ids'][0])
            if defect=='extra':event['unit_scopes']['invented']=copy.deepcopy(next(iter(event['unit_scopes'].values())))
            if defect=='empty':event['unit_scopes']={}
            if defect=='not_mapping':event['unit_scopes']=[]
            with self.subTest(defect=defect),self.assertRaises(ValueError):hi.validate_definition(definition)

    def test_extent_scope_and_evidence_are_strict_and_do_not_accept_quantity_injection(self):
        for defect in ['extent','bool_extent','scope','source','no_evidence','personnel']:
            definition,event=scoped_definition();scope=next(iter(event['unit_scopes'].values()))
            if defect=='extent':scope['extent']='entire_division_assumed'
            if defect=='bool_extent':scope['extent']=True
            if defect=='scope':scope['scope']=' '
            if defect=='source':scope['evidence'][0]['source_id']='invented'
            if defect=='no_evidence':scope['evidence']=[]
            if defect=='personnel':scope['personnel']=6000
            with self.subTest(defect=defect),self.assertRaises(ValueError):hi.validate_definition(definition)

    def test_native_history_paging_preserves_scope_without_mutating_world(self):
        from backend import agent_tools
        definition,event=scoped_definition();session={'war_state':{'historical_initial':snapshot(definition)},'use_rag':False}
        saved=copy.deepcopy(session);response=agent_tools.exec_retrieve_history(session,{'kind':'operations','limit':1})
        self.assertEqual(response['operations'][0]['unit_scopes'],event['unit_scopes'])
        self.assertEqual(session,saved)

    def test_frame_binding_preserves_partial_scope_and_does_not_invent_a_subunit(self):
        definition,event=scoped_definition();initial=snapshot(definition)
        wire={'event_key':event['id'],'historical_binding':{'phase_id':initial['phase_id'],'operation_id':event['id']}}
        result=links.frame_binding(initial,wire)
        self.assertEqual(result['unit_scopes'],event['unit_scopes'])
        self.assertEqual({u['id']for u in result['units']},set(event['unit_ids']))
        self.assertIsNone(result['places'][0]['position'])

    def test_old_events_remain_unchanged_and_do_not_acquire_whole_unit_claims(self):
        definition=linked_definition();saved=copy.deepcopy(definition)
        self.assertTrue(hi.validate_definition(definition));s=snapshot(definition)
        response=links.observation({'war_state':{'historical_initial':s}},{'kind':'operations'})
        self.assertNotIn('unit_scopes',response['operations'][0])
        self.assertEqual(definition,saved)


class ContemporaryDivisionSourcesTests(unittest.TestCase):
    def definitions(self):
        from tools.upgrade_division90_sources import build_wanjialing,build_wuhan
        return build_wanjialing(),build_wuhan()

    def test_versions_add_no_invented_subunits_numbers_or_coordinates(self):
        for definition,version,base in zip(self.definitions(),['1.6.0','1.3.0'],['1.5.0','1.2.0']):
            old=hi.definition(definition['battle'],base)
            self.assertEqual(definition['version'],version);self.assertTrue(hi.validate_definition(definition))
            self.assertEqual({u['id']for u in definition['units']},{u['id']for u in old['units']})
            self.assertEqual({u['id']:u['facts']for u in definition['units']},{u['id']:u['facts']for u in old['units']})
            self.assertFalse(any(definition['coverage'][k]for k in ['order_of_battle_complete','opening_deployment_complete','strength_complete']))

    def test_primary_account_is_distinct_from_unread_original_archive_and_late_october_report(self):
        for definition in self.definitions():
            source=definition['sources']['WU1940_90']
            self.assertEqual(source['evidence_kind'],'published_memoir')
            self.assertFalse(source['original_archive_examined'])
            self.assertIn('1940',source['title']);self.assertIn('37—39',source['limitations'])
            self.assertNotIn('106139',source['url'])

    def test_all_ten_source_events_preserve_scope_pages_and_clock_precision(self):
        for definition in self.definitions():
            operations=[op for p in definition['phases']for op in p.get('operations',[])if 'WU1940'in op['id']]
            self.assertEqual(len(operations),10)
            for op in operations:
                self.assertEqual(set(op['unit_scopes']),set(op['unit_ids']))
                self.assertTrue(all(v['extent']in ['elements','reference']for v in op['unit_scopes'].values()))
                self.assertTrue(all(p['position']is None for p in op['places']))
                self.assertTrue(all(e['source_id']=='WU1940_90' and '印本'in e['locator']for e in op['evidence']))
                self.assertNotIn('00:00',op['date']['label'])
            support=next(op for op in operations if op['id'].endswith('Oct6-support'))
            self.assertEqual(support['date']['precision'],'hour');self.assertIn('20时',support['date']['label'])
            self.assertEqual(support['unit_scopes']['ww2.cn.division90']['extent'],'elements')
            self.assertEqual(support['unit_scopes']['ww2.cn.division58']['extent'],'reference')

    def test_campaign_windows_keep_existing_actors_estimates_and_reference_only_milestones(self):
        from tools.upgrade_division90_sources import build_wanjialing_window,build_wuhan_window
        from gentactix import campaign_windows as cw
        a,b=self.definitions()
        for definition,window,identity,base in [(a,build_wanjialing_window(a),'WJL-oct6-10','1.6.0'),(b,build_wuhan_window(b),'WH-northern-sep17-18','1.2.0')]:
            old=cw.load(identity,base)
            self.assertEqual(window['parameter_estimates'],old['parameter_estimates'])
            self.assertEqual({i for i,r in window['units'].items()if r['representation']=='actor'},
                             {i for i,r in old['units'].items()if r['representation']=='actor'})
            self.assertTrue(all(m['policy']=='reference_only'for m in window['milestones']))
            cw.validate_definition(window,hi._materialize(definition,window['start_phase_id'])['historical_initial'])

    def test_frozen_replay_new_sources_do_not_fill_unit_positions_or_effects(self):
        from gentactix import history_replay
        a,_=self.definitions();initial=hi._materialize(a,'oct6_orders')['historical_initial']
        pack=history_replay.dataset(BATTLE);pack.pop('dataset_hash');pack['version']=history_replay.PINNED_VERSION
        history_replay._merge_missing_operations(pack,initial);links.bind_events(pack,initial);pack['dataset_hash']=history_replay._digest(pack)
        keys=[e.get('event_key')for e in pack['events']];target=next(key for key in keys if key and key.endswith('WU1940-Oct6-support'))
        world=history_replay.frame_pinned({'pack':pack,'initial':initial},keys.index(target))
        self.assertTrue(history_replay.validate(world))
        self.assertEqual(world['history_replay']['source_operation']['unit_scopes']['ww2.cn.division90']['extent'],'elements')
        self.assertTrue(all(u['lat']is None and u['personnel']['current']is None for u in world['red_units']+world['blue_units']))
        self.assertNotIn('combined_arms',world)

    def test_new_documentary_phases_are_not_claimed_as_complete_numeric_initial_states(self):
        a,_=self.definitions()
        for phase in ['oct1_div90_local','oct3_div90_local','oct4_div90_local']:
            initial=hi._materialize(a,phase)['historical_initial']
            with self.assertRaises(ValueError):ho.configuration_template(initial)

    def test_old_definitions_defaults_and_window_pins_stay_available(self):
        from gentactix import campaign_windows as cw
        from tools import upgrade_wanjialing_140
        from tools.upgrade_northern_campaign import wanjialing,wuhan
        self.assertEqual(hi.definition(BATTLE,'1.4.0'),upgrade_wanjialing_140.build())
        self.assertEqual(hi.definition(BATTLE,'1.5.0'),wanjialing())
        self.assertEqual(hi.definition('抗日战争-武汉会战-1938.06至1938.10','1.2.0'),wuhan())
        self.assertEqual(hi.definition(BATTLE)['version'],'1.0.0')
        self.assertEqual(cw.load('WJL-oct6-10','1.6.0')['historical_initial']['version'],'1.5.0')

    def test_new_wuhan_replay_does_not_jump_backwards_between_battlefield_axes(self):
        from gentactix import history_replay as hr
        _,d=self.definitions();initial=hi._materialize(d,'campaign_opening')['historical_initial']
        pack=hr.dataset(d['battle']);pack.pop('dataset_hash');pack['version']=hr.PINNED_VERSION
        hr._merge_missing_operations(pack,initial)
        days=[re.match(r'\d{4}-\d{2}-\d{2}',e['date_label']).group()
              for e in pack['events']if re.match(r'\d{4}-\d{2}-\d{2}',e['date_label'])]
        self.assertEqual(days,sorted(days))
        self.assertEqual(pack['ordering']['version'],'dated-events-1')
        self.assertIn('同日',pack['ordering']['scope'])

    def test_ordering_is_explicit_and_unknown_clock_or_overlapping_period_is_not_fabricated(self):
        from gentactix import history_replay as hr
        self.assertTrue(callable(getattr(hr,'_sort_dated_events',None)))
        events=[{'date_label':'1938-10-06，20时','precision':'hour'},
                {'date_label':'1938年9月下旬概览','precision':'range'},
                {'date_label':'1938-10-06，04时至19时','precision':'period'},
                {'date_label':'1938-10-01，当日','precision':'day'}]
        saved=copy.deepcopy(events);result=hr._sort_dated_events(events)
        self.assertEqual(result,[events[1],events[3],events[0],events[2]])
        self.assertEqual(events,saved)
        self.assertNotIn('00:00',str(result))

    def test_unknown_ordering_version_and_impossible_calendar_date_reject(self):
        from gentactix import history_replay as hr
        for value in ['guess_hours',True,{},None]:
            definition=linked_definition();definition['event_order']=value
            with self.subTest(value=value),self.assertRaises(ValueError):hi.validate_definition(definition)
        with self.assertRaises(ValueError):hr._sort_dated_events([{'date_label':'1938-02-30，当日'}])

    def test_frozen_ordering_cannot_be_removed_or_reversed_even_if_pack_hash_is_recomputed(self):
        from gentactix import history_replay as hr
        for defect in ['missing','reverse']:
            pinned=hr.pin(BATTLE,version='1.6.0');pack=pinned['pack']
            if defect=='missing':pack.pop('ordering')
            else:pack['events'].reverse()
            pack['dataset_hash']=hr._digest({k:v for k,v in pack.items()if k!='dataset_hash'})
            with self.subTest(defect=defect),self.assertRaises(ValueError):hr.frame_pinned(pinned,0)

    def test_frame_scope_tampering_does_not_turn_elements_into_whole_unit_action(self):
        from gentactix import history_replay as hr
        pinned=hr.pin(BATTLE,version='1.6.0');keys=[e.get('event_key')for e in pinned['pack']['events']]
        index=keys.index('WJL-WU1940-Oct6-support');world=hr.frame_pinned(pinned,index)
        world['history_replay']['source_operation']['unit_scopes']['ww2.cn.division90']['extent']='whole'
        with self.assertRaises(ValueError):hr.validate(world)


if __name__=='__main__':unittest.main()
