"""Detached command/organization/task handoffs; no platform or live commit."""
import copy
import json
import unittest
from unittest.mock import patch

from gentactix import commands, force_organization as forces, force_tasks, force_task_execution as tasks
from gentactix import formation_session as handoff, formation_conversion as fc, missions
from verify_formation_continuity import world, selected, proposal
from verify_force_task_execution import execution


def setup(initial_world=None):
    w=initial_world if initial_world is not None else world();s=dict(id='a'*12,war_state=w,turn_count=0,time_step=w['mission']['definition']['time_step'],
        product_mode='synthetic',simulation_mode='open',execution_backend='narrative',role_epoch=2,
        history=[],decision_log=[],trajectory=[])
    s['command_state']=commands.replace_queue(s,[],control_team='red',director=True,no_fire=False,intent='QA全局意图')
    uid=next(i for i,(_,u) in commands.resolve_units(s).items() if u['name']==selected(w)['name'])
    s['force_organization']=forces.detach(s,[uid],'原任务群','QA显式配属')
    return s,uid,s['force_organization']['groups'][0]['id']


def prepare(s,p=None):return handoff.prepare(s,p or proposal(s['war_state']),team='red')


def register(s,group,config=None,task=None):
    task=task or dict(kind='defend')
    config=config or execution('原任务',finish=dict(kind='turn',end_turn=5,minimum_executions=2))
    v=force_tasks.preview(s,group,task,execution=config)
    s['command_state']=force_tasks.commit(s,group,task,v['preview_hash'],execution=config)
    return next(reversed(s['command_state']['task_plans']))


class SessionHandoffTests(unittest.TestCase):
    def test_human_order_and_original_receipts_survive_under_explicit_new_ids(self):
        s,uid,_=setup();u=selected(s['war_state']);point=dict(lat=u['lat']+.001,lng=u['lng'])
        s['command_state']=commands.replace_queue(s,[dict(unit_id=uid,action='move',duration='until_arrived',destination=point)],
            control_team='red',director=True,no_fire=False,intent='人工先行')
        saved=copy.deepcopy(s);v=prepare(s);after=v['session'];ids=v['command_map'][uid]
        self.assertEqual(len(ids),2);self.assertTrue(handoff.validate(after));self.assertEqual(s,saved)
        cs=after['command_state'];self.assertEqual({o['unit_id'] for o in cs['orders']},set(ids))
        self.assertTrue(all(o['destination']==point and o['created_turn']==0 for o in cs['orders']))
        self.assertEqual(len({o['id'] for o in cs['orders']}),2)
        self.assertEqual(cs['receipts'],s['command_state']['receipts']);self.assertEqual(after['history'],s['history'])
        self.assertTrue(next(r for r in cs['registry'] if r['id']==uid)['retired'])
        self.assertFalse(v['runtime_admitted'])

    def test_unit_agent_assignment_moves_but_native_sessions_and_old_decisions_are_not_cloned(self):
        s,uid,_=setup();cs=s['command_state'];cs['unit_agents']=[uid]
        cs['agent_sessions']={uid:dict(session_id=f'gentactix-unit-{s["id"]}-e2-{uid}-qa')}
        s['decision_log']=[dict(unit_id=uid,action='原决策')];saved=copy.deepcopy(s)
        v=prepare(s);after=v['session'];self.assertEqual(set(after['command_state']['unit_agents']),set(v['command_map'][uid]))
        self.assertEqual(after['command_state']['agent_sessions'],cs['agent_sessions'])
        self.assertTrue(all(i not in after['command_state']['agent_sessions'] for i in v['command_map'][uid]))
        self.assertEqual(after['decision_log'],s['decision_log']);self.assertEqual(s,saved)

    def test_task_group_uses_all_new_leaves_once_and_unselected_ids_remain_stable(self):
        s,uid,group=setup();before=set(commands.resolve_units(s));v=prepare(s);after=v['session']
        self.assertEqual(set(forces.effective_member_ids(after,group)),set(v['command_map'][uid]))
        self.assertEqual(set(commands.resolve_units(after))-set(v['command_map'][uid]),before-{uid})
        a=forces.view(after)['totals'];b=forces.view(s)['totals']
        for team in ('red','blue'):
            self.assertEqual({k:v for k,v in a[team].items() if k!='units'},{k:v for k,v in b[team].items() if k!='units'})
        self.assertEqual(a['red']['units'],b['red']['units']+1)

    def test_task_frozen_definition_is_unchanged_while_effective_members_follow_conversion(self):
        s,uid,group=setup();tid=register(s,group);old=copy.deepcopy(s['command_state']['task_plans'][tid])
        v=prepare(s);after=v['session'];record=after['command_state']['task_plans'][tid]
        self.assertEqual(record['task'],old['task']);self.assertEqual(record['execution']['definition_hash'],old['execution']['definition_hash'])
        self.assertEqual(record['execution']['definition'],old['execution']['definition'])
        self.assertEqual(set(record['execution']['members']),set(v['command_map'][uid]))
        self.assertTrue(tasks.validate(after));self.assertTrue(handoff.validate(after))

    def test_command_probe_reuses_normal_queue_and_does_not_run_physics_or_score(self):
        s,uid,group=setup();tid=register(s,group);v=prepare(s);after=v['session'];saved=copy.deepcopy(after)
        with patch.object(missions,'advance',side_effect=AssertionError('No physics')):
            probe=handoff.command_probe(after)
        self.assertEqual({r['command']['unit_id'] for r in probe['manual']},set(v['command_map'][uid]))
        self.assertEqual(after,saved);self.assertEqual(after['command_state']['task_plans'][tid]['execution']['status'],'queued')
        with self.assertRaises(ValueError):missions.validate(after['war_state'])

    def test_inherited_task_counts_are_not_summed_as_extra_rounds(self):
        s,uid,group=setup();tid=register(s,group);runtime=s['command_state']['task_plans'][tid]['execution']
        runtime['member_states'][uid]['executions']=3;tasks._stamp(runtime)
        v=prepare(s);after=v['session'];r=after['command_state']['task_plans'][tid]['execution']
        self.assertEqual([row['executions'] for row in r['member_states'].values()],[3,3])
        view=tasks.observation(after,dict(kind='members',task_id=tid))
        self.assertTrue(all(row['conversion_origin']['counts_must_not_be_summed'] for row in view['rows']))
        self.assertEqual(r['status'],runtime['status']);self.assertEqual(r['events'],runtime['events'])

    def test_terminal_task_and_original_decision_history_remain_exact(self):
        s,_,group=setup();tid=register(s,group);r=s['command_state']['task_plans'][tid]['execution']
        r['status']='completed';tasks._stamp(r);old=copy.deepcopy(s['command_state']['task_plans'][tid])
        after=prepare(s)['session'];self.assertEqual(after['command_state']['task_plans'][tid],old)

    def test_nested_split_and_merge_keep_original_task_hash_and_cold_restore(self):
        s,uid,group=setup();tid=register(s,group);first=prepare(s)['session'];w=first['war_state']
        children=[u for u in w['red_units'] if u.get('runtime_allocation')]
        p=fc.merge_current(children,assumption='QA同地合并',operation_id='b'*32)
        v=prepare(first,p);after=v['session'];record=after['command_state']['task_plans'][tid]
        self.assertEqual(record['execution']['definition_hash'],s['command_state']['task_plans'][tid]['execution']['definition_hash'])
        self.assertEqual(len(record['execution']['members']),1);self.assertTrue(handoff.validate(json.loads(json.dumps(after))))

    def test_conflicting_human_orders_reject_merge_without_mutation(self):
        s,uid,_=setup();v=prepare(s);after=v['session'];a,b=v['command_map'][uid]
        with handoff.command_validation(after):
            after['command_state']=commands.replace_queue(after,[dict(unit_id=a,action='hold',duration='next'),dict(unit_id=b,action='recon',duration='next')],
                control_team='red',director=True,no_fire=False,intent='QA不同人工决策')
        # This is a later command revision at the same physical tick.
        children=[u for u in after['war_state']['red_units'] if u.get('runtime_allocation')]
        p=fc.merge_current(children,assumption='QA冲突合并',operation_id='c'*32);saved=copy.deepcopy(after)
        with self.assertRaisesRegex(ValueError,'冲突|不同'):prepare(after,p)
        self.assertEqual(after,saved)

    def test_target_split_requires_explicit_choice_instead_of_retargeting_arbitrarily(self):
        s,uid,_=setup();enemy=next(i for i,(r,_) in commands.resolve_units(s).items() if r['team']=='blue')
        # Build a saved, blocked intent so legality of the original range does
        # not mask ambiguity in one-target-to-many-target conversion.
        s['command_state']['orders']=[dict(id='b'*32,unit_id=enemy,action='fire',target_id=uid,status='blocked',
            duration='next',source='human',created_turn=0,reason='QA目标选择',rule_version=commands.rule_version(s))]
        saved=copy.deepcopy(s)
        with self.assertRaisesRegex(ValueError,'目标|选择'):prepare(s)
        self.assertEqual(s,saved)

    def test_repeated_readonly_preparation_is_exact_and_cannot_hide_a_forged_command_map(self):
        s,_,_=setup();a=prepare(s);b=prepare(s);self.assertEqual(a,b)
        after=copy.deepcopy(a['session']);event=after['command_state']['formation_handoffs'][-1]
        event['command_map']={'bad':['bad']}
        with self.assertRaises(ValueError):handoff.validate(after)

    def test_later_command_edit_does_not_disable_validation_of_old_identity_maps(self):
        s,_,_=setup();v=prepare(s);after=v['session']
        after['command_state']['revision']+=1
        event=after['command_state']['formation_handoffs'][-1];event['command_map']={'bad':['bad']}
        with self.assertRaises(ValueError):handoff.validate(after)

    def test_merge_cannot_silently_choose_between_distinct_task_roles(self):
        s,uid,group=setup();v=prepare(s);after=v['session'];a,b=v['command_map'][uid]
        with handoff.command_validation(after):
            register(after,group,task=dict(kind='defend',roles={a:'reserve',b:'maneuver'}))
        units=[u for u in after['war_state']['red_units'] if u.get('runtime_allocation')]
        p=fc.merge_current(units,assumption='QA角色冲突',operation_id='d'*32);saved=copy.deepcopy(after)
        with self.assertRaisesRegex(ValueError,'分工|冲突'):prepare(after,p)
        self.assertEqual(after,saved)

    def test_a_partial_task_member_cannot_absorb_a_different_units_task(self):
        s,uid,group=setup();v=prepare(s);after=v['session'];a,b=v['command_map'][uid]
        # Explicitly issue the task to one child, then put both under the same
        # direct group. Its frozen membership must not silently expand on merge.
        after['force_organization']=forces.detach(after,[a],'子任务群','QA单一承担者')
        child=after['force_organization']['groups'][-1]['id']
        with missions._prepared_validation(after['war_state']):register(after,child)
        after['force_organization']=forces.detach(after,[a,b],'同地待合群','QA不改变原任务范围')
        units=[u for u in after['war_state']['red_units'] if u.get('runtime_allocation')]
        p=fc.merge_current(units,assumption='QA任务范围冲突',operation_id='f'*32)
        with self.assertRaisesRegex(ValueError,'承担者|任务|命令'):prepare(after,p)

    def test_physical_world_or_public_runtime_is_not_accepted_after_a_command_probe(self):
        s,_,group=setup();register(s,group);after=prepare(s)['session']
        handoff.command_probe(after)
        with self.assertRaises(ValueError):missions.validate(after['war_state'])
        other=copy.deepcopy(after['war_state'])
        with handoff.command_validation(after):
            with self.assertRaises(ValueError):missions.validate(other)

    def test_historical_parent_totals_include_the_explicit_unknown_residual(self):
        from tools.qa.formation_ownership_fixture import historical_parent_world
        w=historical_parent_world();s=dict(id='b'*12,war_state=w,turn_count=0,role_epoch=0,product_mode='historical',
            simulation_mode='open',execution_backend='narrative',time_step=w['mission']['definition']['time_step'])
        s['command_state']=commands.replace_queue(s,[],control_team='red',director=True,no_fire=False,intent='QA')
        parent=next(u for u in w['red_units'] if u['historical_unit_id']=='ww2.cn.army74')
        p=fc.split_current(parent,[dict(id='a',historical_unit_id='ww2.cn.division51',committed=4000),
            dict(id='b',historical_unit_id='ww2.cn.division58',committed=4000),dict(id='rest',historical_unit_id=None,committed=2000)],
            assumption='QA估计分配，未知余部',operation_id='e'*32,product_mode='historical',historical_snapshot=w['historical_initial'])
        after=prepare(s,p)['session'];view=forces.view(after)
        node=next(n for n in view['nodes'] if n['id']=='ww2.cn.army74')
        self.assertEqual(node['totals']['committed'],10000);self.assertEqual(node['totals']['units'],3)
        rest=next(u for u in after['war_state']['red_units'] if u.get('runtime_allocation') and u['name'].endswith('未分配余部（估计）'))
        self.assertIn('ww2.cn.army74',forces.effective_command_chains(after)[forces.leaf_key('red',rest)])

    def test_task_round_settlement_counts_each_current_actor_once_without_summing_ancestors(self):
        s,uid,group=setup();tid=register(s,group);r=s['command_state']['task_plans'][tid]['execution']
        r['member_states'][uid]['executions']=3;tasks._stamp(r)
        after=prepare(s)['session'];probe=handoff.command_probe(after);receipts=[]
        for n,row in enumerate(probe['manual']):
            o=row['command'];receipts.append(dict(id=str(n),unit_id=o['unit_id'],task_context=o['task_context'],status='completed',action='hold'))
        cs=tasks.finish(after,probe['state'],after['war_state'],receipts)
        runtime=cs['task_plans'][tid]['execution']
        self.assertEqual([r['executions'] for r in runtime['member_states'].values()],[4,4]);self.assertNotEqual(runtime['status'],'completed')

    def test_duplicate_actor_receipts_cannot_count_as_two_task_rounds(self):
        s,_,group=setup();register(s,group);after=prepare(s)['session'];probe=handoff.command_probe(after)
        o=probe['manual'][0]['command'];r=dict(id='same',unit_id=o['unit_id'],task_context=o['task_context'],status='completed',action='hold')
        saved=copy.deepcopy(probe['state'])
        with self.assertRaisesRegex(ValueError,'重复|一次'):tasks.finish(after,probe['state'],after['war_state'],[r,r])
        self.assertEqual(probe['state'],saved)

    def test_detached_session_uses_the_existing_checkpoint_filter_for_live_observers(self):
        import threading
        s,_,_=setup();lock=threading.Lock();s.update(active_observer=lock,adj_spec=lock,progress=dict(status='working'))
        after=prepare(s)['session']
        self.assertNotIn('active_observer',after);self.assertNotIn('adj_spec',after);self.assertNotIn('progress',after)
        self.assertIs(s['active_observer'],lock);self.assertEqual(s['progress'],dict(status='working'))

    def test_internal_command_scope_validates_once_without_admitting_a_public_world(self):
        from gentactix import formation_continuity
        s,_,_=setup();after=prepare(s)['session'];w=after['war_state']
        with patch.object(formation_continuity,'validate',wraps=formation_continuity.validate) as check:
            with missions._prepared_validation(w):
                for _ in range(3):self.assertTrue(missions.validate(w))
            self.assertEqual(check.call_count,1)
        with self.assertRaises(ValueError):missions.validate(w)
        with self.assertRaisesRegex(ValueError,'不得改变'):
            with missions._prepared_validation(w):w['red_units'][0]['personnel']['current']-=1

    def test_handoff_clock_and_revisions_do_not_accept_boolean_integer_aliases(self):
        s,_,_=setup();after=prepare(s)['session']
        for key in ('registry_revision','turn'):
            changed=copy.deepcopy(after);event=changed['command_state']['formation_handoffs'][-1]
            event[key]=bool(event[key])
            with self.subTest(key=key),self.assertRaises(ValueError):handoff.validate(changed)


if __name__=='__main__':unittest.main(verbosity=2)
