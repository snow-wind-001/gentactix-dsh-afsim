"""Validated configuration prefixes survive Native failures; never execute model text."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import scenario_builder as builder,scenario_assembly as assembly
from gentactix import missions,scenario_constraints
from tools.qa.jizhong_assembly_fixture import inputs


class ScenarioResumeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall);patch.object(builder,'directory',return_value=Path(self.directory.name)).start()
        self.snapshot,self.params=inputs();self.basis=builder.historical_basis(self.snapshot['definition']['battle'],
            self.snapshot['phase_id'],force_scope='campaign',time_step='30分钟',termination_mode='objectives')
        self.fixed=[{'path':['aviation','ww2.jp.flight29','initial',k],'value':v} for k,v in [('committed',4),('ordnance',8),('fuel',16)]]
        scenario_constraints.prepare(self.basis,self.fixed)

    def prefix(self):
        draft=assembly.create(self.basis);self.addCleanup(assembly.close,draft.id)
        result=draft.tool('globals','update_scenario_configuration',{'revision':0,
            'patch':{k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')}})
        self.assertTrue(result['updated'],result)
        for part in draft.parts[:5]:
            result=draft.tool(part,'update_scenario_configuration',{'revision':draft.revision,
                'patch':{'actors':{i:self.params['actors'][i] for i in draft.assigned(part)}}})
            self.assertTrue(result['updated'],result)
        self.assertEqual(len(draft.filled),20)
        return draft

    def checkpoint(self,draft,*,complete=False):
        from backend import scenario_checkpoints as checkpoints
        work=checkpoints.new_work('QA','narrative')
        sid='gentactix-unit-scenario-'+draft.id+'-parent'
        work['bindings'][sid]={'session_id':sid};work['coordinator']=sid
        for row in draft.audit:
            work['stages'].append({**row,'session_id':sid})
            work['part_bindings'][row['part']]=sid
        if complete:
            result=draft.tool('final','validate_scenario_configuration',{})
            self.assertTrue(result['valid'],result)
            work['stages'].append({'part':'final',**draft.receipt(),'session_id':sid})
            work['status']='configured'
        return checkpoints.save(draft,work)

    def native_ok(self,calls,hook=None):
        def run(binding,prompt,observer,**kwargs):
            context=kwargs['context'];part=context['scenario_composer']['part'];calls.append(part)
            handle=binding or {'session_id':'gentactix-unit-'+kwargs['namespace']+'-'+str(len(calls))}
            kwargs['on_session'](handle)
            if hook:hook('before',part,context,observer)
            builder.execute_tool(context,{'tool':'read_scenario_skill'})
            view=builder.execute_tool(context,{'tool':'get_scenario_basis'});names=['read_scenario_skill','get_scenario_basis']
            if context['scenario_composer'].get('read_only'):result=view
            elif part=='final':
                result=builder.execute_tool(context,{'tool':'validate_scenario_configuration'});names.append('validate_scenario_configuration')
                self.assertTrue(result['valid'],result)
            else:
                patch_={k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')} if part=='globals' else {'actors':{i:self.params['actors'][i] for i in view['assigned_actor_ids']}}
                result=builder.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':view['revision'],'patch':patch_}})
                self.assertTrue(result['updated'],result);names.append('update_scenario_configuration')
            observer.runs.append({'id':handle['session_id']+':'+str(len(calls)),'session_id':handle['session_id'],
                'finish_reason':'completed','events':[{'type':'tool/call','name':n} for n in names]})
            final=hook('after',part,context,observer) if hook else None
            return SimpleNamespace(final_response=final or json.dumps({k:result[k] for k in ('revision','configuration_hash')})),handle
        return run

    def test_cancel_in_native_stage_returns_checkpoint_and_does_not_change_parameters(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft);assembly.close(draft.id);calls=[]
        def cancel(when,part,context,observer):
            if when=='before':
                saved=checkpoints.read(draft.id)
                self.assertEqual(saved['work']['part_bindings'][part],'gentactix-unit-scenario-'+draft.id+'-1')
                self.assertIn(saved['work']['part_bindings'][part],saved['work']['bindings'])
                observer.cancel_requested=True;raise RuntimeError('QA native cancelled')
        app=FastAPI();app.include_router(builder.build_router(lambda fn:fn))
        with patch.object(builder.h,'unit_run',side_effect=self.native_ok(calls,cancel)),\
             patch.object(builder.h,'restore_unit_session',side_effect=lambda binding,**kw:binding),\
             patch.object(builder.h,'dispose_unit_sessions'):
            reply=TestClient(app).post('/api/historical-scenarios/resume',json={'assembly_id':draft.id})
        self.assertEqual(reply.status_code,409,reply.text);self.assertEqual(reply.json()['detail']['assembly_id'],draft.id)
        self.assertEqual(checkpoints.read(draft.id)['state'],record['state']);self.assertEqual(calls,['actors:5'])

    def test_written_stage_with_missing_receipt_resumes_readonly_without_rewriting(self):
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft);assembly.close(draft.id);calls=[];attempt=0
        def fail(when,part,context,observer):
            nonlocal attempt
            if when=='after' and part=='actors:5':attempt+=1;return 'invalid receipt'
            if when=='before' and attempt:raise RuntimeError('QA receipt retry connection failed')
        with patch.object(builder.h,'unit_run',side_effect=self.native_ok(calls,fail)),\
             patch.object(builder.h,'restore_unit_session',side_effect=lambda binding,**kw:binding),patch.object(builder.h,'dispose_unit_sessions'):
            with self.assertRaisesRegex(RuntimeError,'receipt retry'):
                builder.build_historical_staged(record['state']['basis'],'QA','narrative',builder.h.RunObserver('first'),resume_checkpoint=draft.id)
        saved=checkpoints.read(draft.id)
        self.assertEqual(len(saved['state']['filled']),24);self.assertEqual(len(saved['work']['stages']),6)
        calls.clear()
        with patch.object(builder.h,'unit_run',side_effect=self.native_ok(calls)),\
             patch.object(builder.h,'restore_unit_session',side_effect=lambda binding,**kw:binding),patch.object(builder.h,'dispose_unit_sessions'):
            config,construction=builder.build_historical_staged(record['state']['basis'],'QA','narrative',builder.h.RunObserver('second'),resume_checkpoint=draft.id)
        self.assertTrue(construction['stages'][6]['restored_validated_write'])
        self.assertEqual(construction['draft_updates'][6],saved['state']['audit'][6])
        self.assertEqual(len(construction['draft_updates']),10);self.assertEqual(len(config['actors']),34)

    def test_stage_receipt_cannot_borrow_another_parts_hash(self):
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft);assembly.close(draft.id)
        record['work']['stages'][2]['configuration_hash']=record['work']['stages'][0]['configuration_hash']
        record.pop('checkpoint_hash');record['checkpoint_hash']=missions.digest(record)
        builder._save_draft(record,None)
        with self.assertRaisesRegex(ValueError,'回执'):checkpoints.restore(draft.id)

    def test_checkpoint_io_failure_does_not_accept_an_unsaved_update(self):
        draft=self.prefix();before=draft.export_state()
        def fail(_):raise OSError('QA disk full')
        draft.on_change=fail;part=draft.parts[5]
        with self.assertRaises(OSError):
            draft.tool(part,'update_scenario_configuration',{'revision':draft.revision,
                'patch':{'actors':{i:self.params['actors'][i] for i in draft.assigned(part)}}})
        self.assertEqual(draft.export_state(),before)

    def test_completed_checkpoint_needs_no_model_or_native_journal_to_retry_load(self):
        draft=self.prefix()
        for part in draft.parts[5:]:
            result=draft.tool(part,'update_scenario_configuration',{'revision':draft.revision,
                'patch':{'actors':{i:self.params['actors'][i] for i in draft.assigned(part)}}})
            self.assertTrue(result['updated'],result)
        record=self.checkpoint(draft,complete=True);assembly.close(draft.id)
        with patch.object(builder.h,'unit_run') as run,patch.object(builder.h,'restore_unit_session') as resume,\
             patch.object(builder.h,'dispose_unit_sessions'):
            config,construction=builder.build_historical_staged(record['state']['basis'],'QA','narrative',
                builder.h.RunObserver('QA load retry'),resume_checkpoint=draft.id)
        run.assert_not_called();resume.assert_not_called()
        self.assertEqual(config,self.params);self.assertEqual(len(construction['resume']['skipped_stages']),11)

    def test_missing_native_parent_fails_without_creating_fresh_sessions(self):
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft);assembly.close(draft.id)
        with patch.object(builder.h,'restore_unit_session',side_effect=RuntimeError('QA missing journal')),\
             patch.object(builder.h,'unit_run') as run,patch.object(builder.h,'dispose_unit_sessions'):
            with self.assertRaisesRegex(RuntimeError,'missing journal') as caught:
                builder.build_historical_staged(record['state']['basis'],'QA','narrative',
                    builder.h.RunObserver('QA missing journal'),resume_checkpoint=draft.id)
        run.assert_not_called();self.assertEqual(caught.exception.assembly_id,draft.id)
        self.assertEqual(checkpoints.read(draft.id)['state'],record['state'])

    def test_explicit_rebuild_creates_only_the_unwritten_failed_part_and_keeps_old_binding(self):
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft);old='gentactix-unit-scenario-'+draft.id+'-failed'
        work=record['work'];work['bindings'][old]={'session_id':old};work['part_bindings']['actors:5']=old
        work.update(failed_part='actors:5',status='interrupted');checkpoints.save(draft,work);assembly.close(draft.id)
        seen=[];run=self.native_ok([])
        def native(binding,*args,**kwargs):
            seen.append((kwargs['context']['scenario_composer']['part'],binding));return run(binding,*args,**kwargs)
        with patch.object(builder.h,'unit_run',side_effect=native),patch.object(builder.h,'dispose_unit_sessions'),\
             patch.object(builder.h,'restore_unit_session',side_effect=lambda binding,**kw:binding) as parent:
            config,construction=builder.build_historical_staged(record['state']['basis'],'QA','narrative',
                builder.h.RunObserver('QA explicit rebuild'),resume_checkpoint=draft.id,rebuild_failed_session=True)
        self.assertEqual(seen[0],('actors:5',None));parent.assert_called_once()
        saved=checkpoints.read(draft.id)
        self.assertIn(old,saved['work']['bindings']);self.assertNotEqual(saved['work']['part_bindings']['actors:5'],old)
        self.assertEqual(saved['state']['audit'][:6],record['state']['audit']);self.assertEqual(len(config['actors']),34)
        self.assertEqual(construction['resume']['rebuilt_session'],{'part':'actors:5','previous_session_id':old})

    def test_rebuild_cannot_replace_an_already_validated_part(self):
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft)
        record['work'].update(failed_part='actors:4',status='interrupted')
        checkpoints.save(draft,record['work']);assembly.close(draft.id)
        with patch.object(builder.h,'unit_run') as run:
            with self.assertRaisesRegex(ValueError,'未写入'):
                builder.build_historical_staged(record['state']['basis'],'QA','narrative',
                    builder.h.RunObserver('QA unsafe rebuild'),resume_checkpoint=draft.id,rebuild_failed_session=True)
        run.assert_not_called()

    def test_resume_endpoint_rejects_editable_parameters_and_loaded_checkpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import scenario_checkpoints as checkpoints
        app=FastAPI();app.include_router(builder.build_router(lambda fn:fn));client=TestClient(app)
        draft=self.prefix();record=self.checkpoint(draft);assembly.close(draft.id)
        with patch.object(builder,'build_historical_staged',side_effect=AssertionError('must reject before model')):
            reply=client.post('/api/historical-scenarios/resume',json={'assembly_id':draft.id,'parameters':self.params})
        self.assertEqual(reply.status_code,422)
        checkpoints.mark_loaded(draft.id,'c'*32)
        self.assertEqual(client.post('/api/historical-scenarios/resume',json={'assembly_id':draft.id}).status_code,422)

    def test_cancel_response_exposes_durable_progress_and_basis_lists_only_same_scope(self):
        from backend import scenario_checkpoints as checkpoints
        draft=self.prefix();record=self.checkpoint(draft);error=RuntimeError('QA cancelled')
        error.assembly_id=draft.id;error.assembly_summary=checkpoints.summary(record)
        response=builder._assembly_failure(error,True)
        self.assertEqual(response.status_code,409);self.assertEqual(response.detail['assembly_progress']['validated_actors'],20)
        rows=checkpoints.pending(self.snapshot,force_scope='campaign')
        self.assertEqual([r['id'] for r in rows],[draft.id]);self.assertFalse(rows[0]['active'])
        self.assertEqual(checkpoints.pending(self.snapshot,force_scope='phase'),[])

    def test_validated_twenty_actor_state_restores_exactly_without_live_catalogue(self):
        from gentactix import historical_initial
        draft=self.prefix();state=draft.export_state();assembly.close(draft.id)
        with patch.object(historical_initial,'DATA_ROOT',historical_initial.DATA_ROOT/'absent'):
            restored=assembly.restore(state)
        self.addCleanup(assembly.close,restored.id)
        self.assertEqual(restored.id,draft.id);self.assertEqual(restored.revision,6)
        self.assertEqual(restored.configuration,draft.configuration);self.assertEqual(restored.filled,draft.filled)
        self.assertEqual(restored.basis['fixed_parameters']['values'],self.fixed)
        self.assertEqual(restored.assigned('actors:5'),draft.ids[20:24])

    def test_restore_rejects_changed_candidate_fixed_value_and_missing_actor(self):
        draft=self.prefix();state=draft.export_state();assembly.close(draft.id)
        for kind in ('fixed','missing','unfilled','revision','filled'):
            s=copy.deepcopy(state)
            if kind=='fixed':s['configuration']['aviation']['ww2.jp.flight29']['initial']['fuel']=100
            if kind=='missing':s['configuration']['actors'].pop(draft.ids[-1])
            if kind=='unfilled':s['configuration']['actors'][draft.ids[-1]]['personnel']=999
            if kind=='revision':s['revision']+=1
            if kind=='filled':s['filled'].append(draft.ids[-1])
            with self.subTest(kind=kind),self.assertRaises(ValueError):assembly.restore(s)

    def test_saved_draft_prefix_is_not_a_runnable_historical_operation(self):
        from backend import scenario_checkpoints
        draft=self.prefix();work=scenario_checkpoints.new_work('QA','narrative')
        record=scenario_checkpoints.save(draft,work);self.assertEqual(record['kind'],'historical_assembly')
        self.assertNotIn('preview_world',builder.load(draft.id))
        with self.assertRaises(ValueError):builder.historical_draft_base(draft.id)

    def test_completed_draft_cold_read_is_bound_to_saved_inputs_without_model_calls(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        record=builder.stage_historical(self.snapshot,self.params,construction={'source':'dsh_native_skill'},execution_backend='narrative')
        app=FastAPI();app.include_router(builder.build_router(lambda fn:fn))
        with patch.object(builder.h,'unit_run',side_effect=AssertionError('No model on cold read')):
            reply=TestClient(app).get('/api/historical-scenarios/drafts/'+record['id'])
        self.assertEqual(reply.status_code,200,reply.text);self.assertEqual(reply.json()['parameters'],record['parameters'])
        self.assertEqual(reply.json()['preview_world'],record['preview_world'])
        rows=builder.completed_configurations(self.snapshot,force_scope='campaign')
        self.assertEqual([r['id'] for r in rows],[record['id']]);self.assertEqual(builder.completed_configurations(self.snapshot,force_scope='phase'),[])

    def test_partial_checkpoint_cannot_be_read_as_completed_configuration(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        draft=self.prefix();self.checkpoint(draft)
        app=FastAPI();app.include_router(builder.build_router(lambda fn:fn))
        self.assertEqual(TestClient(app).get('/api/historical-scenarios/drafts/'+draft.id).status_code,422)

    def test_new_native_binding_callback_is_called_before_inflight_operation(self):
        from backend import harness_engine as h
        seen=[];binding={'session_id':'gentactix-unit-scenario-'+'a'*32+'-root'}
        def run(*args,**kwargs):self.assertEqual(seen,[binding['session_id']]);return SimpleNamespace(final_response='{}')
        with patch.object(h,'get_harness'),patch.object(h,'NATIVE_RUNTIME',True),patch.dict(h.RUNTIME_STATUS,connected=True),\
             patch.object(h.runtime_bridge,'control',return_value={'factory':'DSH.AgentRegistry'}),patch.object(h,'_native_control_run',side_effect=run):
            h.unit_run(binding,'QA',h.RunObserver('QA'),namespace='scenario-'+'a'*32,
                on_session=lambda value:seen.append(value['session_id']))

    def test_restore_parent_uses_native_resume_without_prompt_or_new_session(self):
        from backend import harness_engine as h
        sid='gentactix-unit-scenario-'+'a'*32+'-parent';calls=[]
        def control(path,payload):
            calls.append((path,payload))
            if payload['operation']=='inspect':raise RuntimeError('notlive')
            self.assertEqual(payload['operation'],'resume');return {'factory':'DSH.AgentRegistry'}
        with patch.object(h,'get_harness'),patch.object(h,'NATIVE_RUNTIME',True),patch.dict(h.RUNTIME_STATUS,connected=True),\
             patch.object(h.runtime_bridge,'control',side_effect=control),patch.object(h,'_native_control_run') as run:
            result=h.restore_unit_session({'session_id':sid},namespace='scenario-'+'a'*32,role='scenario-builder')
        self.assertEqual(result['session_id'],sid);run.assert_not_called();self.assertEqual(len(calls),2)

    def test_missing_update_after_twenty_actors_resumes_only_remaining_native_parts(self):
        calls=[];interrupt=True;binding_for_failed=None
        def native(binding,prompt,obs,**kwargs):
            nonlocal interrupt,binding_for_failed
            context=kwargs['context'];part=context['scenario_composer']['part'];calls.append(part)
            sid=binding['session_id'] if binding else 'gentactix-unit-'+kwargs['namespace']+'-'+str(len(calls))
            handle={'session_id':sid,'factory':'DSH.AgentRegistry','persistence':'session_journal'}
            if kwargs.get('on_session'):kwargs['on_session'](handle)
            builder.execute_tool(context,{'tool':'read_scenario_skill'})
            view=builder.execute_tool(context,{'tool':'get_scenario_basis'})
            names=['read_scenario_skill','get_scenario_basis']
            if part=='actors:5' and interrupt:
                interrupt=False;binding_for_failed=sid
                obs.runs.append({'id':sid,'session_id':sid,'finish_reason':'completed','events':[{'type':'tool/call','name':n} for n in names]})
                return SimpleNamespace(final_response='<tool_call><function=update_scenario_configuration>{"patch":{}}</function></tool_call>'),handle
            if part=='actors:5':self.assertEqual(sid,binding_for_failed)
            if part=='final':
                result=builder.execute_tool(context,{'tool':'validate_scenario_configuration'});names.append('validate_scenario_configuration')
            else:
                patch_={k:v for k,v in self.params.items() if k not in ('actors','format','phase_id')} if part=='globals' else {'actors':{i:self.params['actors'][i] for i in view['assigned_actor_ids']}}
                result=builder.execute_tool(context,{'tool':'update_scenario_configuration','args':{'revision':view['revision'],'patch':patch_}})
                self.assertTrue(result['updated'],result);names.append('update_scenario_configuration')
            obs.runs.append({'id':sid+':'+part,'session_id':sid,'finish_reason':'completed','events':[{'type':'tool/call','name':n} for n in names]})
            return SimpleNamespace(final_response=json.dumps({k:result[k] for k in ('revision','configuration_hash')})),handle
        with patch.object(builder.h,'unit_run',side_effect=native),patch.object(builder.h,'dispose_unit_sessions'),\
             patch.object(builder.h,'restore_unit_session',side_effect=lambda binding,**kw:binding) as restore_parent:
            with self.assertRaisesRegex(ValueError,'实际工具调用证据') as failed:
                builder.build_historical_staged(self.basis,'QA','narrative',builder.h.RunObserver('first'))
            identity=failed.exception.assembly_id
            from backend import scenario_checkpoints
            checkpoint=scenario_checkpoints.read(identity)
            self.assertEqual(len(checkpoint['state']['filled']),20);self.assertEqual(checkpoint['state']['revision'],6)
            self.assertEqual(checkpoint['work']['failed_part'],'actors:5')
            self.assertEqual(checkpoint['work']['part_bindings']['actors:5'],binding_for_failed)
            calls.clear()
            config,construction=builder.build_historical_staged(checkpoint['state']['basis'],'QA','narrative',
                builder.h.RunObserver('resume'),resume_checkpoint=identity)
        self.assertEqual(calls,['actors:5','actors:6','actors:7','actors:8','final'])
        self.assertEqual(construction['resume']['validated_actors_at_start'],20)
        self.assertEqual(len(config['actors']),34);scenario_constraints.validate(config,self.basis['fixed_parameters'])
        restore_parent.assert_called_once()


if __name__=='__main__':unittest.main()
