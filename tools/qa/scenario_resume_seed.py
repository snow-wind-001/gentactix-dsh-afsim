"""Explicit QA revalidation import of accepted old Native tool writes only.

This is not retroactive production persistence. Failed final parameter text is
never consumed; each original accepted patch must reproduce its original hash.
Native session journals are read, never modified.
"""
import copy
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'.cache/qa/scenario-admission-2026-11-01'
OUT=ROOT/'.cache/qa/scenario-resume-2026-11-01'
os.environ['GENTACTIX_SESSION_DIR']=str(OLD/'browser/sessions')
from backend import scenario_builder as b,scenario_assembly as a,scenario_checkpoints as c
from gentactix import scenario_constraints,missions


def main():
    request=json.loads((OLD/'retry-model-response.json').read_text())['request']
    audits=json.loads((OLD/'retry-terminal-native-audit.json').read_text())
    identity=audits[0]['session_id'].split('-scenario-')[1].split('-')[0]
    if (b.directory()/(identity+'.json')).exists():raise ValueError('Refuse replacing an existing checkpoint')
    basis=b.historical_basis(request['battle'],request['phase_id'],version=request.get('version'),
        time_step=request['time_step'],termination_mode=request['termination_mode'],force_scope=request['force_scope'])
    a.prepare_required_models(basis,request['required_models']);scenario_constraints.prepare(basis,request['fixed_parameters'])
    draft=a.create(basis);state=draft.export_state();a.close(draft.id);state['id']=identity;draft=a.restore(state)
    work=c.new_work(request['instruction'],request['execution_backend']);evidence=[];accepted=[]
    for audit in audits:
        sid=audit['session_id'];part=audit['parts'][0]
        work['bindings'][sid]={'session_id':sid,'factory':'DSH.AgentRegistry','persistence':'session_journal'}
        work['part_bindings'][part]=sid
        if part=='globals':work['coordinator']=sid
        file=next((OLD/'browser/dsh-home/sessions').rglob(sid+'/session.v4.jsonl'))
        calls={};receipt=None;final=None;events=[]
        for line in file.open():
            row=json.loads(line);data=row.get('data',{})
            if row['type']=='tool/call':
                calls[data['callId']]=data;events.append({'type':'tool/call','name':data['name'],'seq':row['seq']})
            elif row['type']=='tool/result':
                message=data['message'];call=calls.get(message.get('toolCallId'))
                if not call or call['name']!='update_scenario_configuration':continue
                result=json.loads(''.join(x['text'] for x in message['content'] if x['type']=='text'))
                if result.get('updated'):
                    arguments=call['arguments'];arguments=json.loads(arguments) if isinstance(arguments,str) else arguments
                    accepted.append((result['revision'],part,arguments,result))
                    receipt=result
            elif row['type']=='assistant/message':
                text=''.join(x['text'] for x in data['message']['content'] if x['type']=='text')
                try:final=json.loads(text)
                except ValueError:pass
        runid='qa-old-native:'+sid
        work['runs'].append({'id':runid,'session_id':sid,'finish_reason':'completed','events':events,'evidence':'old_native_journal_revalidated_for_QA'})
        if receipt:
            if not isinstance(final,dict) or any(final.get(k)!=receipt[k] for k in ('revision','configuration_hash')):
                raise ValueError('Accepted old stage lacks its completed Native receipt')
            work['stages'].append({'part':part,'session_id':sid,'parent_session_id':None,
                **{k:receipt[k] for k in ('revision','configuration_hash','completed_actors','total_actors','global_ready','status')},
                'run_ids':[runid],'recovery_of':None,'restored_validated_write':False})
            if final.get('explanation'):work['explanations'].append(final['explanation'][:1200])
        evidence.append({'session_id':sid,'part':part,'journal_hash':missions.digest(file.read_text()),
            'accepted_revision':receipt['revision'] if receipt else None})
    for revision,part,arguments,old in sorted(accepted):
        result=draft.tool(part,'update_scenario_configuration',arguments)
        if not result.get('updated') or any(result[k]!=old[k] for k in ('revision','configuration_hash')):
            raise ValueError('Old accepted patch no longer validates identically: '+str(revision))
    work['stages'].sort(key=lambda r:r['revision'])
    if len(draft.filled)!=20 or draft.revision!=6:raise ValueError('Expected exactly20hostvalidated actors')
    work.update(status='interrupted',failed_part='actors:5',last_error='QA重验导入：旧原生工具曾通过20/34单位；非当时生产检查点，不接纳失败参数文本。')
    record=c.save(draft,work);a.close(draft.id)
    restored,checked=c.restore(draft.id);a.close(draft.id)
    report={'scope':'QA-only revalidation import; not retroactive production persistence or independent full generation',
        'assembly_id':identity,'host_summary':c.summary(record),'journals_read_only':evidence,
        'accepted_hashes_reproduced':6,'failed_final_text_consumed':False,'native_resume_not_yet_run':True}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'seed-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'assembly_id':identity,'validated_actors':20,'reproduced_original_hashes':6,'scope':report['scope']}))


if __name__=='__main__':main()
