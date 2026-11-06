"""Observed membership and ancestry must describe actual command authority."""
import copy
import unittest
from unittest.mock import patch

from gentactix import commands, force_organization as f
from tools.qa.initial_command_fixture import session as opening_session
from verify_force_organization import session as legacy_session


class ForceObservationTests(unittest.TestCase):
    def test_legacy_command_members_exclude_temporarily_assigned_leaves(self):
        s=legacy_session();ids=[i for i,(e,u) in commands.resolve_units(s).items() if e['team']=='blue']
        node=next(n for n in f.view(s)['nodes'] if ids[0] in n['execution_ids'])
        s['force_organization']=f.detach(s,[ids[0]],'独立配属','QA显式抽调')
        before=copy.deepcopy(s)
        current=f.observation(s,{'kind':'members','hierarchy':'command','node_id':node['id']})
        administrative=f.observation(s,{'kind':'members','hierarchy':'historical','node_id':node['id']})
        self.assertEqual({r['command_id'] for r in current['items']},set(f.effective_member_ids(s,node['id'])))
        self.assertNotIn(ids[0],{r['command_id'] for r in current['items']})
        self.assertIn(ids[0],{r['command_id'] for r in administrative['items']})
        self.assertEqual(s,before)

    def test_opening_paths_distinguish_ancestors_from_members_and_admin_reference(self):
        s=opening_session();before=copy.deepcopy(s)
        r=f.observation(s,{'kind':'members','node_id':'ww2.cn.army66'})
        self.assertEqual(r['observation_version'],'force-observation-2')
        for row in r['items']:
            self.assertEqual([p['id'] for p in row['command_path']],row['command_chain'])
            self.assertEqual(row['command_chain'],['ww2.cn.warzone9','ww2.cn.corps1','ww2.cn.army66'])
            self.assertTrue(all(p['name'] and p['basis']=='source_opening' for p in row['command_path']))
            self.assertNotIn(row['historical_unit_id'],row['command_chain'])
        attached=next(row for row in r['items'] if row['name']=='第161师万家岭投入部')
        self.assertEqual(attached['administrative_path'][-1]['id'],'ww2.cn.division161')
        self.assertEqual(attached['command_path'][-1]['id'],'ww2.cn.army66')
        self.assertIn('上级',r['field_semantics']['command_chain'])
        self.assertEqual(s,before)

    def test_legacy_software_authority_is_labeled_and_not_claimed_as_opening_evidence(self):
        s=legacy_session();r=f.observation(s,{'kind':'members'})
        row=next(x for x in r['items'] if x['command_chain'])
        self.assertTrue(all(p['basis']=='legacy_administrative_fallback' for p in row['command_path']))
        self.assertNotIn('command_baseline',r)

    def test_temporary_ancestor_chain_overrides_opening_but_admin_path_stays(self):
        s=opening_session();ids=f.effective_member_ids(s,'ww2.cn.army66')
        s['force_organization']=f.detach(s,ids,'北侧总指挥','QA临时方向')
        top=f.state(s)['groups'][0]['id']
        s['force_organization']=f.detach(s,ids[:1],'先遣群','QA下级任务',parent_id=top)
        child=next(g['id'] for g in f.state(s)['groups'] if g['label']=='先遣群')
        r=f.observation(s,{'kind':'members','node_id':top})
        row=next(x for x in r['items'] if x['command_id']==ids[0])
        self.assertEqual(row['command_chain'],[top,child])
        self.assertEqual([p['name'] for p in row['command_path']],['北侧总指挥','先遣群'])
        self.assertTrue(all(p['basis']=='temporary_assignment' for p in row['command_path']))
        self.assertTrue(row['administrative_path'])
        self.assertEqual(f.observation(s,{'kind':'members','node_id':'ww2.cn.army66'})['total'],0)

    def test_arrival_wait_is_distinct_from_physical_availability(self):
        from tools.qa.campaign_fixture import inputs
        from gentactix import historical_operations
        s=legacy_session();s['war_state']=historical_operations.initial(*inputs())
        before=copy.deepcopy(s);r=f.observation(s,{'kind':'members'})
        row=next(x for x in r['items'] if x['historical_unit_id']=='ww2.jp.sakamoto_detachment')
        self.assertTrue(row['available']);self.assertEqual(row['arrival_wait_seconds'],3600)
        self.assertEqual(row['operational_status'],'waiting_arrival')
        self.assertEqual(s,before)

    def test_exercise_only_actor_does_not_acquire_a_historical_path(self):
        from gentactix import synthetic_history as sh,missions
        s=opening_session();binding=s['war_state']['mission']['definition']['historical_calculation']
        config=sh.seed(binding)['configuration'];new=copy.deepcopy(config['teams']['red'][0])
        new['name']='新演习部队';config['teams']['red'].append(new)
        s['war_state']=missions.from_definition(sh.definition(binding,config))
        row=next(r for r in f.observation(s,{'kind':'members'})['items'] if r['name']==new['name'])
        self.assertEqual(row['command_path'],[]);self.assertEqual(row['administrative_path'],[])

    def test_member_details_are_enriched_only_for_the_requested_page(self):
        from gentactix import campaign
        s=opening_session();seen=[];release=campaign.release_seconds
        def counted(world,unit):
            seen.append(unit['name']);return release(world,unit)
        with patch.object(campaign,'release_seconds',side_effect=counted):
            r=f.observation(s,{'kind':'members','limit':1,'offset':2})
        self.assertEqual(set(seen),{r['items'][0]['name']})
        self.assertEqual(r['total'],6);self.assertIsNotNone(r['next_args'])

    def test_node_counts_and_totals_match_effective_member_query(self):
        for s,node_id in ((opening_session(),'ww2.cn.army66'),(legacy_session(),None)):
            node=next((n for n in f.view(s)['nodes'] if n['id']==node_id),None)
            if node is None:node=next(n for n in f.view(s)['nodes'] if n['execution_ids']);node_id=node['id']
            ids=f.effective_member_ids(s,node_id)
            s['force_organization']=f.detach(s,ids,'另行指挥','QA整体抽调，来源树保留')
            current=f.observation(s,{'kind':'nodes','node_id':node_id,'limit':32})
            row=next(r for r in current['items'] if r['id']==node_id)
            members=f.observation(s,{'kind':'members','node_id':node_id})
            self.assertEqual(row['execution_count'],members['total'])
            self.assertEqual(row['totals']['units'],members['total'])
            self.assertEqual(row['totals']['current'],0)
            self.assertGreater(row['historical_totals']['units'],0)
            self.assertEqual(current['totals_scope'],'all_deployed_leaves_not_selection')

    def test_new_group_ids_are_session_scoped_and_never_reuse_retired_references(self):
        s=opening_session();unit=f.effective_member_ids(s,'ww2.cn.army66')[0]
        s['force_organization']=f.detach(s,[unit],'第一分遣','QA短引用')
        first=f.state(s)['groups'][0]['id'];self.assertEqual(first,'task:1')
        s['force_organization']=f.detach(s,[unit],'第二分遣','QA重组，原群退出')
        second=f.state(s)['groups'][0]['id'];self.assertEqual(second,'task:2')
        self.assertNotIn(first,{g['id'] for g in f.state(s)['groups']})
        self.assertIn(first,{g['id'] for e in f.state(s)['events'] for g in e['after']})
        restored=copy.deepcopy(s)
        restored['force_organization']=f.detach(restored,[unit],'第三分遣','QA冷恢复后继续')
        self.assertEqual(f.state(restored)['groups'][0]['id'],'task:3')
        branch=copy.deepcopy(s);branch['id']='fork-qa'
        key=next(k for k,row in f.leaves(s).items() if row[0]==unit)
        with self.assertRaises(ValueError):f.detach(branch,[unit],'误用原局命令ID','QA跨局命令引用拒绝')
        branch_unit=f.leaves(branch)[key][0]
        branch['force_organization']=f.detach(branch,[branch_unit],'分支分遣','QA分支独立作用域')
        self.assertEqual(f.state(branch)['groups'][0]['id'],'task:3')
        self.assertEqual(f.state(s)['groups'][0]['id'],second)

    def test_existing_uuid_groups_and_imported_numeric_ids_are_preserved(self):
        s=opening_session();unit=f.effective_member_ids(s,'ww2.cn.army66')[0]
        s['force_organization']=f.detach(s,[unit],'旧分遣','QA旧群')
        s['force_organization']['groups'][0]['id']='task:legacy-uuid-preserved'
        old=copy.deepcopy(s)
        s['force_organization']=f.detach(s,[unit],'新下级','QA兼容混合引用',parent_id='task:legacy-uuid-preserved')
        self.assertEqual(s['force_organization']['groups'][0]['id'],'task:legacy-uuid-preserved')
        self.assertEqual(s['war_state'],old['war_state'])
        # Valid older imports can use arbitrary strings; never collide with one.
        imported=opening_session();ids=f.effective_member_ids(imported,'ww2.cn.army66')
        imported['force_organization']=f.detach(imported,[ids[0]],'保留群','QA')
        imported['force_organization']['groups'][0]['id']='task:2'
        imported['force_organization']=f.detach(imported,[ids[1]],'另一群','QA')
        self.assertEqual(len({g['id'] for g in f.state(imported)['groups']}),2)


if __name__=='__main__':unittest.main(verbosity=2)
