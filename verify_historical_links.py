"""Sourced phase events bind actual identities without inventing live state."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from gentactix import historical_initial as hi,historical_operations as ho,history_replay

BATTLE='抗日战争-万家岭战役-1938.09下旬至1938.10'


def linked_definition():
    d=hi.definition(BATTLE,'1.0.0');p=d['phases'][1]
    p['operations']=[{'id':'WJL-test-attack','kind':'attack','date':{'label':'1938-10-07，当日','precision':'day'},
        'unit_ids':['ww2.cn.army66','ww2.jp.division106'],
        'places':[{'name':'石堡山','position':None,'evidence':copy.deepcopy(p['evidence'])}],
        'description':'仅核任务与地名，未核单位坐标和局部兵额。',
        'evidence':copy.deepcopy(p['evidence']),'limitations':'公开回顾；不表示原始命令已核。'}]
    p['relations']=[{'id':'WJL-test-command','kind':'operational_command','parent_id':'ww2.cn.corps1',
        'child_id':'ww2.cn.army66','scope':'仅本阶段的有出处作战配属参考。','evidence':copy.deepcopy(p['evidence'])}]
    return d


def snapshot(d):
    return hi._materialize(d,'oct7_attack')['historical_initial']


class HistoricalLinkTests(unittest.TestCase):
    def test_sourced_operations_validate_without_changing_unit_counts_or_facts(self):
        d=linked_definition();self.assertTrue(hi.validate_definition(d))
        s=snapshot(d);self.assertEqual(len(ho.partition(s)),4)
        self.assertIsNone(d['units'][2]['facts']['personnel']['value'])

    def test_missing_identity_source_duplicate_event_and_relation_cycles_reject(self):
        for defect in ('unit','source','duplicate','cycle','position'):
            d=linked_definition();p=d['phases'][1]
            if defect=='unit':p['operations'][0]['unit_ids'].append('invented')
            if defect=='source':p['operations'][0]['evidence'][0]['source_id']='invented'
            if defect=='duplicate':d['phases'][0]['operations']=copy.deepcopy(p['operations'])
            if defect=='cycle':p['relations'].append({**copy.deepcopy(p['relations'][0]),'id':'reverse',
                'parent_id':'ww2.cn.army66','child_id':'ww2.cn.corps1'})
            if defect=='position':p['operations'][0]['places'][0]['position']={'lat':0,'lng':0}
            with self.subTest(defect=defect),self.assertRaises(ValueError):hi.validate_definition(d)

    def test_native_history_reads_frozen_phase_links_when_rag_is_off(self):
        from backend import agent_tools
        s={'war_state':{'historical_initial':snapshot(linked_definition())},'use_rag':False}
        before=copy.deepcopy(s)
        r=agent_tools.exec_retrieve_history(s,{'kind':'operations','limit':1})
        self.assertTrue(r['ok'],r);self.assertEqual(r['total'],1)
        self.assertEqual(r['operations'][0]['unit_ids'],['ww2.cn.army66','ww2.jp.division106'])
        self.assertIsNone(r['operations'][0]['places'][0]['position']);self.assertEqual(s,before)
        self.assertEqual(r['definition_hash'],s['war_state']['historical_initial']['definition_hash'])
        with self.assertRaises(ValueError):
            agent_tools.exec_retrieve_history(s,{'kind':'operations','definition_hash':'stale'})

    def test_bound_replay_event_marks_only_reported_units_and_keeps_locations_unknown(self):
        pack=history_replay.dataset(BATTLE);d=linked_definition();d['version']='1.1.0'
        # This explicit fixture joins one editorial event to one frozen source operation.
        event=pack['events'][2];event['event_key']='WJL-test-attack'
        with patch.object(hi,'definition',return_value=d):
            with patch.object(history_replay,'dataset',return_value=pack):
                pinned=history_replay.pin(BATTLE,version='1.1.0')
        world=history_replay.frame_pinned(pinned,2)
        self.assertTrue(history_replay.validate(world))
        bound=world['history_replay']['source_operation']
        self.assertEqual(bound['id'],'WJL-test-attack')
        for unit in world['red_units']+world['blue_units']:
            self.assertIsNone(unit['lat']);self.assertIsNone(unit['personnel']['current'])
            self.assertEqual(unit['frame_operation_ids'],['WJL-test-attack'] if unit['historical_unit_id'] in bound['unit_ids'] else [])
        view=history_replay.observation(world)
        self.assertEqual(view['source_operation']['places'][0]['name'],'石堡山')

    def test_partial_parent_needs_explicit_local_remainder_declaration(self):
        from gentactix import campaign_scope
        d=hi.definition(BATTLE,'1.0.0');child=copy.deepcopy(d['units'][2]);child.update(id='ww2.cn.army4.known',name='第4军已核投入部',parent_id='ww2.cn.army4')
        d['units'][2]['children_coverage']={'status':'partial','scope':'只核一个投入部，余部未知。','evidence':copy.deepcopy(child['evidence'])}
        d['units'].append(child);s=snapshot(d)
        with self.assertRaisesRegex(ValueError,'完整历史初态'):
            ho.configuration_template(s)
        # QA-only coverage must not inherit an unchanged published guide.
        with patch.object(ho,'objective_guidance',return_value=None):
            p=ho.configuration_template(s)
        self.assertIn('oob_coverage',p)
        with self.assertRaises(ValueError):campaign_scope.validate_local(s,p)
        p['oob_coverage']['remainders']['ww2.cn.army4']={'policy':'excluded_unquantified','assumption':'仅计算所列投入部；未知余部明确不投入。'}
        campaign_scope.validate_local(s,p)
        p['oob_coverage']['remainders']['ww2.cn.army4']['policy']='covered_by_children'
        with self.assertRaises(ValueError):campaign_scope.validate_local(s,p)


class WanjialingSourceTests(unittest.TestCase):
    def test_additive_version_has_six_known_leaves_and_four_explicit_remainders(self):
        from gentactix import campaign_scope
        s=hi.initial(BATTLE,'oct7_attack',version='1.1.0')['historical_initial']
        ids=ho.partition(s);self.assertEqual(len(ids),6)
        self.assertNotIn('ww2.cn.army66',ids)
        self.assertIn('ww2.cn.division161.wjl_part',ids)
        self.assertEqual(len(campaign_scope.local_coverage(s)),4)
        self.assertEqual(hi.definition(BATTLE)['version'],'1.0.0')
        d=s['definition'];index={u['id']:u for u in d['units']}
        self.assertIsNone(index['ww2.cn.division161']['parent_id'])
        self.assertTrue(all(u['facts'][k]['value'] is None for u in d['units'] for k in ('personnel','equipment','position')))
        self.assertFalse(d['sources']['WJL_GUO']['original_archive_examined'])
        self.assertEqual(ho.objective_guidance(s)['binding']['initial_version'],'1.1.0')

    def test_document_only_days_do_not_become_executable_same_day_deployments(self):
        for phase in ('oct6_orders','oct8_counterattacks'):
            s=hi.initial(BATTLE,phase,version='1.1.0')['historical_initial']
            with self.subTest(phase=phase),self.assertRaises(ValueError):ho.partition(s)

    def test_seven_bound_events_survive_live_sources_becoming_unavailable(self):
        pinned=history_replay.pin(BATTLE,version='1.1.0');count=0
        with patch.object(history_replay,'dataset',side_effect=AssertionError('frozen')),patch.object(hi,'DATA_ROOT',hi.DATA_ROOT/'offline'):
            for cursor in range(len(pinned['pack']['events'])):
                w=history_replay.frame_pinned(pinned,cursor);self.assertTrue(history_replay.validate(w))
                if w['history_replay'].get('source_operation'):count+=1
                self.assertTrue(all(u['lat'] is None and u['personnel']['current'] is None for u in w['red_units']+w['blue_units']))
        self.assertEqual(count,7)

    def test_relations_and_operations_page_without_duplicates_or_state_changes(self):
        from gentactix import historical_links as links
        s={'war_state':{'historical_initial':hi.initial(BATTLE,'oct7_attack',version='1.1.0')['historical_initial']}}
        before=copy.deepcopy(s)
        for kind,total in [('operations',3),('relations',4)]:
            args={'kind':kind,'limit':2};ids=[]
            while args:
                r=links.observation(s,args);ids += [x['id'] for x in r[kind]];args=r['next_args']
            self.assertEqual(len(ids),total);self.assertEqual(len(set(ids)),total)
        self.assertEqual(s,before)

    def test_replay_query_defaults_to_bound_event_phase_instead_of_campaign_reference(self):
        from gentactix import historical_links
        world=history_replay.frame_pinned(history_replay.pin(BATTLE,version='1.1.0'),7)
        self.assertEqual(world['historical_initial']['phase_id'],'campaign_reference')
        r=historical_links.observation({'war_state':world},{'kind':'operations','limit':1})
        self.assertEqual(r['phase_id'],'oct8_counterattacks');self.assertEqual(r['total'],2)

    def test_api_can_select_new_replay_version_and_reject_misapplied_version(self):
        from fastapi.testclient import TestClient
        from backend import main,harness_engine
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
            'GENTACTIX_SESSION_DIR':folder+'/sessions','GENTACTIX_TRACE_DIR':folder+'/traces'}), \
                patch.object(harness_engine,'ask_xuanji',return_value=('', '固定离线讲解夹具；真实模型另行验收。')):
            client=TestClient(main.app)
            preview=client.get('/api/historical-initial',params={'battle':BATTLE,'version':'1.1.0'})
            self.assertEqual(preview.status_code,200,preview.text)
            self.assertEqual(preview.json()['initial']['version'],'1.1.0')
            req={'scenario':'有来源的万家岭事件关联','battle':BATTLE,'product_mode':'analysis','simulation_mode':'replay',
                'execution_backend':'narrative','historical_source_version':'1.1.0'}
            r=client.post('/api/sessions',json=req);self.assertEqual(r.status_code,200,r.text);sid=r.json()['session_id']
            try:
                self.assertEqual(main._SESSIONS[sid]['source_replay_snapshot']['initial']['version'],'1.1.0')
                result=client.post('/api/sessions/'+sid+'/init');self.assertEqual(result.status_code,200,result.text)
            finally:main._SESSIONS.pop(sid,None)
            r=client.post('/api/sessions',json={**req,'product_mode':'historical','simulation_mode':'open'})
            self.assertEqual(r.status_code,422,r.text)


if __name__=='__main__':unittest.main()
