"""Exact world/command and original-file preservation around owned QA restarts."""
import argparse
import hashlib
import json
from pathlib import Path

from tools.qa.catalog_expansion_live import call


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--phase',choices=['restart','before','after','close'],required=True);args=p.parse_args()
    if not args.live:p.error('Use --live against owned isolated API18998')
    root=Path('.cache/qa/noncontact');health=call('GET','/api/health');pid=health['build']['pid']
    assert Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[1]==b'.cache/qa/ww2-phases/launch.py'
    if args.phase not in ('restart','before'):assert not health['build']['restart_required']
    current=[]
    for row in call('GET','/api/sessions')['sessions']:
        sid=row['session_id'];progress=call('GET','/api/sessions/'+sid+'/progress')
        assert not progress['active'] and progress['operation_id'] is None,sid
        session=call('GET','/api/sessions/'+sid)
        current.append({'session_id':sid,'world':session['war_state'],'turn':session['turn_count'],
                        'commands':call('GET','/api/sessions/'+sid+'/commands')})
    index={r['session_id']:r for r in current}
    original=json.loads(Path('.cache/qa/fire-process/before-cold-restart.json').read_text())
    assert len(original)==69
    assert all(index.get(r['session_id'])==r for r in original),'Existing 69 worlds/commands changed'
    preserved=[]
    for name in ['.cache/qa/formation-partitions/preservation.json',
                 '.cache/qa/noncontact/profile-files-before.json','.cache/qa/noncontact/saved-files-before.json']:
        rows=json.loads(Path(name).read_text())
        for r in rows:assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'],r['path']
        preserved.append({'manifest':name,'files':len(rows)})
    assert hashlib.sha256(Path('AGENTS.md').read_bytes()).hexdigest()=='7843b4d3d32b423430e97a840e273dc237f8db262b19208a1521e32bb4414be0'
    operations=set(json.loads(Path('.cache/qa/catalog-expansion/checkpoint-after.json').read_text())['build_operations_inactive'])
    for path in root.rglob('*-operation.json'):operations.add(json.loads(path.read_text())['operation_id'])
    if (root/'browser-operations.json').exists():operations.update(json.loads((root/'browser-operations.json').read_text()))
    for operation in operations:assert not call('GET','/api/scenarios/operations/'+operation+'/progress')['active'],operation
    if args.phase=='before':
        (root/'before-cold-restart.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
    elif args.phase in ('after','close'):
        baseline=json.loads((root/'before-cold-restart.json').read_text())
        assert index=={r['session_id']:r for r in baseline}
        assert pid!=json.loads((root/'checkpoint-before.json').read_text())['pid']
    result={'passed':True,'pid':pid,'sessions':len(current),'original_worlds_unchanged':69,
        'protected':preserved,'agents_unchanged':True,'build_operations_inactive':sorted(operations)}
    (root/('checkpoint-'+args.phase+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='build_operations_inactive'},ensure_ascii=False))


if __name__=='__main__':main()
