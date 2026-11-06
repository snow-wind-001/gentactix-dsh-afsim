"""Mixed formation tasks are read-only proposals until explicit atomic commit."""
import copy
import unittest

from gentactix import commands,force_organization as f,missions
from gentactix import force_tasks as t
from tools.qa.large_formation_fixture import inputs
from gentactix import historical_operations as ho


def session():
    snap,p=inputs()
    red=[u['id'] for u in snap['definition']['units'] if u['team']=='red' and u['id'] in p['actors']]
    p['actors'][red[1]]['position']['lng']=114.29  # QA rear artillery deployment, not history.
    world=ho.initial(snap,p)
    s=dict(id='mixed-task-qa',turn_count=0,role_epoch=0,time_step='30分钟',product_mode='historical',
        simulation_mode='open',execution_backend='narrative',war_state=world)
    ids=[i for i,(e,_) in commands.resolve_units(s).items() if e['team']=='red'][:4]
    s['force_organization']=f.detach(s,ids,'合成方向群','QA互斥叶子')
    enemy=next(i for i,(e,_) in commands.resolve_units(s).items() if e['team']=='blue')
    return s,ids,s['force_organization']['groups'][0]['id'],enemy


class ForceTaskTests(unittest.TestCase):
    def intent(self,ids,enemy):
        return dict(kind='assault',destination={'lat':30.591,'lng':114.31},target_id=enemy,
            roles={ids[0]:'maneuver',ids[1]:'fire_support',ids[2]:'engineer',ids[3]:'reserve'})

    def test_preview_differentiates_roles_and_never_writes_world_or_queue(self):
        s,ids,g,enemy=session();saved=copy.deepcopy(s)
        result=t.preview(s,g,self.intent(ids,enemy))
        self.assertEqual(s,saved)
        rows={r['unit_id']:r for r in result['rows']}
        self.assertEqual(rows[ids[0]]['order']['action'],'fire')
        self.assertEqual(rows[ids[1]]['order']['action'],'bombard')
        self.assertEqual(rows[ids[2]]['order']['action'],'hold')
        self.assertEqual(rows[ids[3]]['order']['action'],'hold')
        self.assertTrue(all(r['reason'] for r in result['rows']))
        self.assertTrue(result['preview_hash'])

    def test_existing_manual_order_is_preserved_unless_override_is_explicit(self):
        s,ids,g,enemy=session()
        s['command_state']=commands.replace_queue(s,[dict(unit_id=ids[0],action='recon',duration='next')],
            control_team='red',director=False,no_fire=False,intent='人工侦察优先')
        task=self.intent(ids,enemy);p=t.preview(s,g,task)
        cs=t.commit(s,g,task,p['preview_hash'])
        self.assertEqual(next(o for o in cs['orders'] if o['unit_id']==ids[0])['action'],'recon')
        p=t.preview(s,g,task,replace_existing=True)
        overridden=t.commit(s,g,task,p['preview_hash'],replace_existing=True)
        self.assertEqual(next(o for o in overridden['orders'] if o['unit_id']==ids[0])['action'],'fire')
        self.assertEqual(len(overridden['orders']),4)

    def test_stale_preview_invalid_target_and_illegal_role_reject(self):
        s,ids,g,enemy=session();task=self.intent(ids,enemy);p=t.preview(s,g,task)
        s['war_state']['red_units'][0]['formation']['fatigue']+=1
        with self.assertRaises(commands.Conflict):t.commit(s,g,task,p['preview_hash'])
        task['roles'][ids[0]]='invented'
        with self.assertRaises(ValueError):t.preview(s,g,task)
        task=self.intent(ids,enemy);task['target_id']=ids[0]
        with self.assertRaises(ValueError):t.preview(s,g,task)

    def test_no_fire_resource_shortage_and_waiting_are_not_silent_firing(self):
        s,ids,g,enemy=session();task=self.intent(ids,enemy)
        s['command_state']=commands.replace_queue(s,[],control_team='red',director=False,no_fire=True,intent='停火')
        p=t.preview(s,g,task)
        self.assertTrue(all(r['order']['action'] not in ('fire','bombard','suppress') for r in p['rows'] if r['order']))
        s['command_state']['no_fire']=False
        s['war_state']['red_units'][1]['formation']['shells']=0
        row=next(r for r in t.preview(s,g,task)['rows'] if r['unit_id']==ids[1])
        self.assertEqual(row['order']['action'],'hold');self.assertEqual(row['status'],'waiting')

    def test_task_provenance_reaches_unit_receipt_and_queue_restores(self):
        s,ids,g,enemy=session();task=dict(kind='advance',destination={'lat':30.61,'lng':114.31})
        p=t.preview(s,g,task);s['command_state']=t.commit(s,g,task,p['preview_hash'])
        commands.validate_saved(s)
        prepared=commands.prepare(s)
        executed=[r['order'] for r in prepared['manual']]
        after=copy.deepcopy(s['war_state'])
        cs,decisions=commands.finish(s,prepared,after,executed=executed)
        own=[r for r in cs['receipts'] if r['unit_id'] in ids]
        self.assertEqual(len(own),4)
        self.assertTrue(all(r['task_context']['group_id']==g for r in own))
        self.assertEqual(len({r['task_context']['task_id'] for r in own}),1)
        task_id=own[0]['task_context']['task_id']
        self.assertEqual(cs['task_plans'][task_id]['task'],task)
        target={**copy.deepcopy(s),'id':'continued-task-qa','command_state':None}
        carried=f.continue_session(s,target)
        self.assertEqual(carried['command_state']['task_plans'],s['command_state']['task_plans'])

    def test_native_preview_pages_and_stale_hash_are_read_only(self):
        from backend import agent_tools,harness_engine
        s,ids,g,enemy=session();before=copy.deepcopy(s)
        args={'group_id':g,'task':self.intent(ids,enemy),'limit':2};rows=[]
        while args:
            r=agent_tools.execute_tool_call(s,s['war_state'],{'tool':'preview_force_task','args':args})
            self.assertTrue(r['ok'],r);self.assertLessEqual(len(r['rows']),2)
            rows+=r['rows'];args=r['next_args']
        self.assertEqual({r['unit_id'] for r in rows},set(ids));self.assertEqual(s,before)
        self.assertIn('preview_force_task',harness_engine.role_policy('engine',tools=True,external=True)['allowed_tools'])

    def test_unavailable_member_old_order_expires_without_blocking_other_members(self):
        s,ids,g,enemy=session()
        s['command_state']=commands.replace_queue(s,[dict(unit_id=ids[0],action='recon',duration='next')],
            control_team='red',director=False,no_fire=False,intent='QA')
        unit=s['war_state']['red_units'][0];unit['personnel'].update(current=0,casualties=unit['personnel']['committed'])
        task={'kind':'defend'};p=t.preview(s,g,task);result=t.commit(s,g,task,p['preview_hash'])
        self.assertNotIn(ids[0],{o['unit_id'] for o in result['orders']})
        self.assertEqual(len(result['orders']),3)
        self.assertEqual(result['archive'][-1]['status'],'expired')


if __name__=='__main__':unittest.main()
