"""Formal zero-time conversion, durable rollback and ordinary API admission.

Offline fixtures prove contracts, not real Native execution or history.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import main,session_store
from gentactix import commands,formation_conversion as conversion,formation_session,force_organization,missions
from verify_formation_session import setup


def fixture(initial_world=None):
    s,uid,group=setup(initial_world);w=s['war_state'];definition=w['mission']['definition']
    full=main._new_session('编组事务回归QA',s['time_step'],False,definition['battle'],False,False,agent_mode='native')
    full.update(s);full.update(mission_id=w['mission']['id'],historical_definition=definition,
        synthetic_configuration=definition.get('synthetic_configuration'),
        scenario_construction=dict(id='c'*32,definition_hash=w['mission']['definition_hash'],construction={'source':'dsh_native_skill'}))
    session_store.validate(full)
    return full,uid,group


class ConversionCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source,cls.uid,cls.group=fixture()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.session=copy.deepcopy(self.source)
        self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':self.temp.name+'/sessions',
            'GENTACTIX_TRACE_DIR':self.temp.name+'/traces','GENTACTIX_ROLE_INDEX':self.temp.name+'/roles.json'})
        self.env.start();session_store.save(self.session)
        self.path=Path(self.temp.name)/'sessions'/(self.session['id']+'.json')

    def tearDown(self):self.env.stop();self.temp.cleanup()

    def request(self,session=None,**changes):
        s=session or self.session;view=commands.view(s)
        args=dict(kind='split',unit_ids=[self.uid],allocations=[dict(id='left',label='事务左',committed=5000),
            dict(id='right',label='事务右',committed=5000)],assumption='软件事务QA，非历史编制命令')
        args.update(changes)
        if args.get('allocations','present') is None:args.pop('allocations')
        preview=conversion.observation(s,args)
        return dict(**args,expected_turn=s['turn_count'],revision=view['revision'],world_version=view['world_version'],
            organization_revision=force_organization.state(s)['revision'],view_version=preview['view_version'],commit_id='f'*32)

    def commit(self,request):
        from backend import formation_commit
        return formation_commit.commit(self.session,request)

    def test_success_saves_before_memory_adoption_and_cold_restores_normal_session(self):
        request=self.request();before=copy.deepcopy(self.session);original=self.path.read_bytes()
        real_save=session_store.save
        def save(candidate):
            self.assertEqual(self.session,before);self.assertEqual(self.path.read_bytes(),original)
            session_store.validate(candidate);real_save(candidate)
        with patch.object(session_store,'save',side_effect=save) as writer:result=self.commit(request)
        self.assertEqual(writer.call_count,1);self.assertFalse(result['replayed'])
        self.assertTrue(result['runtime_admitted']);self.assertFalse(result['physics_executed'])
        self.assertEqual(self.session['turn_count'],before['turn_count'])
        self.assertEqual(self.session['war_state']['simulation_clock'],before['war_state']['simulation_clock'])
        self.assertEqual(self.session['history'],before['history']);self.assertEqual(self.session['trajectory'],before['trajectory'])
        self.assertEqual(len(self.session['war_state']['red_units']),len(before['war_state']['red_units'])+1)
        self.assertTrue(missions.validate(self.session['war_state']))
        loaded,errors=session_store.load_all();self.assertFalse(errors);session_store.validate(loaded[self.session['id']])
        self.assertEqual(session_store.serializable(self.session),session_store.serializable(loaded[self.session['id']]))
        self.assertEqual(len(commands.prepare(self.session)['state']['registry']),len(self.session['command_state']['registry']))

    def test_exact_retry_returns_receipt_without_second_save_or_conversion(self):
        request=self.request();first=self.commit(request);before=copy.deepcopy(self.session);blob=self.path.read_bytes()
        with patch.object(session_store,'save',side_effect=AssertionError('No duplicate write')):second=self.commit(request)
        self.assertTrue(second['replayed']);self.assertEqual(first['registry_revision'],second['registry_revision'])
        self.assertEqual(second['command_map'],first['command_map'])
        self.assertEqual(second['current_command_map'],first['command_map'])
        self.assertEqual(self.session,before);self.assertEqual(self.path.read_bytes(),blob)
        changed=copy.deepcopy(request);changed['assumption']='篡改重试输入'
        with self.assertRaises(ValueError):self.commit(changed)
        self.assertEqual(self.session,before)

    def test_stale_world_command_organization_turn_or_preview_rejects_without_writes(self):
        request=self.request();before=copy.deepcopy(self.session);blob=self.path.read_bytes()
        for key,value in [('world_version','stale'),('revision',99),('organization_revision',99),('expected_turn',99),('view_version','stale')]:
            with self.subTest(key=key),self.assertRaises((ValueError,commands.Conflict)):
                self.commit({**request,key:value})
            self.assertEqual(self.session,before);self.assertEqual(self.path.read_bytes(),blob)

    def test_fsync_and_replace_failure_leave_original_memory_file_and_queue(self):
        request=self.request();before=copy.deepcopy(self.session);blob=self.path.read_bytes()
        for name in ('fsync','replace'):
            with self.subTest(name=name),patch.object(session_store.os,name,side_effect=OSError('disk failure')),self.assertRaises(OSError):
                self.commit(request)
            self.assertEqual(self.session,before);self.assertEqual(self.path.read_bytes(),blob)
            self.assertFalse(self.path.with_suffix('.tmp').exists())
        self.assertTrue(self.commit(request)['runtime_admitted'])

    def test_compile_failure_does_not_save_or_adopt_candidate(self):
        from backend import formation_commit
        request=self.request();before=copy.deepcopy(self.session);blob=self.path.read_bytes()
        with patch.object(formation_commit,'compile_candidate',side_effect=ValueError('compiler rejected')),patch.object(session_store,'save',side_effect=AssertionError('No save')),self.assertRaisesRegex(ValueError,'compiler rejected'):
            self.commit(request)
        self.assertEqual(self.session,before);self.assertEqual(self.path.read_bytes(),blob)

    def test_prepared_world_remains_unadmitted_and_forged_or_missing_session_receipts_reject(self):
        from verify_formation_session import prepare
        candidate=prepare(self.session)['session']
        with self.assertRaises(ValueError):session_store.validate(candidate)
        self.commit(self.request());before=copy.deepcopy(self.session)
        for kind in ('world','commands','journal'):
            bad=copy.deepcopy(before)
            if kind=='world':bad['war_state']['formation_runtime']['registry_hash']='0'*64
            elif kind=='commands':bad['war_state']['formation_runtime']['handoff_hash']='0'*64
            else:bad['formation_commits']={}
            with self.subTest(kind=kind),self.assertRaises(ValueError):session_store.validate(bad)

    def test_valid_physical_allocation_cannot_be_logged_as_a_different_requested_allocation(self):
        from gentactix import formation_runtime
        request=self.request();actual=copy.deepcopy(request['allocations'])
        request['allocations'][0]['committed']=4000;request['allocations'][1]['committed']=6000
        args={k:request[k] for k in ('kind','unit_ids','allocations','assumption')}
        operation=missions.digest([request['world_version'],request['revision'],request['organization_revision'],args])[:32]
        unit=commands.resolve_units(self.session)[self.uid][1]
        proposal=conversion.split_current(unit,actual,assumption=request['assumption'],operation_id=operation,
            product_mode='synthetic',historical_snapshot=self.session['war_state']['historical_initial'])
        candidate=formation_session.prepare(self.session,proposal,team='red')['session']
        request['view_version']=missions.digest([request['world_version'],request['revision'],request['organization_revision'],proposal['proposal_hash']])
        candidate['formation_commits']={request['commit_id']:dict(version=formation_runtime.VERSION,
            request=request,request_hash=commands.fingerprint(request),registry_revision=1,
            proposal_hash=proposal['proposal_hash'],view_version=request['view_version'])}
        formation_runtime.seal(candidate)
        with self.assertRaisesRegex(ValueError,'分配|输入|提案'):session_store.validate(candidate)

    def test_second_conversion_merge_and_normal_restore_preserve_two_journal_entries(self):
        self.commit(self.request());s=self.session
        ids=[i for i,(_,u) in commands.resolve_units(s).items() if u.get('runtime_allocation')]
        request=self.request(kind='merge',unit_ids=ids,allocations=None)
        request.pop('allocations',None);request['commit_id']='e'*32
        result=self.commit(request);self.assertEqual(result['registry_revision'],2)
        self.assertEqual(len(self.session['formation_commits']),2)
        self.assertEqual(len(self.session['war_state']['red_units']),len(self.source['war_state']['red_units']))
        loaded,errors=session_store.load_all();self.assertFalse(errors);formation_session.validate(loaded[s['id']])

    def test_afsim_codec_compile_is_zero_time_and_does_not_execute_a_job(self):
        from backend import afsim_world
        self.session['execution_backend']='afsim';request=self.request();before=copy.deepcopy(self.session['war_state'])
        with patch.object(afsim_world,'run_scene',side_effect=AssertionError('No physics at conversion')):
            result=self.commit(request)
        self.assertFalse(result['physics_executed']);self.assertTrue(result['runtime_admitted'])
        self.assertEqual(self.session['war_state']['simulation_clock'],before['simulation_clock'])
        self.assertEqual(conversion._totals(self.session['war_state']['red_units']),conversion._totals(before['red_units']))

    def test_permissions_and_replay_mode_cannot_commit_a_preview(self):
        request=self.request();before=copy.deepcopy(self.session);blob=self.path.read_bytes()
        self.session['command_state']['director']=False;self.session['command_state']['control_team']='blue'
        with self.assertRaisesRegex(ValueError,'权限'):self.commit(request)
        self.session=copy.deepcopy(before);self.session['simulation_mode']='replay'
        with self.assertRaisesRegex(ValueError,'回放'):self.commit(request)
        self.assertEqual(self.path.read_bytes(),blob)

    def test_new_unit_native_context_preserves_epoch_mode_and_current_world_binding(self):
        from backend import unit_planning,harness_engine
        from types import SimpleNamespace
        self.session['execution_backend']='afsim';result=self.commit(self.request())
        identity=next(iter(result['command_map'].values()))[0]
        self.session['command_state']['unit_agents']=[identity]
        self.session['command_state']['orders']=[]
        prepared=commands.prepare(self.session);observer=harness_engine.RunObserver('转换后单位作用域回归')
        def native(binding,prompt,watcher,*,context,namespace,on_session=None):
            current=context['session']
            self.assertEqual(current.get('role_epoch'),self.session['role_epoch'])
            self.assertEqual(current.get('product_mode'),self.session['product_mode'])
            self.assertEqual(commands.world_version(current),commands.world_version(self.session))
            if on_session:on_session({})
            return SimpleNamespace(final_response=json.dumps(dict(order=dict(unit_id=identity,action='hold',duration='next'),rationale='QA'))),{}
        with patch.object(harness_engine,'unit_run',side_effect=native):
            orders,decisions=unit_planning.plan(self.session,prepared,observer)
        self.assertEqual(len(orders),1);self.assertEqual(decisions[0]['unit_id'],identity)

    def test_native_unit_can_return_action_without_repeating_its_host_bound_identity(self):
        from backend import unit_planning,harness_engine
        from types import SimpleNamespace
        self.commit(self.request());identity=next(i for i,(_,u) in commands.resolve_units(self.session).items() if u.get('runtime_allocation'))
        self.session['command_state'].update(unit_agents=[identity],orders=[])
        prepared=commands.prepare(self.session);observer=harness_engine.RunObserver('宿主绑定单位身份回归')
        answer=SimpleNamespace(final_response=json.dumps(dict(order=dict(action='hold',duration='next'),rationale='本单位待命')))
        with patch.object(harness_engine,'unit_run',return_value=(answer,{})):
            orders,decisions=unit_planning.plan(self.session,prepared,observer)
        self.assertEqual(len(orders),1);self.assertEqual(decisions[0]['unit_id'],identity)

    def test_explicit_wrong_native_identity_is_rejected_with_exact_binding_feedback(self):
        from backend import unit_planning,harness_engine
        from types import SimpleNamespace
        identity=self.uid;self.session['command_state'].update(unit_agents=[identity],orders=[])
        prepared=commands.prepare(self.session);observer=harness_engine.RunObserver('显式错误单位身份回归')
        typo=identity[:16]+'extra'+identity[16:]
        answer=SimpleNamespace(final_response=json.dumps(dict(order=dict(unit_id=typo,action='hold',duration='next'))))
        with patch.object(harness_engine,'unit_run',return_value=(answer,{})),self.assertRaises(ValueError) as error:
            unit_planning.plan(self.session,prepared,observer)
        self.assertIn(identity,str(error.exception));self.assertIn(typo,str(error.exception))

    def test_legacy_missing_epoch_keeps_the_existing_zero_epoch_world_version(self):
        from backend import afsim_state
        legacy=copy.deepcopy(self.session);legacy.pop('role_epoch',None)
        context=afsim_state.operation_context(legacy)['session']
        self.assertEqual(commands.world_version(context),commands.world_version(legacy))

    def test_restore_rejects_construction_record_missing_the_id_required_by_normal_snapshot(self):
        bad=copy.deepcopy(self.session);bad['scenario_construction'].pop('id')
        with self.assertRaisesRegex(ValueError,'构建|id|ID'):session_store.validate(bad)

    def test_ordinary_http_preview_commit_and_new_unit_order_use_existing_lock_and_one_write(self):
        from fastapi.testclient import TestClient
        request=self.request();sid=self.session['id'];base='/api/sessions/'+sid+'/force-organization'
        with patch.dict(main._SESSIONS,{sid:self.session},clear=True):
            client=TestClient(main.app)
            with patch.object(session_store,'save',wraps=session_store.save) as writer:
                response=client.post(base+'/conversion-commit',json=request)
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(writer.call_count,1)
            self.assertTrue(response.json()['conversion_result']['runtime_admitted'])
            self.assertEqual(client.post(base+'/conversion-commit',json=request).status_code,200)
            self.assertEqual(client.get('/api/sessions/'+sid).status_code,200)
            view=client.get('/api/sessions/'+sid+'/commands').json()
            selected=[u['id'] for u in view['units'] if u['controllable']]
            order=client.put('/api/sessions/'+sid+'/commands',json=dict(expected_turn=self.session['turn_count'],
                revision=view['revision'],world_version=view['world_version'],orders=[dict(unit_id=selected[0],action='hold',duration='next')],control_team='red',director=True,no_fire=False,intent='QA'))
            self.assertEqual(order.status_code,200,order.text)
            current=client.get('/api/sessions/'+sid+'/commands').json();before=copy.deepcopy(self.session)
            branch=client.post('/api/sessions/'+sid+'/commands/open-branch',json=dict(expected_turn=self.session['turn_count'],
                revision=current['revision'],world_version=current['world_version']))
            self.assertEqual(branch.status_code,200,branch.text);self.assertEqual(self.session,before)
            self.assertNotEqual(branch.json()['session_id'],sid)
            main._OP_LOCK.acquire()
            try:self.assertEqual(client.post(base+'/conversion-commit',json={**request,'commit_id':'d'*32}).status_code,409)
            finally:main._OP_LOCK.release()


class HistoricalEstimatedCommitTests(unittest.TestCase):
    def test_estimated_split_commits_as_distinct_units_under_source_parent(self):
        from backend import formation_commit
        from tools.qa.formation_ownership_fixture import historical_parent_world
        world=historical_parent_world();definition=world['mission']['definition']
        session=main._new_session('历史计算分队事务验证',definition['time_step'],False,definition['battle'],False,False,agent_mode='native')
        session.update(war_state=world,mission_id=world['mission']['id'],historical_definition=definition,
            product_mode='historical',simulation_mode='open',execution_backend='narrative')
        session['command_state']=commands.replace_queue(session,[],control_team='red',director=True,no_fire=False,intent='QA')
        view=commands.view(session);unit=next(u for u in view['units'] if u['name']=='第74军')
        total=unit['personnel']['committed']
        args=dict(kind='split',unit_ids=[unit['id']],allocations=[dict(id='a',label='甲计算团',committed=total//2),
            dict(id='b',label='乙计算团',committed=total-total//2)],assumption='教学计算分队，不是历史番号')
        preview=conversion.observation(session,args)
        request=dict(**args,expected_turn=session['turn_count'],revision=view['revision'],world_version=view['world_version'],
            organization_revision=force_organization.state(session)['revision'],view_version=preview['view_version'],commit_id='e'*32)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':tmp+'/sessions',
                'GENTACTIX_TRACE_DIR':tmp+'/traces','GENTACTIX_ROLE_INDEX':tmp+'/roles.json'}):
            session_store.save(session)
            result=formation_commit.commit(session,request)
            children=result['current_command_map'][unit['id']]
            self.assertEqual(len(children),2)
            roster=commands.view(session)['units']
            self.assertTrue(all(any(u['id']==identity and u['controllable'] for u in roster) for identity in children))
            node=next(n for n in force_organization.view(session)['nodes'] if n['id']=='ww2.cn.army74')
            self.assertEqual(node['totals']['committed'],total)
            self.assertEqual(node['totals']['units'],2)
            session_store.validate(session)
            self.assertFalse(session_store.load_all()[1])
            queue=commands.replace_queue(session,[dict(unit_id=children[0],action='hold',duration='next'),
                dict(unit_id=children[1],action='recon',duration='next')],control_team='red',director=True,no_fire=False,intent='QA')
            self.assertEqual({order['action'] for order in queue['orders']},{'hold','recon'})
            self.assertEqual({order['unit_id'] for order in queue['orders']},set(children))


if __name__=='__main__':unittest.main(verbosity=2)
