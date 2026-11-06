"""Real AFSIM source-frame acceptance; never uses model responses or combat rules."""
import json
import argparse
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--all-frames', action='store_true', help='Verify every source frame in all catalog entries')
args = parser.parse_args()
out = ROOT / '.cache/qa/history-replay' / str(time.time_ns())
out.mkdir(parents=True)
for key, suffix in (('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('TRACE_DIR','traces'),('ROLE_INDEX','roles.json')):
    os.environ['GENTACTIX_' + key] = str(out / suffix)
os.environ['GENTACTIX_DSH_PATCHES'] = '[]'
from backend import afsim_history, harness_engine as h
from gentactix import adjudication_lib, history_replay, missions

results = []
with (patch.object(h, 'get_ai_response', side_effect=AssertionError('Model used')),
     patch.object(h, 'get_ai_response_with_retry', side_effect=AssertionError('Model used')),
     patch.object(missions, 'advance', side_effect=AssertionError('Teaching combat used'))):
    for battle in adjudication_lib.list_battles():
        session = {'battle_choice': battle, 'war_state': None, 'source_replay_snapshot':history_replay.pin(battle)}
        # All catalog initial frames plus one complete multi-frame replay.
        count = len(session['source_replay_snapshot']['pack']['events']) if args.all_frames or '湘江战役' in battle else 1
        try:
            for cursor in range(count):
                world = afsim_history.execute(session, cursor)
                history_replay.validate(world)
                session['war_state'] = json.loads(json.dumps(world, ensure_ascii=False))
                assert world['history_replay']['cursor'] == cursor
                assert world['afsim']['combat_entity_count'] == 0
                assert world['afsim']['battlefield_initialized'] is False
            result = {'battle': battle, 'passed': True, 'frames': count,
                      'process_id': world['afsim']['process_id'], 'source': world['afsim']['source']}
        except Exception as exc:
            result = {'battle': battle, 'passed': False, 'error': str(exc)}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        (out / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print('Evidence:', out)
raise SystemExit(any(not r['passed'] for r in results))
