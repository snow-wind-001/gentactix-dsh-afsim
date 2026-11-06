"""Opening operational command is distinct from administrative identity and tasks."""
import copy
import unittest

from gentactix import commands,force_organization as f,historical_operations as ho,historical_initial as hi
from tools.qa.initial_command_fixture import inputs,session


def names(s,ids):
    return {e['name'] for i,(e,u) in commands.resolve_units(s).items() if i in ids}


class InitialCommandTests(unittest.TestCase):
    def test_source_overlay_controls_partial_attachment_without_rewriting_admin_tree(self):
        s=session();before=copy.deepcopy(s['war_state']);v=f.view(s);nodes={n['id']:n for n in v['nodes']}
        self.assertEqual(nodes['ww2.cn.division161.wjl_part']['parent_id'],'ww2.cn.division161')
        self.assertEqual(nodes['ww2.cn.division161.wjl_part']['command_parent_id'],'ww2.cn.army66')
        self.assertEqual(names(s,f.effective_member_ids(s,'ww2.cn.army66')),{'第159师','第161师万家岭投入部'})
        self.assertEqual(names(s,nodes['ww2.cn.army66']['execution_ids']),{'第159师'})
        self.assertEqual(len(f.effective_member_ids(s,'ww2.cn.corps1')),5)
        self.assertEqual(f.effective_member_ids(s,'ww2.cn.division161'),[])
        self.assertEqual(v['totals']['red']['current'],1500);self.assertEqual(s['war_state'],before)

    def test_group_queue_and_temporary_override_follow_current_authority(self):
        s=session();before=copy.deepcopy(s['war_state']);ids=f.effective_member_ids(s,'ww2.cn.army66')
        cs=f.queue(s,'ww2.cn.army66',{'action':'hold','duration':'next'})
        self.assertEqual({o['unit_id'] for o in cs['orders']},set(ids))
        part=next(i for i,(e,u) in commands.resolve_units(s).items() if e['name']=='第161师万家岭投入部')
        s['force_organization']=f.detach(s,[part],'北侧分遣','QA显式临时转用')
        self.assertEqual(names(s,f.effective_member_ids(s,'ww2.cn.army66')),{'第159师'})
        group=f.view(s)['groups'][0]['id'];key=next(k for k,r in f.leaves(s).items() if r[0]==part)
        self.assertEqual(f.command_chain(s,key),[group]);self.assertEqual(s['war_state'],before)

    def test_new_source_profile_requires_choice_but_old_frozen_calculation_stays_legacy(self):
        snap,p=inputs();self.assertIn('initial_command',ho.configuration_template(snap))
        p.pop('initial_command')
        with self.assertRaises(ValueError):ho.definition(snap,p)
        old=session(enabled=False);v=f.view(old)
        self.assertNotIn('command_baseline',v)
        self.assertEqual(names(old,f.effective_member_ids(old,'ww2.cn.army66')),{'第159师'})

    def test_combined_administrative_and_operational_cycle_is_rejected(self):
        from gentactix import initial_command
        snap,p=inputs();d=snap['definition'];phase=next(x for x in d['phases'] if x['id']==snap['phase_id'])
        next(r for r in phase['relations'] if r['child_id']=='ww2.cn.army66')['parent_id']='ww2.cn.division159'
        snap['definition_hash']=hi.digest(d)
        self.assertTrue(hi.validate_definition(d))
        with self.assertRaises(ValueError):initial_command.validate(snap,p)

    def test_native_members_and_task_receipts_expose_actual_opening_chain(self):
        from gentactix import force_tasks
        s=session();r=f.observation(s,{'kind':'members','node_id':'ww2.cn.army66','limit':1});rows=r['items']
        while r['next_args']:r=f.observation(s,r['next_args']);rows+=r['items']
        self.assertEqual({x['name'] for x in rows},{'第159师','第161师万家岭投入部'})
        self.assertTrue(all(x['command_chain']==['ww2.cn.warzone9','ww2.cn.corps1','ww2.cn.army66'] for x in rows))
        historical=f.observation(s,{'kind':'members','node_id':'ww2.cn.division161','hierarchy':'historical'})
        self.assertEqual(len(historical['items']),1)
        task={'kind':'uniform','order':{'action':'hold','duration':'next'}}
        p=force_tasks.preview(s,'ww2.cn.army66',task);cs=force_tasks.commit(s,'ww2.cn.army66',task,p['preview_hash'])
        self.assertTrue(all(o['task_context']['command_chain'][-1]=='ww2.cn.army66' for o in cs['orders']))

    def test_support_relation_does_not_grant_command_and_calendar_does_not_reassign(self):
        from gentactix import initial_command
        snap,p=inputs();phase=next(x for x in snap['definition']['phases'] if x['id']==snap['phase_id'])
        next(r for r in phase['relations'] if r['child_id']=='ww2.cn.division161.wjl_part')['kind']='support'
        snap['definition_hash']=hi.digest(snap['definition']);r=initial_command.validate(snap,p)
        self.assertEqual(r['parents']['ww2.cn.division161.wjl_part'],'ww2.cn.division161')
        s=session();before=f.effective_member_ids(s,'ww2.cn.army66');s['war_state']['current_time']='1938-10-09 00:00'
        self.assertEqual(f.effective_member_ids(s,'ww2.cn.army66'),before)

    def test_explicit_handoff_reports_command_changes_and_keeps_temporary_priority(self):
        source=session(enabled=False);ids=f.effective_member_ids(source,'ww2.cn.division161')
        source['force_organization']=f.detach(source,ids,'保留分遣群','QA持续人工任务优先')
        target=session();target['id']='target-qa';before=copy.deepcopy(source)
        fields=f.continue_session(source,target)
        change=fields['command_handoff']['initial_command'];self.assertTrue(change['changed'])
        self.assertTrue(any(r['name']=='第161师万家岭投入部' and r['after_name']=='第66军' for r in change['changes']))
        target.update(fields)
        self.assertEqual(names(target,f.effective_member_ids(target,'ww2.cn.army66')),{'第159师'})
        self.assertEqual(source,before)

    def test_historical_synthetic_baseline_keeps_command_and_new_exercise_units_separate(self):
        from gentactix import synthetic_history,missions
        s=session();binding=s['war_state']['mission']['definition']['historical_calculation']
        seed=synthetic_history.seed(binding);config=copy.deepcopy(seed['configuration'])
        clone=copy.deepcopy(config['teams']['red'][0]);clone['name']='新增演习分队';config['teams']['red'].append(clone)
        world=missions.from_definition(synthetic_history.definition(binding,config));s['war_state']=world;s['product_mode']='synthetic'
        self.assertIn('command_baseline',f.view(s))
        self.assertEqual(names(s,f.effective_member_ids(s,'ww2.cn.army66')),{'第159师','第161师万家岭投入部'})
        added=next((key,row) for key,row in f.leaves(s).items() if row[1]['name']=='新增演习分队')
        self.assertEqual(f.command_chain(s,added[0]),[])


if __name__=='__main__':unittest.main()
