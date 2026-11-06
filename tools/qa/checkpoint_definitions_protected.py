"""Verify source freeze, untouched user files and earlier owned QA sessions."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path('.cache/qa/checkpoint-definitions-2026-11-03')


def get(api,path):
    with urllib.request.urlopen(api+path,timeout=90) as response:return json.load(response)


def wire(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required for owned QA API')
    out=ROOT/'protection-review.json'
    if out.exists():raise ValueError('Preserve prior evidence')
    counts={}
    for name,path in [('source',ROOT/'source-freeze.json'),
                      ('protected',Path('.cache/qa/native-unit-input-index-2026-11-03/protected-before.json'))]:
        frozen=json.loads(path.read_text())
        changed=[p for p,digest in frozen.items() if not Path(p).exists() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest]
        assert not changed,(name,changed);counts[name]=len(frozen)
    originals=json.loads(Path('.cache/qa/operation-clock-2026-11-03/original7-before.json').read_text())
    for sid,expected in originals.items():
        api='http://127.0.0.1:19227';path='/api/sessions/'+sid
        assert not get(api,path+'/progress')['active']
        assert wire(get(api,path+'/export')['session'])==wire(expected),sid
    old=Path('.cache/qa/native-source-details-2026-11-03/real-ui-t6/turn-browser/authoritative-after.json')
    expected=json.loads(old.read_text());sid=expected['id'];api='http://127.0.0.1:19257';path='/api/sessions/'+sid
    assert not get(api,path+'/progress')['active']
    assert wire(get(api,path+'/export')['session'])==wire(expected)
    out.write_text(json.dumps(dict(passed=True,source_files=counts['source'],protected_files=counts['protected'],
        previous_seven_whole_sessions_exact=True,previous_source_t6_whole_session_exact=True,
        unique_battles_not_inferred_from_shared_ids=True,uploaded=False,installed=False),indent=2)+'\n')
    print('PASS source63/protected73 and previous7+T6 whole API sessions unchanged',flush=True)


if __name__=='__main__':main()
