"""Read-only cold-restore and original-file preservation proof for this slice."""
import argparse
import hashlib
import json
from pathlib import Path

from tools.qa.catalog_expansion_live import call


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--phase',choices=['before','after'],required=True)
    args=p.parse_args()
    if not args.live:p.error('Use --live against owned isolated API18998')
    root=Path('.cache/qa/catalog-expansion')
    health=call('GET','/api/health');pid=health['build']['pid']
    assert not health['build']['restart_required']
    assert Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[1]==b'.cache/qa/ww2-phases/launch.py'
    current=[]
    for r in call('GET','/api/sessions')['sessions']:
        sid=r['session_id'];progress=call('GET','/api/sessions/'+sid+'/progress')
        assert not progress['active'] and progress['operation_id'] is None,sid
        s=call('GET','/api/sessions/'+sid)
        current.append({'session_id':sid,'world':s['war_state'],'turn':s['turn_count'],
                        'commands':call('GET','/api/sessions/'+sid+'/commands')})
    indexed={r['session_id']:r for r in current}
    assert len(indexed)==len(current),'Duplicate session identities'
    original=json.loads(Path('.cache/qa/ferry-model/before-cold-restart.json').read_text())
    assert len(original)==47
    assert all(indexed.get(r['session_id'])==r for r in original),'Original 47 QA worlds or commands changed'
    protected=[]
    for name in ['.cache/qa/formation-partitions/preservation.json',
                 '.cache/qa/catalog-expansion/existing-profiles-preserved.json',
                 '.cache/qa/catalog-expansion/saved-files-before.json']:
        rows=json.loads(Path(name).read_text())
        for r in rows:
            assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'],r['path']
        protected.append({'manifest':name,'files':len(rows)})
    agents=hashlib.sha256(Path('AGENTS.md').read_bytes()).hexdigest()
    assert agents=='7843b4d3d32b423430e97a840e273dc237f8db262b19208a1521e32bb4414be0'
    operations=set(json.loads(Path('.cache/qa/ferry-model/checkpoint-after.json').read_text())['build_operations_inactive'])
    operations.update(json.loads((root/'operations.json').read_text()))
    operations.add(json.loads((root/'builder-followup/validation-request.json').read_text())['operation_id'])
    operations.update(r['operation_id'] for r in json.loads((root/'window-live-preflight.json').read_text())['checks'])
    for op in operations:assert not call('GET','/api/scenarios/operations/'+op+'/progress')['active'],op
    if args.phase=='before':
        (root/'before-cold-restart.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
    else:
        previous=json.loads((root/'checkpoint-before.json').read_text())
        assert pid!=previous['pid'],'Cold restore must use a different process'
        before=json.loads((root/'before-cold-restart.json').read_text())
        before_index={r['session_id']:r for r in before}
        assert len(before_index)==len(before),'Duplicate baseline identities'
        assert indexed==before_index,'Cold worlds/commands differ'
    summary={'passed':True,'pid':pid,'sessions':len(current),'original_qa_worlds_unchanged':len(original),
        'protected':protected,'agents_sha256':agents,'build_operations_inactive':sorted(operations)}
    if args.phase=='after':
        summary['listing_order_changed']=[r['session_id'] for r in current]!=[r['session_id'] for r in before]
    (root/('checkpoint-'+args.phase+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['agents_sha256','build_operations_inactive']},ensure_ascii=False))


if __name__=='__main__':main()
