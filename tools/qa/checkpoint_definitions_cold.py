"""Snapshot/verify isolated complete product exports across an owned restart."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path('.cache/qa/checkpoint-definitions-2026-11-03')


def wire(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def get(api,path):
    with urllib.request.urlopen(api+path,timeout=90) as response:return json.load(response)


def save(path,value):
    if path.exists():raise ValueError('Preserve earlier evidence: '+str(path))
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['snapshot','verify'])
    parser.add_argument('side',choices=['source','target'])
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required for owned QA API')
    info=json.loads((ROOT/'case.json').read_text());sid=info['session_id'];api=info[args.side+'_api']
    path=ROOT/(args.side+'-api/sessions')/(sid+'.json')
    stem=args.side+'-cold';before=ROOT/(stem+'-before.json')
    progress=get(api,'/api/sessions/'+sid+'/progress');assert not progress['active']
    session=get(api,'/api/sessions/'+sid+'/export')['session']
    value=dict(session=session,progress=progress,file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
               file_mtime_ns=path.stat().st_mtime_ns,file_format=json.loads(path.read_text())['format'])
    if args.mode=='snapshot':
        save(before,value);print('Snapshot whole isolated',args.side,sid,'T',session['turn_count'],flush=True);return
    previous=json.loads(before.read_text())
    assert wire(previous['session'])==wire(value['session'])
    assert wire(previous['progress'])==wire(progress)
    for field in ['file_sha256','file_mtime_ns','file_format']:assert previous[field]==value[field]
    from backend import afsim_state,checkpoint_codec,session_store
    stored=checkpoint_codec.decode(json.loads(path.read_text()))
    assert wire(stored)==wire(session_store.serializable(session))
    units=[];offset=0
    while True:
        observation=afsim_state.observation(session,dict(offset=offset,limit=16,detail=True))
        units+=observation['units'];offset=observation['next_offset']
        if offset is None:break
    assert len(units)==22
    save(ROOT/(stem+'-review.json'),dict(passed=True,side=args.side,session_id=sid,turn=session['turn_count'],
        whole_typed_session_exact=True,complete_history_retained=True,all22_details_available=True,
        whole_public_trajectory_and_native_proofs_exact=True,native_bindings_exact=True,
        progress_and_terminal_exact=True,file_bytes_and_mtime_unchanged=True,file_format=value['file_format'],
        new_model_call_after_cold=False,physical_turn_after_cold=False))
    print('PASS complete typed',args.side,'cold restore, all22 details; no new model',flush=True)


if __name__=='__main__':main()
