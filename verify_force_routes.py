"""Task organization HTTP permissions, stale revisions and atomic persistence."""
import copy
import unittest
from unittest.mock import patch
import verify_mission_backend as fixtures
from backend import main,session_store
from gentactix import commands


class ForceAPITests(unittest.TestCase):
    def setUp(self):
        fixtures.MissionAPITests.setUp(self)
        fixtures.MissionAPITests.start(self)
        self.path=f'/api/sessions/{self.sid}/force-organization'

    def tearDown(self):
        main._SESSIONS.clear()
        fixtures.MissionAPITests.tearDown(self)

    def data(self):
        r=self.client.get(self.path);self.assertEqual(r.status_code,200,r.text);return r.json()

    def revision(self):
        v=self.data();return dict(expected_turn=v['turn'],revision=v['command_revision'],
            world_version=v['world_version'],organization_revision=v['revision'])

    def detach(self,ids,revision=None):
        return self.client.post(self.path+'/detach',json={**(revision or self.revision()),
            'unit_ids':ids,'label':'测试任务群','assumption':'临时配属，不改变原历史建制与物理位置'})

    def test_permission_staleness_and_storage_failure(self):
        s=main._SESSIONS[self.sid];before=copy.deepcopy(s['war_state'])
        units=commands.view(s)['units'];red=next(u['id'] for u in units if u['team']=='red')
        blue=next(u['id'] for u in units if u['team']=='blue')
        self.assertEqual(self.detach([blue]).status_code,422)
        stale=self.revision()
        with patch.object(session_store,'save',side_effect=OSError('full')):
            self.assertEqual(self.detach([red]).status_code,503)
        self.assertNotIn('force_organization',s)
        self.assertEqual(self.detach([red]).status_code,200)
        self.assertEqual(self.detach([red],stale).status_code,409)
        self.assertEqual(s['war_state'],before)
        restored,errors=session_store.load_all();self.assertFalse(errors)
        self.assertEqual(restored[self.sid]['force_organization'],s['force_organization'])

    def test_group_order_and_fork_identity(self):
        s=main._SESSIONS[self.sid];red=next(u['id'] for u in commands.view(s)['units'] if u['team']=='red')
        self.assertEqual(self.detach([red]).status_code,200)
        group=self.data()['groups'][0]['id']
        r=self.client.post(self.path+'/orders',json={**self.revision(),'group_id':group,
            'order':{'action':'hold','duration':'next'}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([o['unit_id'] for o in commands.state(s)['orders']],[red])
        from gentactix import force_organization as f
        branch=copy.deepcopy(s);branch.update(id='f'*12,role_epoch=1,command_state=None)
        f.validate(branch)
        self.assertNotEqual(f.member_ids(branch,group),[red])
        self.assertEqual(f.view(branch)['totals'],self.data()['totals'])

    def test_nested_wrap_reparent_cycle_and_atomic_storage(self):
        s=main._SESSIONS[self.sid];before=copy.deepcopy(s['war_state'])
        units=commands.resolve_units(s)
        team=max(('red','blue'),key=lambda t:sum(e['team']==t for e,u in units.values()))
        ids=[i for i,(e,u) in units.items() if e['team']==team]
        self.assertGreaterEqual(len(ids),2)
        s['command_state']=commands.replace_queue(s,[],control_team=team,director=False,no_fire=False,intent='QA')
        self.assertEqual(self.detach(ids[:1]).status_code,200)
        first=self.data()['groups'][0]['id']
        self.assertEqual(self.detach(ids[1:2]).status_code,200)
        second=next(g['id'] for g in self.data()['groups'] if g['id']!=first)
        body={**self.revision(),'group_ids':[first,second],'label':'上级指挥群','assumption':'QA保留两个下级群'}
        with patch.object(session_store,'save',side_effect=OSError('full')):
            self.assertEqual(self.client.post(self.path+'/wrap',json=body).status_code,503)
        self.assertEqual(len(self.data()['groups']),2)
        wrapped=self.client.post(self.path+'/wrap',json=body)
        self.assertEqual(wrapped.status_code,200,wrapped.text)
        top=next(g['id'] for g in wrapped.json()['groups'] if g['depth']==0)
        self.assertEqual(self.client.post(self.path+'/wrap',json=body).status_code,409)
        bad=self.client.post(self.path+'/reparent',json={**self.revision(),'group_id':top,
            'parent_id':first,'assumption':'不允许循环'})
        self.assertEqual(bad.status_code,422,bad.text)
        good=self.client.post(self.path+'/reparent',json={**self.revision(),'group_id':first,
            'parent_id':None,'assumption':'QA整群退出上级指挥'})
        self.assertEqual(good.status_code,200,good.text)
        self.assertEqual(s['war_state'],before)
        restored,errors=session_store.load_all();self.assertFalse(errors)
        session_store.validate(restored[self.sid])

    def test_task_preview_confirm_stale_and_write_failure(self):
        s=main._SESSIONS[self.sid];red=next(u['id'] for u in commands.view(s)['units'] if u['team']=='red')
        self.assertEqual(self.detach([red]).status_code,200)
        group=self.data()['groups'][0]['id'];before=copy.deepcopy(s)
        body={**self.revision(),'group_id':group,'task':{'kind':'defend'}}
        p=self.client.post(self.path+'/task-preview',json=body)
        self.assertEqual(p.status_code,200,p.text);self.assertEqual(s,before)
        self.assertEqual(self.client.post(self.path+'/tasks',json=body).status_code,422)
        request={**body,'preview_hash':p.json()['preview_hash']}
        with patch.object(session_store,'save',side_effect=OSError('full')):
            self.assertEqual(self.client.post(self.path+'/tasks',json=request).status_code,503)
        self.assertEqual(s,before)
        r=self.client.post(self.path+'/tasks',json=request)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.post(self.path+'/tasks',json=request).status_code,409)
        order=commands.state(s)['orders'][0]
        self.assertEqual(order['task_context']['kind'],'defend')
        old=self.client.post(self.path+'/orders',json={**self.revision(),'group_id':group,'order':{'action':'hold','duration':'next'}})
        self.assertEqual(old.status_code,409,old.text)

    def test_persistent_task_confirmation_cancel_and_cold_restore_are_atomic(self):
        from verify_force_task_execution import execution
        s=main._SESSIONS[self.sid];red=next(u['id'] for u in commands.view(s)['units'] if u['team']=='red')
        self.assertEqual(self.detach([red]).status_code,200)
        group=self.data()['groups'][0]['id'];before=copy.deepcopy(s)
        body={**self.revision(),'group_id':group,'task':{'kind':'defend'},
            'execution':execution('持续防御',finish=dict(kind='turn',end_turn=3,minimum_executions=1))}
        p=self.client.post(self.path+'/task-preview',json=body);self.assertEqual(p.status_code,200,p.text)
        body['preview_hash']=p.json()['preview_hash']
        with patch.object(session_store,'save',side_effect=OSError('full')):
            self.assertEqual(self.client.post(self.path+'/tasks',json=body).status_code,503)
        self.assertEqual(s,before)
        self.assertEqual(self.client.post(self.path+'/tasks',json=body).status_code,200)
        page=self.client.get(self.path+'/tasks?limit=1');self.assertEqual(page.status_code,200,page.text)
        task=page.json()['rows'][0];self.assertEqual(task['status'],'queued')
        loaded,errors=session_store.load_all();self.assertFalse(errors);commands.validate_saved(loaded[self.sid])
        cancel={**self.revision(),'task_id':task['id']};prior=copy.deepcopy(s)
        with patch.object(session_store,'save',side_effect=OSError('full')):
            self.assertEqual(self.client.post(self.path+'/cancel-task',json=cancel).status_code,503)
        self.assertEqual(s,prior)
        self.assertEqual(self.client.post(self.path+'/cancel-task',json=cancel).status_code,200)
        self.assertEqual(self.client.post(self.path+'/cancel-task',json=cancel).status_code,409)
        self.assertEqual(self.client.get(self.path+'/tasks').json()['rows'][0]['status'],'cancelled')
        self.assertEqual(s['war_state'],before['war_state'])


if __name__=='__main__':unittest.main()
