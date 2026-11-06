"""Review actual frontend request, Native conflict receipts and load evidence."""
import json
from pathlib import Path


def main():
    root=Path('.cache/qa/fixed-parameters-2026-11-01')
    data=json.loads((root/'browser-build.json').read_text())
    assert data['status']=='finished' and data['http']==200
    request,body=data['request'],data['body']
    fixed=request['fixed_parameters']
    assert len(fixed)==23 and fixed==body['construction']['fixed_parameters']['values']
    mismatches=[]
    for row in fixed:
        value=body['parameters']
        for key in row['path']:value=value[key]
        if value!=row['value']:mismatches.append(row['path'])
    assert not mismatches,mismatches
    results=[]
    for path in (root/'browser').glob('dsh-home/sessions/**/session.v4.jsonl'):
        names={}
        for line in path.read_text().splitlines():
            event=json.loads(line);payload=event.get('data',{})
            if event['type']=='tool/call':names[payload['callId']]=payload['name']
            if event['type']!='tool/result':continue
            message=payload['message']
            for block in message.get('content',[]):
                if block.get('type')!='text':continue
                try:response=json.loads(block['text'])
                except (ValueError,TypeError):continue
                if isinstance(response,dict) and 'updated' in response:
                    results.append({'tool':names.get(message['toolCallId']),**{k:response[k] for k in
                        ('updated','revision','fixed_parameter_conflicts','configuration_hash','error') if k in response}})
    results.sort(key=lambda r:(r['revision'],r['updated']))
    conflicts=[r for r in results if not r['updated'] and r.get('fixed_parameter_conflicts')]
    assert conflicts and conflicts[0]['revision']==0
    assert conflicts[0]['fixed_parameter_conflicts']==[{'path':['supply_schedule','passive_work_per_hour'],'expected':4,'actual':1}]
    assert sorted(r['revision'] for r in results if r['updated'])==[1,2]
    assert len(body['construction']['stages'])==3
    assert body['afsim']['entity_count']==3 and body['afsim']['returncode']==0
    assert body['preview_world']['mission']['turn']==body['preview_world']['simulation_clock']['elapsed_seconds']==0
    result={'passed':True,'actual_model':True,'actual_frontend':True,'actual_afsim_load':True,
            'fixed_fields':len(fixed),'fixed_numeric_mismatches':mismatches,'deliberate_conflicts':len(conflicts),
            'other_rejected_updates':sum(not r['updated'] and not r.get('fixed_parameter_conflicts') for r in results),
            'rejected_revision':0,'accepted_revisions':[1,2],'stages':3,
            'meta':body['construction']['meta'],'public_update_receipts':results,
            'scope':'Three historical identities with23explicit QA priors. Native conflict/recovery and initial load; not historical deployment/loss calibration or arbitrary NLP adherence.'}
    (root/'actual-native-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('meta','public_update_receipts')},ensure_ascii=False))


if __name__=='__main__':main()
