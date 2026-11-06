"""Preservation and cold restore evidence for the fire-process validation."""
import argparse
import hashlib
import json
from pathlib import Path

from tools.qa.catalog_expansion_live import call


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--phase',choices=['before','after','close'],required=True)
    args=parser.parse_args()
    if not args.live:parser.error('Use --live against owned isolated API18998')
    root=Path('.cache/qa/fire-process')
    health=call('GET','/api/health');pid=health['build']['pid']
    assert Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[1]==b'.cache/qa/ww2-phases/launch.py'
    if args.phase!='before':assert not health['build']['restart_required']
    current=[]
    for row in call('GET','/api/sessions')['sessions']:
        sid=row['session_id'];progress=call('GET','/api/sessions/'+sid+'/progress')
        assert not progress['active'] and progress['operation_id'] is None,sid
        session=call('GET','/api/sessions/'+sid)
        current.append({'session_id':sid,'world':session['war_state'],'turn':session['turn_count'],
                        'commands':call('GET','/api/sessions/'+sid+'/commands')})
    indexed={row['session_id']:row for row in current}
    assert len(indexed)==len(current)
    original=json.loads(Path('.cache/qa/catalog-expansion/before-cold-restart.json').read_text())
    assert len(original)==65
    assert all(indexed.get(row['session_id'])==row for row in original),'Existing 65 worlds/commands changed'
    protected=[]
    for path in ['.cache/qa/formation-partitions/preservation.json',
                 '.cache/qa/fire-process/profile-files-before.json',
                 '.cache/qa/fire-process/saved-files-before.json']:
        manifest=json.loads(Path(path).read_text())
        for row in manifest:
            assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
        protected.append({'manifest':path,'files':len(manifest)})
    agents=hashlib.sha256(Path('AGENTS.md').read_bytes()).hexdigest()
    assert agents=='7843b4d3d32b423430e97a840e273dc237f8db262b19208a1521e32bb4414be0'
    operations=json.loads(Path('.cache/qa/catalog-expansion/checkpoint-after.json').read_text())['build_operations_inactive']
    for operation in operations:
        assert not call('GET','/api/scenarios/operations/'+operation+'/progress')['active'],operation
    if args.phase=='before':
        (root/'before-cold-restart.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
    else:
        before=json.loads((root/'before-cold-restart.json').read_text())
        assert pid!=json.loads((root/'checkpoint-before.json').read_text())['pid']
        assert indexed=={row['session_id']:row for row in before},'Restored worlds/commands differ'
    summary={'passed':True,'pid':pid,'sessions':len(current),'existing_worlds_unchanged':len(original),
        'protected':protected,'agents_unchanged':True,'build_operations_inactive':operations}
    (root/('checkpoint-'+args.phase+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='build_operations_inactive'},ensure_ascii=False))


if __name__=='__main__':main()
