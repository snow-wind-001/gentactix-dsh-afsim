"""Offline review of isolated frames and public Native tool envelopes only."""
import json
from pathlib import Path

from gentactix import formation_session,missions
from .sustainment_feedback_live import ROOT,facts,save

CHAIN='chain-instructed'


def public_results():
    results=[]
    for path in (ROOT/'runtime/dsh-home/sessions').glob('*/*/session.v4.jsonl'):
        calls={}
        for line in path.open():
            try:row=json.loads(line)
            except ValueError:continue
            # Never inspect assistant messages or reasoning blocks.
            if row.get('type') not in ('tool/call','tool/result'):continue
            data=row.get('data') or {}
            if row['type']=='tool/call':
                calls[data.get('callId',data.get('id'))]=data.get('name')
                continue
            message=data.get('message') or {}
            identity=message.get('toolCallId') or message.get('source',{}).get('callId')
            for block in message.get('content',[]):
                if block.get('type')!='text':continue
                try:value=json.loads(block['text'])
                except (ValueError,TypeError):continue
                if not isinstance(value,dict):continue
                results.append(dict(session=path.parent.name,call=identity,name=calls.get(identity),
                    result=value))
    return results


def main():
    public=public_results();proofs=[]
    names=['native-1-validated','native-4-validated','chain-1-native',
        CHAIN+'-2-narrative',CHAIN+'-3-afsim',CHAIN+'-4-narrative',CHAIN+'-5-afsim']
    for name in names:
        folder=ROOT/name
        before=json.loads((folder/'before.json').read_text());after=json.loads((folder/'after.json').read_text())
        review=json.loads((folder/'review.json').read_text());result=json.loads((folder/'result.json').read_text())
        assert review['passed'] and facts(before)==review['before'] and facts(after)==review['after']
        formation_session.validate(json.loads(json.dumps(after)))
        assert after['war_state']==result['updated_state']
        assert facts(after)['noncombat']+facts(after)['fraction']==facts(after)['turn']*2
        assert facts(after)['committed']==6000
        assert after['turn_count']==before['turn_count']+1
        assert facts(after)['elapsed_seconds']-facts(before)['elapsed_seconds']==1800
        old={u['name']:u for _,u in missions.units(before['war_state'])}
        for _,unit in missions.units(after['war_state']):
            previous=old[unit['name']]['equipment']
            assert len(unit['equipment'])==len(previous)
            for current,prior in zip(unit['equipment'],previous):
                assert {k:v for k,v in current.items() if k!='calculation_source'}=={k:v for k,v in prior.items() if k!='calculation_source'}
                if current.get('calculation_source')!=prior.get('calculation_source'):
                    assert review['backend']=='afsim' and prior.get('calculation_source') is None
                    assert current['calculation_source']=='combined-arms-teaching-1'
            assert unit['personnel']['casualties']==old[unit['name']]['personnel']['casualties']
        proof=dict(case=name,facts=facts(after),cold_json_validation=True)
        if review['backend']=='afsim':
            evidence=result['external_execution']
            assert evidence['status']=='completed' and evidence['returncode']==0
            assert evidence['legacy_support_revision']==1 and 'dsh_execution' not in after['war_state']
            proof['native_process_id']=evidence['process_id']
        else:
            matches=[r for r in public if r['result'].get('ok') and r['result'].get('operation_id')==review['operation_id']]
            assert {r['name'] for r in matches}>={'preview_turn_effects','submit_turn_report'}
            assert all(r['result']['before_hash']==missions.digest(before['war_state']) for r in matches)
            preview=next(r['result'] for r in matches if r['name']=='preview_turn_effects')
            assert preview['after_hash']==missions.digest(after['war_state'])
            assert 'afsim' not in after['war_state']
            proof.update(operation_id=review['operation_id'],public_source_bound=True,
                public_session=next(r['session'] for r in matches))
        proofs.append(proof)
    chain=json.loads((ROOT/(CHAIN+'-review.json')).read_text());assert chain['passed']
    save('public-frame-review.json',dict(passed=True,frames=proofs,
        public_scope='tool/call and tool/result only; no assistant reasoning',
        history_calibration_proven=False,runtime_admitted=False))
    print('PASS7 real frames, continuity, cold JSON and public Native source binding')


if __name__=='__main__':main()
