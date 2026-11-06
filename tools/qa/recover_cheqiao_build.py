"""Recover pre-checkpoint QA input from successful native tool writes only.

One-off migration for the recorded redCrossed load failure. Does not accept model
final text, failed tool patches, or modify any actor value to make it validate.
"""
import copy
import json
import os
import subprocess
from pathlib import Path
import uuid


def main():
    root=Path('.cache/qa/cheqiao-complete/full');runtime=root/'runtime'
    os.environ['GENTACTIX_SESSION_DIR']=str(runtime.resolve()/'sessions')
    from backend import scenario_builder as b,scenario_assembly
    from gentactix import historical_operations as ho,missions
    battle='抗日战争-车桥战役-1944.03.05至1944.03.06'
    basis=b.historical_basis(battle,'core_march5_6',version='1.1.0',time_step='30分钟')
    accepted=[];validations=[];paths=[]
    for path in (runtime/'dsh-home').glob('sessions/*/*/session.v4.jsonl'):
        calls={};paths.append(str(path))
        for line in path.read_text().splitlines():
            record=json.loads(line);data=record.get('data') or {}
            if record.get('type')=='tool/call':calls[data['callId']]=data
            if record.get('type')!='tool/result':continue
            message=data.get('message') or {};call=calls.get(message.get('toolCallId'),{})
            for block in message.get('content',[]):
                if block.get('type')!='text':continue
                try:value=json.loads(block.get('text',''))
                except ValueError:continue
                if call.get('name')=='update_scenario_configuration' and value.get('updated') is True:
                    args=call['arguments'];args=json.loads(args) if isinstance(args,str) else args
                    # The native Node plugin sends JSON over HTTP. Replay that
                    # serializer too (4.0 becomes 4); strings stay strings.
                    encoded=subprocess.run(['node','-e',
                        'process.stdout.write(JSON.stringify(JSON.parse(require("fs").readFileSync(0,"utf8"))))'],
                        input=json.dumps(args,ensure_ascii=False),text=True,capture_output=True,check=True)
                    args=json.loads(encoded.stdout)
                    patch=args['patch'];patch=json.loads(patch) if isinstance(patch,str) else patch
                    accepted.append((value['revision'],patch,value))
                if call.get('name')=='validate_scenario_configuration' and value.get('valid') is True:
                    validations.append(value)
    assert accepted and validations,'No complete native tool evidence'
    config=copy.deepcopy(basis['configuration_template']);receipts=[]
    for expected,(revision,patch,receipt) in enumerate(sorted(accepted,key=lambda row:row[0]),1):
        assert revision==expected,'Missing or duplicate successful revision'
        config=scenario_assembly._merge_known(config,patch)
        assert missions.digest(config)==receipt['configuration_hash'],'Tool receipt does not match recovered input'
        receipts.append({k:receipt[k] for k in ('revision','configuration_hash','completed_actors','total_actors')})
    final=next(v for v in validations if v.get('scope')=='complete_configuration_and_native_template; not_live_load')
    assert final['configuration_hash']==missions.digest(config)
    ho.initial(basis['initial'],config)
    report={'source':'actual successful DSH tool updates, verified hash at every revision',
        'receipts':receipts,'full_validation':final,'traces':paths,
        'original_failure':'vendor/afsim/local/afsim/workspace/jobs/406ffb85d48446a6bd195e0bcfaa24a4/failure.json'}
    (root/'recovery-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (root/'raw-model-configuration.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    # The production stage already canonicalized display text before its failed
    # native load; repeat that same derived-text operation, never numeric repair.
    config['goal']['description']=b.historical_goal_text(config)
    world=ho.initial(basis['initial'],config)
    saved=b._save_draft({'id':uuid.uuid4().hex,'kind':'historical_configuration',
        'initial':basis['initial'],'parameters':config,
        'construction':{'source':'dsh_native_skill','skill':'historical-unit-configuration',
            'workflow':'native_agent_registry_scoped_drafts',
            'recovery':'hash-verified saved tool writes after native load failure, before checkpoints existed',
            'evidence':report},'parent_id':None,'execution_backend':'afsim',
        'definition_hash':world['mission']['definition_hash'],
        'scope':'validated_inputs_only; recovered from actual trace; cannot_create_session_until_load_succeeds'},world)
    result={'configuration_id':saved['id'],'actors':len(config['actors']),
            'leaves':len(world['red_units'])+len(world['blue_units']),'tool_revisions':len(receipts)}
    (root/'recovered.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
