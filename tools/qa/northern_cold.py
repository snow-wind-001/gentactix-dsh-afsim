"""Snapshot/verify all owned northern QA sessions without advancing or calling DSH."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['snapshot','verify'])
    parser.add_argument('root',type=Path)
    parser.add_argument('label')
    args=parser.parse_args();root=args.root;manifest=json.loads((root/'live-case.json').read_text())
    api=manifest['api'];owned=root.parent/'api'
    def get(path):
        with urllib.request.urlopen(api+'/api'+path,timeout=90)as response:return json.load(response)
    sessions={}
    for row in get('/sessions')['sessions']:
        identity=row['session_id'];progress=get('/sessions/'+identity+'/progress')
        assert not progress['active'],'Never snapshot or restart an active round'
        sessions[identity]=dict(export=get('/sessions/'+identity+'/export'),progress=progress)
    raw={}
    paths=[p for p in owned.rglob('*')if p.is_file()and not p.is_symlink()]
    paths += [Path(p)for p in json.loads((root/'owned-launch-paths.json').read_text()).values()]
    for path in paths:
        stat=path.stat();raw[str(path.resolve())]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),mtime_ns=stat.st_mtime_ns,bytes=stat.st_size)
    value=dict(sessions=sessions,raw_files=raw)
    path=root/(args.label+'-before.json')
    if args.action=='snapshot':
        if path.exists():raise ValueError('Preserve earlier cold evidence')
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        print('Snapshot',len(sessions),'complete typed sessions and',len(raw),'raw files');return
    previous=json.loads(path.read_text())
    assert wire(previous)==wire(value),'Whole typed exports/progress/raw files must remain exact'
    health=get('/health');assert not health['build']['restart_required']
    target=root/(args.label+'-review.json')
    if target.exists():raise ValueError('Preserve earlier review')
    target.write_text(json.dumps(dict(passed=True,sessions={k:v['export']['session']['turn_count']for k,v in sessions.items()},
        raw_files=len(raw),whole_types_trajectory_commands_sdk_bindings_exact=True,raw_sha_mtime_exact=True,
        operation_terminal_exact=True,build=health['build'],new_model_or_physical_calls=0),ensure_ascii=False,indent=2)+'\n')
    print('PASS whole typed cold restore',len(sessions),'sessions;',len(raw),'raw files')


if __name__=='__main__':main()
