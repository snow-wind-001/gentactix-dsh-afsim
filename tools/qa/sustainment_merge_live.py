"""Opt-in real Native turn after merging the completed damaged QA chain."""
import argparse
import copy
import json

from gentactix import formation_conversion,formation_session
from . import formation_execution_live as base
from .sustainment_feedback_live import ROOT,execute,facts,save


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Explicit --live required')
    source=ROOT/'chain-instructed-5-afsim/after.json'
    session=json.loads(source.read_text());formation_session.validate(session);before=copy.deepcopy(session)
    assert facts(session)['noncombat']==10 and facts(session)['fraction']==0
    proposal=formation_conversion.merge_current(session['war_state']['red_units'],
        assumption='软件QA：同地互斥分队有损合并，不是历史编制命令',operation_id='e'*32)
    prepared=formation_session.prepare(session,proposal,team='red')['session']
    assert session==before and facts(prepared)=={**facts(session),'units':1}
    save('merge-before-native.json',prepared);base.ROOT=ROOT;base.boot()
    from backend import harness_engine
    try:
        after=execute(prepared,'afsim','chain-merged-6-afsim');row=facts(after)
        assert row==dict(turn=6,elapsed_seconds=10800,units=1,committed=6000,current=5988,noncombat=12,fraction=0),row
        assert json.loads(source.read_text())==before
        save('merge-review.json',dict(passed=True,before=facts(session),after=row,
            source_unchanged=True,cold_json_validation=True,runtime_admitted=False,
            scope='Actual Native after split/DSH/Native and damaged merge; not public commit or historical calibration'))
        print('PASS actual damaged merge then Native T6; original6000 and cumulative12 preserved',flush=True)
    finally:harness_engine.close_harness()


if __name__=='__main__':main()
