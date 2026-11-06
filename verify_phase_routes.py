"""A continuation is a new checkpoint; a failed native load never mutates its parent."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend import main, scenario_builder
from gentactix import missions, historical_operations
from verify_phase_continuity import checkpoint


class PhaseRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict('os.environ',{'GENTACTIX_SESSION_DIR':str(self.root/'sessions')});self.env.start()
        world,target=checkpoint()
        self.session=main._new_session('QA连续阶段','30分钟',False,world['mission']['definition']['battle'],False,False)
        self.session.update(war_state=world,turn_count=2,execution_backend='narrative',product_mode='historical',
            simulation_mode='open',mission_id=world['mission']['id'],historical_definition=world['mission']['definition'])
        self.registry=patch.dict(main._SESSIONS,{self.session['id']:self.session},clear=True);self.registry.start()
        folder=scenario_builder.directory();folder.mkdir(parents=True)
        record={'kind':'historical_operation','execution_backend':'narrative','initial':target['initial'],
            'parameters':target['parameters'],'construction':{'source':'dsh_native_skill'},
            'definition_hash':missions.digest(historical_operations.from_binding(target))}
        (folder/('a'*32+'.json')).write_text(json.dumps(record))
        self.body={'draft_id':'a'*32,'world_version':missions.digest(world)}
        self.url='/api/sessions/'+self.session['id']+'/phase-continuation'
        self.client=TestClient(main.app)

    def tearDown(self):
        self.registry.stop();self.env.stop();self.temp.cleanup()

    def test_preview_is_read_only_and_commit_creates_restorable_branch(self):
        before=copy.deepcopy(self.session)
        r=self.client.post(self.url+'/preview',json=self.body)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.session,before)
        r=self.client.post(self.url,json=self.body)
        self.assertEqual(r.status_code,200,r.text)
        identity=r.json()['session_id'];self.assertNotEqual(identity,self.session['id'])
        self.assertEqual(main._SESSIONS[identity]['war_state']['red_units'][0]['logistics']['ammo'],3)
        restored,errors=main.session_store.load_all()
        self.assertEqual(errors,[])
        self.assertEqual(restored[identity]['war_state'],main._SESSIONS[identity]['war_state'])
        main.session_store.validate(restored[identity])
        self.assertEqual(self.session['war_state'],before['war_state'])

    def test_native_failure_and_stale_version_cannot_commit(self):
        before=copy.deepcopy(self.session)
        with patch.object(scenario_builder,'_load_world',side_effect=RuntimeError('QA load failed')):
            r=self.client.post(self.url,json=self.body)
        self.assertEqual(r.status_code,502)
        self.assertEqual(self.session,before)
        self.assertEqual(len(main._SESSIONS),1)
        self.body['world_version']='stale'
        self.assertEqual(self.client.post(self.url,json=self.body).status_code,422)

    def test_rule_upgrade_is_rejected_before_native_loading_or_durable_branch(self):
        path=scenario_builder.directory()/('a'*32+'.json')
        draft=json.loads(path.read_text())
        draft['parameters']['rules']['transport_tons_per_truck']=9
        target={'format':historical_operations.FORMAT,'initial':draft['initial'],'parameters':draft['parameters']}
        draft['definition_hash']=missions.digest(historical_operations.from_binding(target))
        path.write_text(json.dumps(draft))
        before=copy.deepcopy(self.session)
        with patch.object(scenario_builder,'_load_world',side_effect=AssertionError('Invalid rules must not load a new engine')) as load:
            for suffix in ('/preview',''):
                response=self.client.post(self.url+suffix,json={**self.body,'version':'historical-phase-continuity-1'})
                self.assertEqual(response.status_code,422,response.text)
                self.assertIn('物理',response.text)
            load.assert_not_called()
        self.assertEqual(self.session,before)
        self.assertEqual(len(main._SESSIONS),1)

    def test_continuation_preserves_groups_control_and_remaining_task_time(self):
        from gentactix import commands, force_organization as forces
        ids = [i for i,(e,_) in commands.resolve_units(self.session).items() if e['team']=='blue']
        self.session['war_state']['mission']['status']='active'
        self.session['force_organization'] = forces.detach(self.session,ids,'阻援群','QA阶段间维持配属')
        self.session['command_state'] = commands.replace_queue(self.session,
            [dict(unit_id=ids[0],action='hold',duration='until_turn',end_turn=5)],
            control_team='blue',director=False,no_fire=True,intent='继续阻援')
        self.session['war_state']['mission']['status']='completed'
        before=copy.deepcopy(self.session)
        preview=self.client.post(self.url+'/preview',json=self.body)
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(self.session,before)

        self.assertEqual(len(preview.json()['command_handoff']['carried']),1)
        r=self.client.post(self.url,json=self.body)
        self.assertEqual(r.status_code,200,r.text)
        child=main._SESSIONS[r.json()['session_id']]
        self.assertEqual(child['force_organization']['groups'],before['force_organization']['groups'])
        self.assertEqual(child['command_state']['control_team'],'blue')
        self.assertTrue(child['command_state']['no_fire'])
        order=child['command_state']['orders'][0]
        self.assertEqual(order['end_turn'],3)
        self.assertIn(order['unit_id'],forces.member_ids(child,child['force_organization']['groups'][0]['id']))
        self.assertNotEqual(order['unit_id'],ids[0])
        restored,errors=main.session_store.load_all()
        self.assertEqual(errors,[])
        for field in ('war_state','force_organization','command_state'):
            self.assertEqual(restored[child['id']][field],child[field])
        main.session_store.validate(restored[child['id']])
        self.assertEqual(self.session,before)

    def test_stale_organization_or_commands_and_disk_failure_keep_parent(self):
        from gentactix import commands, force_organization as forces
        body={**self.body,'organization_revision':forces.state(self.session)['revision'],
            'command_revision':commands.state(self.session)['revision']}
        for field in ('organization_revision','command_revision'):
            r=self.client.post(self.url,json={**body,field:body[field]+1})
            self.assertEqual(r.status_code,422,r.text)
        before=copy.deepcopy(self.session)
        with patch.object(main.session_store,'save',side_effect=OSError('QA disk full')):
            r=self.client.post(self.url,json=body)
        self.assertEqual(r.status_code,503,r.text)
        self.assertEqual(self.session,before)
        self.assertEqual(len(main._SESSIONS),1)

    def expired_local_battle(self):
        from tools.qa.historical_operational_fixture import inputs
        from gentactix import sim_clock
        snapshot,params=inputs();params['goal'].update(profile='assault',radius_km=2)
        params['rules']['goal_profile']='assault'
        world=historical_operations.initial(snapshot,params)
        world['mission']['turn']=2;missions.evaluate(world)
        world['current_time'],world['simulation_clock']=sim_clock.target(world,'1小时')
        self.session.update(war_state=world,turn_count=2,historical_definition=world['mission']['definition'],mission_id=world['mission']['id'])
        self.assertEqual(world['mission']['reason'],'截止回合目标未达成')
        return world

    def test_objective_branch_preserves_expired_battle_and_current_ledgers(self):
        world=self.expired_local_battle();before=copy.deepcopy(self.session)
        r=self.client.post('/api/sessions/'+self.session['id']+'/objective-branch',
            json={'world_version':missions.digest(world)})
        self.assertEqual(r.status_code,200,r.text);value=r.json()
        self.assertNotEqual(value['session_id'],self.session['id']);self.assertEqual(value['turn_count'],2)
        child=main._SESSIONS[value['session_id']];after=child['war_state']
        self.assertEqual(after['mission']['status'],'active')
        self.assertEqual(after['mission']['definition']['termination_mode'],'objectives')
        self.assertEqual(after['current_time'],world['current_time'])
        self.assertIn('尚未执行新的推演回合',child['history'][0])
        for key in ('red_units','blue_units','supply_nodes','combined_arms'):
            self.assertEqual(after[key],world[key])
        self.assertEqual(self.session,before);self.assertTrue(missions.validate(after))
        main.session_store.validate(child)

    def test_objective_branch_rejects_stale_or_strict_history_without_creating_session(self):
        world=self.expired_local_battle();path='/api/sessions/'+self.session['id']+'/objective-branch'
        self.assertEqual(self.client.post(path,json={'world_version':'stale'}).status_code,422)
        self.session['product_mode']='analysis'
        r=self.client.post(path,json={'world_version':missions.digest(world)})
        self.assertEqual(r.status_code,422);self.assertEqual(len(main._SESSIONS),1)


if __name__ == '__main__': unittest.main()
