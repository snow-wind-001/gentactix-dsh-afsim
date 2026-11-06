"""Temporary command hierarchy must never duplicate execution or physical ledgers."""
import copy
import unittest

from gentactix import commands,force_organization as f
from tools.qa.large_formation_fixture import inputs
from gentactix import historical_operations as ho


def session():
    s,p=inputs()
    return dict(id='hierarchy-qa',turn_count=0,role_epoch=0,product_mode='historical',
        simulation_mode='open',execution_backend='narrative',time_step='30分钟',war_state=ho.initial(s,p))


class HierarchyTests(unittest.TestCase):
    def tree(self):
        s=session();ids=[i for i,(e,_) in commands.resolve_units(s).items() if e['team']=='red']
        s['force_organization']=f.detach(s,ids[:8],'第一方向','QA已有叶子任务组织')
        root=s['force_organization']['groups'][0]['id']
        s['force_organization']=f.detach(s,ids[:4],'左翼群','QA分兵',parent_id=root)
        child=next(g['id'] for g in s['force_organization']['groups'] if g['label']=='左翼群')
        s['force_organization']=f.detach(s,ids[:2],'先遣群','QA三级指挥',parent_id=child)
        return s,ids,root,child

    def test_three_levels_aggregate_unique_leaves_and_orders(self):
        s,ids,root,child=self.tree();view=f.view(s)
        self.assertEqual(set(f.member_ids(s,root)),set(ids[:8]))
        self.assertEqual(set(f.member_ids(s,child)),set(ids[:4]))
        row=next(g for g in view['groups'] if g['id']==root)
        self.assertEqual(row['totals']['current'],24000)
        self.assertEqual(len(row['direct_member_ids']),4)
        self.assertEqual(row['depth'],0)
        queued=f.queue(s,root,dict(action='hold',duration='next'))
        self.assertEqual({o['unit_id'] for o in queued['orders']},set(ids[:8]))
        self.assertEqual(len(queued['orders']),8)

    def test_wrap_reparent_merge_preserve_all_unit_ledgers(self):
        s,ids,root,child=self.tree();before=copy.deepcopy(s['war_state'])
        s['force_organization']=f.detach(s,ids[8:10],'第二方向','QA')
        other=next(g['id'] for g in s['force_organization']['groups'] if g['label']=='第二方向')
        s['force_organization']=f.wrap(s,[root,other],'临时总指挥','QA统一指挥，保持下级组织')
        top=next(g['id'] for g in s['force_organization']['groups'] if g['label']=='临时总指挥')
        s['force_organization']=f.reparent(s,child,other,'QA跨方向转隶')
        self.assertEqual(len(f.member_ids(s,root)),4)
        self.assertEqual(len(f.member_ids(s,other)),6)
        self.assertEqual(set(f.member_ids(s,top)),set(ids[:10]))
        s['force_organization']=f.merge(s,[root,other],'联合方向','QA合并同级并保留下级')
        f.validate(s)
        self.assertEqual(set(f.member_ids(s,top)),set(ids[:10]))
        self.assertEqual(s['war_state'],before)

    def test_cycles_cross_team_missing_parent_and_ancestor_merge_reject(self):
        s,ids,root,child=self.tree();before=copy.deepcopy(s)
        for operation in (lambda:f.reparent(s,root,child,'循环'),
                          lambda:f.merge(s,[root,child],'非法合编','QA'),
                          lambda:f.detach(s,ids[10:11],'非法父级','QA',parent_id='missing')):
            with self.assertRaises(ValueError):operation()
        blue=next(i for i,(e,_) in commands.resolve_units(s).items() if e['team']=='blue')
        with self.assertRaises(ValueError):f.detach(s,[blue],'跨方','QA',parent_id=root)
        self.assertEqual(s,before)

    def test_historical_parent_orders_respect_temporary_command_assignment(self):
        s,ids,root,child=self.tree()
        node=next(n for n in f.view(s)['nodes'] if n['role']=='command' and set(ids[:2])<=set(n['execution_ids']))
        self.assertFalse(set(ids[:8])&set(node['effective_execution_ids']))
        queued=f.queue(s,node['id'],dict(action='hold',duration='next'))
        self.assertFalse(set(ids[:8])&{o['unit_id'] for o in queued['orders']})

    def test_continuation_preserves_empty_headquarters_and_descendant_chain(self):
        s,ids,root,child=self.tree()
        # Move the last direct members into the subordinate: the root is a valid HQ.
        s['force_organization']=f.detach(s,ids[4:8],'右翼群','QA',parent_id=root)
        target={**copy.deepcopy(s),'id':'new-hierarchy-qa','command_state':None}
        fields=f.continue_session(s,target);target.update(fields)
        self.assertEqual({f.leaf_key(e['team'],u) for i,(e,u) in commands.resolve_units(target).items()
            if i in f.member_ids(target,root)},set(next(g for g in f.view(s)['groups'] if g['id']==root)['members'])|
            {key for g in f.state(s)['groups'] if g['id']!=root for key in g['members']})
        self.assertNotEqual(set(f.member_ids(target,root)),set(ids[:8]))
        self.assertEqual(len(f.member_ids(target,root)),8)
        self.assertEqual(next(g for g in fields['force_organization']['groups'] if g['id']==root)['members'],[])
        f.validate(target)

    def test_native_member_paging_exposes_effective_chain(self):
        s,ids,root,child=self.tree();page=f.observation(s,dict(kind='members',node_id=root,limit=32))
        self.assertEqual(len(page['items']),8)
        first=next(r for r in page['items'] if r['command_id']==ids[0])
        self.assertEqual(first['command_chain'][:2],[root,child])
        self.assertEqual(first['command_chain'][-1],first['task_group_id'])

    def test_flat_legacy_is_readable_and_only_upgrades_on_organization_edit(self):
        s=session();ids=list(commands.resolve_units(s))[:1]
        legacy=f.detach(s,ids,'旧平面群','QA兼容')
        legacy['version']=f.VERSION
        for g in legacy['groups']:g.pop('parent_id')
        s['force_organization']=legacy;before=copy.deepcopy(s)
        f.validate(s);self.assertEqual(f.view(s)['version'],f.VERSION)
        self.assertEqual(s,before)
        upgraded=f.detach(s,ids,'新任务群','QA显式编辑')
        self.assertEqual(upgraded['version'],f.TREE_VERSION)
        self.assertEqual(s,before)

    def test_saved_cycle_or_empty_leaf_group_is_not_accepted(self):
        s,ids,root,child=self.tree()
        for kind in ('cycle','empty','duplicate','missing_parent'):
            bad=copy.deepcopy(s)
            groups=bad['force_organization']['groups']
            if kind=='cycle':next(g for g in groups if g['id']==root)['parent_id']=child
            if kind=='empty':groups[-1]['members']=[]
            if kind=='duplicate':groups[0]['members']+=groups[-1]['members']
            if kind=='missing_parent':groups[-1]['parent_id']='missing'
            with self.subTest(kind=kind),self.assertRaises(ValueError):f.validate(bad)


if __name__=='__main__':unittest.main()
