"""Isolated real HTTP/Native final-output recovery and explicit fault injection.

The optional fault removes the closing object delimiter only after an actual
model produced a valid public reply. Model calls, preview tools, host validation,
and normal command commits remain real. Fault evidence is labelled separately
from spontaneous failures. No user configuration or user games are changed.
"""
import argparse
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path

from tools.qa import unit_participation_live as workflow

ROOT=Path('.cache/qa/dsh-output-recovery-2026-11-01/live')
PORT=19122
workflow.ROOT=ROOT;workflow.PORT=PORT;workflow.workflow.PORT=PORT
call=workflow.call


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def serve():
    folder=(ROOT/'http').resolve();folder.mkdir(parents=True,exist_ok=True)
    for name,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                        ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+name]=str(folder/suffix)
    from backend import main,harness_engine as h,runtime_bridge,turn_preview
    from fastapi import HTTPException
    from gentactix import missions
    import uvicorn
    active=ContextVar('qa_public_output_context',default=None)
    armed=set();native_armed=set();boundaries={}
    records={p.stem:json.loads(p.read_text()) for p in (ROOT/'faults').glob('*.json')}
    original_get=h.get_ai_response;original_parse=h.parse_json_object
    original_brain=h._run_brain

    def brain(prompt,*args,**kwargs):
        result=original_brain(prompt,*args,**kwargs)
        context=kwargs.get('native_context');observer=kwargs.get('observer')
        if context and context.get('turn_preview') and observer:
            sid=context['session']['id']
            if sid in native_armed and turn_preview.submitted_report(observer,context):
                native_armed.remove(sid)
                from types import SimpleNamespace
                evidence=dict(session_id=sid,operation_id=observer.operation_id,injected=True,
                    kind='qa_corrupt_free_final_after_native_report',actual_model=True,actual_afsim=False,
                    report_candidate_unchanged=True,public_characters=len(result.final_response))
                records.setdefault(sid,[]).append(evidence);save(ROOT/'faults'/(sid+'.json'),records[sid])
                observer.runs[-1]['qa_final_text_fault']=evidence['kind']
                return SimpleNamespace(final_response='{"report":"QA final deliberately incomplete',
                    finish_reason=result.finish_reason,events=result.events,session_id=result.session_id)
        return result

    def get(prompt,*args,**kwargs):
        context=kwargs.get('native_context')
        token=active.set((context,kwargs.get('observer')) if context and context.get('turn_preview') else None)
        try:return original_get(prompt,*args,**kwargs)
        finally:active.reset(token)

    def parse(raw):
        item=active.get()
        if not item:return original_parse(raw)
        context,observer=item;sid=context['session']['id']
        if sid not in armed:return original_parse(raw)
        armed.remove(sid)
        evidence=dict(session_id=sid,operation_id=observer.operation_id,
            before_hash=missions.digest(context['session']['war_state']),
            injected=False,actual_model=True,actual_afsim=False,public_characters=len(raw))
        try:original_parse(raw)
        except h.JSONOutputError:
            evidence['natural_invalid_json']=True
            records.setdefault(sid,[]).append(evidence);save(ROOT/'faults'/(sid+'.json'),records[sid])
            raise
        cut=raw.rfind('}');truncated=raw[:cut]
        evidence.update(injected=True,kind='qa_remove_final_object_delimiter',
            original_sha256=hashlib.sha256(raw.encode()).hexdigest(),injected_characters=len(truncated))
        records.setdefault(sid,[]).append(evidence);save(ROOT/'faults'/(sid+'.json'),records[sid])
        # The actual public Native journal retains the original valid message;
        # this explicit QA record identifies the application-boundary mutation.
        return original_parse(truncated)

    h.get_ai_response=get;h.parse_json_object=parse;h._run_brain=brain

    def dispatch(context,payload):
        reply=main._native_tool_dispatch(context,payload)
        if payload.get('tool') in ('preview_turn_effects','submit_turn_report') and reply.get('ok'):
            sid=context['session']['id']
            boundaries[sid]=dict(tool=payload['tool'],operation_id=reply['operation_id'],readonly=reply['readonly'],
                digest=reply.get('digest'),report_digest=reply.get('report_digest'))
            save(ROOT/'native-boundaries'/(sid+'.json'),boundaries[sid])
        return reply
    runtime_bridge.register_dispatcher(dispatch)

    @main.app.get('/qa/native-boundary/{sid}')
    def boundary(sid:str):
        main._get(sid)
        return dict(readonly=True,marker=boundaries.get(sid))

    @main.app.post('/qa/native-final-fault/{sid}')
    def arm_native(sid:str):
        session=main._get(sid)
        if session.get('execution_backend','narrative')!='narrative' or session.get('progress'):
            raise HTTPException(409,'Only an idle DSH QA process can be armed')
        native_armed.add(sid)
        return dict(armed=True,injected=False,scope='Corrupt only the final text after a genuine completed Native report submission')

    @main.app.post('/qa/final-output-fault/{sid}')
    def arm(sid:str):
        session=main._get(sid)
        if session.get('execution_backend','narrative')!='narrative' or session.get('product_mode')!='historical':
            raise HTTPException(422,'Only isolated DSH historical QA cases can be armed')
        if session.get('progress') or sid in armed:raise HTTPException(409,'Case already active or armed')
        armed.add(sid)
        return dict(armed=True,injected=False,scope='Explicit QA fault; the next actual public final is truncated before parsing')

    @main.app.get('/qa/final-output-fault/{sid}')
    def inspect(sid:str):
        main._get(sid)
        return dict(armed=sid in armed,attempts=records.get(sid,[]))

    try:uvicorn.run(main.app,host='127.0.0.1',port=PORT,log_level='warning')
    finally:h.close_harness()


def cold(verify=False):
    expected=ROOT/'cold-expected.json';rows={}
    for entry in call('GET','/sessions')['sessions']:
        sid=entry['session_id'];base='/sessions/'+sid
        assert not call('GET',base+'/progress')['active'],'Do not restart an active operation'
        snapshot=call('GET',base)
        rows[sid]=dict(turn=snapshot['turn_count'],world=snapshot['war_state'],history=snapshot['history'],
            commands=call('GET',base+'/commands'),tasks=call('GET',base+'/force-organization/tasks'))
    if verify:
        assert rows==json.loads(expected.read_text()),'Cold restoration changed a committed world, order, report or task'
        save(ROOT/'cold-result.json',dict(passed=True,case_count=len(rows),turns={s:r['turn'] for s,r in rows.items()}))
        print('PASS cold restore',len(rows),'isolated cases')
    else:
        if expected.exists():raise RuntimeError('Preserve existing evidence; choose a new QA run')
        save(expected,rows);print('Saved',len(rows),'idle checkpoints')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['serve','create','prepare-cold','cold'])
    parser.add_argument('--engine',choices=['narrative','afsim'],default='narrative')
    parser.add_argument('--tag',default='ui-recovery');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if args.mode=='serve':serve()
    elif args.mode=='create':
        if not args.live:parser.error('Actual model/engine initialization requires --live')
        workflow.create(args.engine,tag=args.tag,combat=False)
    else:cold(args.mode=='cold')
