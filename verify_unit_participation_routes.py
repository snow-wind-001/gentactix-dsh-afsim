"""Normal command/force routes and durable state; model replies here are fixtures."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from gentactix import commands,historical_operations
from tools.qa.campaign_plan_fixture import inputs


class ParticipationRouteTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();base=Path(self.folder.name)
        self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(base/'sessions'),'GENTACTIX_TRACE_DIR':str(base/'traces')});self.env.start()
        from backend import main,session_store
        self.main=main;self.store=session_store;source,p=inputs();world=historical_operations.initial(source,p)
        self.session=main._new_session('参与状态路由软件QA','30分钟',False,source['definition']['battle'],False,False,agent_mode='native',persist_roles=False)
        self.session.update(war_state=world,mission_id=world['mission']['id'],historical_definition=copy.deepcopy(world['mission']['definition']),
            product_mode='historical',simulation_mode='open',execution_backend='narrative')
        self.sid=self.session['id'];main._SESSIONS[self.sid]=self.session;self.base='/api/sessions/'+self.sid
        self.client=TestClient(main.app,raise_server_exceptions=False)
        unit=next(u for u in self.view()['units'] if u['name']=='第159师');self.identity=unit['id']
        self.point=dict(lat=unit['position']['lat']+.001,lng=unit['position']['lng'])
        self.order=dict(unit_id=self.identity,action='move',duration='until_arrived',destination=self.point,participation='withdraw')

    def tearDown(self):
        self.main._SESSIONS.pop(self.sid,None);self.env.stop();self.folder.cleanup()

    def view(self):
        response=self.client.get(self.base+'/commands');self.assertEqual(response.status_code,200,response.text);return response.json()

    def revision(self):
        v=self.view();return dict(expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'])

    def put(self,orders,**extra):
        return self.client.put(self.base+'/commands',json={**self.revision(),'orders':orders,'director':True,**extra})

    def test_save_and_cold_restore_keep_intent_without_changing_physical_world(self):
        before=copy.deepcopy(self.session['war_state']);r=self.put([self.order]);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['orders'][0]['participation'],'withdraw');self.assertEqual(self.session['war_state'],before)
        restored,errors=self.store.load_all();self.assertFalse(errors);cold=restored[self.sid]
        raw=commands.prepare(cold)['manual'][0]['order']
        self.assertEqual(raw['participation']['destination'],self.point)
        self.assertEqual(raw['participation']['id'],r.json()['orders'][0]['id'])

    def test_invalid_directive_or_failed_checkpoint_never_partially_replaces_the_queue(self):
        before=copy.deepcopy(self.session)
        r=self.put([{**self.order,'participation':'teleport'}]);self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.session,before)
        with patch.object(self.store,'save',side_effect=OSError('QA full disk')):r=self.put([self.order])
        self.assertEqual(r.status_code,503);self.assertEqual(self.session,before)

    def test_natural_language_intent_is_visible_and_cannot_be_edited_under_its_old_source_reference(self):
        from backend import harness_engine as h
        with patch.object(h,'get_ai_response',return_value={'orders':[self.order],'clarifications':[]}):
            r=self.client.post(self.base+'/commands/resolve',json={**self.revision(),'text':'到地图选点退出当前作战',
                'selected_units':[self.identity],'map_target':self.point})
        self.assertEqual(r.status_code,200,r.text);proposal=r.json();self.assertFalse(self.view()['orders'])
        edited={k:v for k,v in self.order.items() if k!='participation'}
        rejected=self.put([edited],proposal_id=proposal['id']);self.assertEqual(rejected.status_code,422,rejected.text)
        accepted=self.put(proposal['orders'],proposal_id=proposal['id']);self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(accepted.json()['orders'][0]['participation'],'withdraw')

    def test_group_task_preview_and_commit_use_the_same_participation_contract(self):
        self.assertEqual(self.put([]).status_code,200)
        def rev():
            v=self.client.get(self.base+'/force-organization').json()
            return dict(expected_turn=v['turn'],revision=v['command_revision'],world_version=v['world_version'],organization_revision=v['revision'])
        r=self.client.post(self.base+'/force-organization/detach',json={**rev(),'unit_ids':[self.identity],'label':'退出任务群','assumption':'软件QA临时编组'})
        self.assertEqual(r.status_code,200,r.text);group=r.json()['groups'][-1]['id']
        body={**rev(),'group_id':group,'task':dict(kind='withdraw',destination=self.point,participation='withdraw')}
        before=copy.deepcopy(self.session['war_state']);r=self.client.post(self.base+'/force-organization/task-preview',json=body)
        self.assertEqual(r.status_code,200,r.text);preview=r.json()
        self.assertEqual(preview['rows'][0]['order']['participation'],'withdraw');self.assertEqual(self.session['war_state'],before)
        r=self.client.post(self.base+'/force-organization/tasks',json={**body,'preview_hash':preview['preview_hash']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(commands.prepare(self.session)['manual'][0]['order']['participation']['kind'],'withdraw')


if __name__=='__main__':unittest.main()
