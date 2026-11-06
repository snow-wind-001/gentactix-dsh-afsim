"""Open branches retain semantic actors/tasks, never live SDK bindings.

Offline transaction tests; the fixture's strengths and equipment are estimates.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main, session_store
from gentactix import commands, formation_conversion, formation_session, force_organization
from verify_formation_commit import fixture
from verify_formation_session import register


def request(s, ids, kind='merge', commit_id='e'*32):
    view=commands.view(s)
    args=dict(kind=kind,unit_ids=ids,assumption='分支软件验证，非历史改编命令')
    preview=formation_conversion.observation(s,args)
    return dict(**args,expected_turn=s['turn_count'],revision=view['revision'],world_version=view['world_version'],
        organization_revision=force_organization.state(s)['revision'],view_version=preview['view_version'],commit_id=commit_id)


class BranchIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend import formation_commit
        cls.source,cls.parent,group=fixture();cls.task=register(cls.source,group)
        s=cls.source
        other=next(i for i,(r,_) in commands.resolve_units(s).items() if i!=cls.parent and r['team']=='red')
        s['command_state']=commands.replace_queue(s,[dict(unit_id=other,action='hold',duration='until_turn',end_turn=5)],
            control_team='red',director=True,no_fire=True,intent='分支测试：保留人工准备、任务和损耗')
        s['command_state']['unit_agents']=[cls.parent]
        s['command_state']['agent_sessions']={cls.parent:dict(session_id=f'gentactix-unit-{s["id"]}-e2-{cls.parent}-original')}
        cls.old_agent=copy.deepcopy(s['command_state']['agent_sessions'])
        args=dict(kind='split',unit_ids=[cls.parent],allocations=[dict(id='a',label='分支左',committed=5000),
            dict(id='b',label='分支右',committed=5000)],assumption='软件QA估计，非历史编组')
        v=commands.view(s);preview=formation_conversion.observation(s,args)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':folder}):
            result=formation_commit.commit(s,dict(**args,expected_turn=0,revision=v['revision'],world_version=v['world_version'],
                organization_revision=force_organization.state(s)['revision'],view_version=preview['view_version'],commit_id='f'*32))
        cls.children=result['command_map'][cls.parent]
        s['decision_log']=[dict(turn=0,summary='分支前公开决策摘要')]
        session_store.validate(s)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':self.temp.name+'/sessions',
            'GENTACTIX_TRACE_DIR':self.temp.name+'/traces','GENTACTIX_ROLE_INDEX':self.temp.name+'/roles.json'})
        self.env.start();self.s=copy.deepcopy(self.source);self.sid=self.s['id'];session_store.save(self.s)
        self.sessions=patch.dict(main._SESSIONS,{self.sid:self.s},clear=True);self.sessions.start()
        self.client=TestClient(main.app);self.base='/api/sessions/'+self.sid
        self.original=session_store.serializable(self.s)
        self.path=Path(self.temp.name)/'sessions'/(self.sid+'.json');self.blob=self.path.read_bytes()

    def tearDown(self):self.sessions.stop();self.env.stop();self.temp.cleanup()

    def revision(self,s=None):
        s=s or self.s;v=commands.view(s)
        return dict(expected_turn=s['turn_count'],revision=v['revision'],world_version=v['world_version'])

    def branch(self,s=None):
        s=s or self.s
        response=self.client.post('/api/sessions/'+s['id']+'/commands/open-branch',json=self.revision(s))
        self.assertEqual(response.status_code,200,response.text)
        return main._SESSIONS[response.json()['session_id']]

    def unchanged(self):
        self.assertEqual(session_store.serializable(self.s),self.original);self.assertEqual(self.path.read_bytes(),self.blob)

    def test_formal_branch_preserves_world_handoffs_task_queue_and_decision_history(self):
        with patch.object(main.harness_engine,'dispose_unit_sessions',side_effect=AssertionError('Original SDK still in use')):
            b=self.branch()
        self.assertNotEqual(b['id'],self.sid);self.assertEqual(b['role_epoch'],self.s['role_epoch']+1)
        self.assertEqual(b['war_state'],self.s['war_state'])
        for key in ('formation_commits','history','trajectory','decision_log','force_organization'):
            self.assertEqual(b[key],self.s[key],key)
        for key in ('registry','formation_handoffs','task_plans','orders','receipts'):
            self.assertEqual(b['command_state'][key],self.s['command_state'][key],key)
        self.assertEqual(b['command_state']['agent_sessions'],{})
        self.assertEqual(b['command_state']['unit_agents'],self.children)
        self.assertEqual(b['command_state']['revision'],self.s['command_state']['revision']+1)
        self.assertNotEqual(commands.world_version(b),commands.world_version(self.s))
        self.assertEqual(set(commands.resolve_units(b)),set(commands.resolve_units(self.s)))
        self.assertTrue(formation_session.validate(b));session_store.validate(b);self.unchanged()
        rows,_=session_store.load_all();self.assertEqual(session_store.serializable(rows[b['id']]),session_store.serializable(b))

    def test_branch_owns_one_save_and_failure_never_publishes_or_changes_source(self):
        real=session_store.save
        with patch.object(session_store,'save',wraps=real) as save:b=self.branch()
        self.assertEqual(save.call_count,1);self.assertEqual(save.call_args.args[0]['id'],b['id']);self.unchanged()
        for target in ('fsync','replace'):
            before=set(main._SESSIONS);files=set(Path(self.temp.name+'/sessions').glob('*'))
            with patch.object(session_store.os,target,side_effect=OSError('disk failed')):
                result=self.client.post(self.base+'/commands/open-branch',json=self.revision())
            self.assertEqual(result.status_code,503,result.text)
            self.assertEqual(set(main._SESSIONS),before);self.assertEqual(set(Path(self.temp.name+'/sessions').glob('*')),files)
            self.unchanged()

    def test_stale_branch_inputs_and_operation_lock_reject_before_creating_session(self):
        for key,value in [('revision',900),('expected_turn',900),('world_version','stale')]:
            response=self.client.post(self.base+'/commands/open-branch',json={**self.revision(),key:value})
            self.assertEqual(response.status_code,409,response.text)
        main._OP_LOCK.acquire()
        try:self.assertEqual(self.client.post(self.base+'/commands/open-branch',json=self.revision()).status_code,409)
        finally:main._OP_LOCK.release()
        self.assertEqual(set(main._SESSIONS),{self.sid});self.unchanged()

    def test_nested_branch_can_merge_and_cold_restore_original_semantic_namespace(self):
        from backend import formation_commit
        first=self.branch();second=self.branch(first)
        self.assertEqual(first['command_identity_origin'],second['command_identity_origin'])
        self.assertEqual(first['command_identity_origin']['session_id'],self.sid)
        self.assertEqual(second['command_state']['formation_handoffs'],self.s['command_state']['formation_handoffs'])
        formation_commit.commit(second,request(second,self.children))
        self.assertEqual(len(second['formation_commits']),2)
        self.assertTrue(formation_session.validate(second));session_store.validate(second)
        rows,errors=session_store.load_all();self.assertFalse(errors)
        self.assertEqual(session_store.serializable(rows[second['id']]),session_store.serializable(second));self.unchanged()

    def test_namespace_metadata_and_registry_cannot_be_changed_independently(self):
        b=self.branch()
        for kind in ('missing','scope','binding','revision','registry'):
            bad=copy.deepcopy(b)
            if kind=='missing':bad.pop('command_identity_origin')
            elif kind=='scope':bad['command_identity_origin']['session_id']='b'*12
            elif kind=='binding':bad['branch_origin']['command_identity_origin']['role_epoch']=99
            elif kind=='revision':bad['branch_origin']['source_command_revision']=bad['command_state']['revision']
            else:bad['command_state']['registry'][0]['id']='b'*32
            with self.subTest(kind=kind),self.assertRaises(ValueError):session_store.validate(bad)
        self.unchanged()

    def test_shared_native_context_preserves_namespace_and_inherited_task_validation(self):
        from backend import afsim_state
        b=self.branch();current=afsim_state.operation_context(b)['session']
        self.assertEqual(current.get('command_identity_origin'),b['command_identity_origin'])
        self.assertEqual(commands.world_version(current),commands.world_version(b))
        self.assertTrue(formation_session.validate_history(current))
        self.assertEqual([o['order'] for o in commands.prepare(current)['manual']],
                         [o['order'] for o in commands.prepare(b)['manual']]);self.unchanged()

    def test_first_branch_unit_agent_uses_fresh_current_session_and_retains_source_binding(self):
        from backend import unit_planning,harness_engine
        b=self.branch();blue=next(i for i,(row,_) in commands.resolve_units(b).items() if row['team']=='blue')
        b['command_state']['unit_agents']=[blue];prepared=commands.prepare(b);seen=[]
        def native(binding,prompt,observer,*,context,namespace,on_session=None):
            self.assertIsNone(binding);self.assertIn(b['id']+'-e'+str(b['role_epoch']),namespace)
            self.assertNotIn(self.sid,namespace);self.assertEqual(context['session']['command_identity_origin'],b['command_identity_origin'])
            seen.append(namespace)
            created=dict(session_id='gentactix-unit-'+namespace+'-fresh')
            if on_session:on_session(created)
            return SimpleNamespace(final_response=json.dumps(dict(order=dict(action='hold',duration='next'),rationale='独立分支QA'))),created
        with patch.object(harness_engine,'unit_run',side_effect=native):
            orders,decisions=unit_planning.plan(b,prepared,harness_engine.RunObserver('分支单位作用域回归'))
        self.assertEqual(len(seen),1);self.assertEqual(decisions[0]['unit_id'],blue)
        self.assertEqual(len(orders),1);self.assertEqual(self.s['command_state']['agent_sessions'],self.old_agent);self.unchanged()

    def test_source_execution_batch_is_archived_and_cannot_replay_as_branch_success(self):
        payload={**self.revision(), 'batch_id':'source-batch','instruction':'来源已执行请求'}
        self.s['command_state']['batches']['source-batch']=dict(input_hash=commands.fingerprint(payload),turn=0)
        self.s['command_state']['revision']+=1
        session_store.save(self.s);self.original=session_store.serializable(self.s);self.blob=self.path.read_bytes()
        b=self.branch()
        self.assertEqual(b['command_state']['batches'],{})
        self.assertEqual(b['branch_origin']['inherited_batches'],self.s['command_state']['batches'])
        response=self.client.post('/api/sessions/'+b['id']+'/next',json=payload)
        self.assertEqual(response.status_code,409,response.text);self.unchanged()

    def test_reinitialize_branch_starts_new_roster_and_drops_old_conversion_identity(self):
        b=self.branch()
        with patch.object(main.harness_engine,'get_ai_response_with_retry',side_effect=AssertionError('Fixed initial state only')):
            response=self.client.post('/api/sessions/'+b['id']+'/init')
        self.assertEqual(response.status_code,200,response.text)
        for key in ('command_identity_origin','formation_commits','branch_origin','force_organization','command_state'):
            self.assertNotIn(key,b)
        self.assertFalse(b['war_state'].get('formation_registry'));session_store.validate(b)
        rows,errors=session_store.load_all();self.assertFalse(errors)
        self.assertEqual(session_store.serializable(rows[b['id']]),session_store.serializable(b));self.unchanged()

    def test_ordinary_native_turn_uses_same_branch_identity_context(self):
        from backend import session_branch
        raw=main._new_session('普通Native分支上下文QA','30分钟',False,None,False,False,use_agent_tools=True,agent_mode='native')
        raw['war_state']=dict(current_time='1938-10-07 00:00',red_units=[dict(name='普通红军',type='步兵',lat=29.,lng=115.,hp=100,supply=100)],
            blue_units=[dict(name='普通蓝军',type='步兵',lat=29.01,lng=115.01,hp=100,supply=100)])
        b=session_branch.prepare(raw,'b'*12);main._SESSIONS[b['id']]=b;seen=[]
        def model(*args,**kwargs):
            context=kwargs['native_context']['session'];seen.append(context)
            raise ValueError('QA已检查上下文，未执行模型')
        with patch.object(main.harness_engine,'get_role_session'),patch.object(main.harness_engine,'consume_role_amnesia',return_value=False),\
                patch.object(main.harness_engine,'get_ai_response_with_retry',side_effect=model):
            response=self.client.post('/api/sessions/'+b['id']+'/next',json={**self.revision(b),'batch_id':'context-probe'})
        self.assertEqual(response.status_code,502,response.text);self.assertEqual(len(seen),1)
        self.assertEqual(seen[0].get('command_identity_origin'),b['command_identity_origin'])
        self.assertEqual(seen[0].get('role_epoch'),b['role_epoch'])
        self.assertEqual(seen[0].get('branch_origin'),b['branch_origin']);self.unchanged()


if __name__=='__main__':unittest.main(verbosity=2)
