"""Read-only evidence checks; revalidate old accepted writes, never model text."""
import copy,json
from pathlib import Path
from backend import scenario_assembly as assembly
from gentactix import missions,scenario_constraints

root=Path('.cache/qa/scenario-resume-2026-11-01');old=Path('.cache/qa/scenario-admission-2026-11-01')
seed=json.loads((root/'seed-review.json').read_text());identity=seed['assembly_id']
checkpoint=json.loads((old/'browser/scenario-drafts'/(identity+'.json')).read_text())
rebuild=json.loads((root/'rebuild-model-response.json').read_text());upgraded=json.loads((root/'delay-validation-response.json').read_text());checks=[]
def check(value,label):
 if not value:raise AssertionError(label)
 checks.append(label)
accepted=[]
for entry in seed['journals_read_only']:
 path=next((old/'browser/dsh-home/sessions').rglob(entry['session_id']+'/session.v4.jsonl'));calls={}
 for line in path.open():
  row=json.loads(line);data=row.get('data',{})
  if row['type']=='tool/call':calls[data['callId']]=data
  if row['type']!='tool/result':continue
  msg=data['message'];call=calls.get(msg.get('toolCallId'))
  if not call or call['name']!='update_scenario_configuration':continue
  for block in msg['content']:
   if block.get('type')!='text':continue
   result=json.loads(block['text'])
   if result.get('updated') and result['revision']<=6:
    args=call['arguments'];args=json.loads(args) if isinstance(args,str) else args
    accepted.append((result['revision'],entry['part'],args,result))
draft=assembly.create(checkpoint['state']['basis'])
try:
 for rev,part,args,old_receipt in sorted(accepted):
  receipt=draft.tool(part,'update_scenario_configuration',args)
  check(receipt.get('updated') and receipt['revision']==rev and receipt['configuration_hash']==old_receipt['configuration_hash'],'original accepted Native hash reproduced revision'+str(rev))
 check(len(draft.filled)==20,'original20validatedactorsreconstructed')
 for result in (rebuild,upgraded):
  check(result['http']==200,'actualresponse200')
  p=result['body']['parameters'];check(all(p['actors'][i]==draft.configuration['actors'][i] for i in draft.filled),'all20originalactorvaluesunchanged')
  scenario_constraints.validate(p,result['body']['construction']['fixed_parameters'])
  check(p['aviation']['ww2.jp.flight29']['initial']=={'committed':4,'ordnance':8,'fuel':16},'all3fixedairinputsunchanged')
  check(result['body']['afsim']['returncode']==0 and result['body']['afsim']['entity_count']==34,'actualNative34load')
finally:assembly.close(draft.id)
before=json.loads((root/'pre-turn-response.json').read_text());after=json.loads((root/'post-turn-response.json').read_text());cold=json.loads((root/'cold-restored-response.json').read_text())
check(after['war_state']==cold['war_state'],'entireworldequalafternewbackendcoldrestore')
index=lambda w:{u['historical_unit_id']:u for _,u in missions.units(w)}
a=index(before['war_state']);b=index(after['war_state']);check(set(a)==set(b) and len(b)==34,'all34sourceidentitiescontinuous')
for identity,u in b.items():
 p=u['personnel'];check(p['committed']==a[identity]['personnel']['committed'] and p['committed']==p['current']+p['casualties']+p['noncombat_losses'],'personnelaccount:'+identity)
 check(all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment']),'equipmentaccount:'+identity)
check(after['war_state']['simulation_clock']['elapsed_seconds']==21600,'exact6hclock')
check(after['war_state']['historical_initial']==before['war_state']['historical_initial'],'frozenhistoryunchanged')
report={'passed':True,'checks':checks,'check_count':len(checks),'historical_process_accepted':False,
 'scope':'Old20host-revalidated Native patches +new14realmodel; explicit policy edit, actual34unit hold/coldrestore. Not independent full generation.'}
(root/'evidence-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('PASS',len(checks),'evidence/account checks')
