"""Isolated public22 motion-contract workflows; source and resource priors unchanged."""
import argparse
import json
from pathlib import Path

from . import wanjialing_continuous_live as workflow

ROOT=Path('.cache/qa/movement-feedback-2026-11-02/live22')
workflow.ROOT=ROOT
workflow.api.ROOT=ROOT
workflow.api.PORT=19227


def prepare():
    build=json.loads((ROOT/'build-response.json').read_text())['body']
    afsim=json.loads((ROOT/'builder-result.json').read_text())['session_id']
    workflow.configure(afsim)
    parameters=build['parameters']
    assert parameters['movement_feedback']['version']=='movement-feedback-1'
    assert parameters['campaign_scope']['window']['version']=='1.5.0'
    checked=workflow.api.call('POST','/historical-scenarios/validate',dict(parameters=parameters,
        parent_draft_id=build['id'],execution_backend='narrative'))
    assert checked['parameters']==parameters
    workflow.save('dsh-validation.json',checked)
    created=workflow.api.call('POST','/sessions',dict(scenario='完整22单位运动反馈验收；沿用公开先验，非历史标定。',
        battle=build['initial']['definition']['battle'],time_step='1小时',product_mode='historical',simulation_mode='open',
        execution_backend='narrative',agent_mode='native',historical_parameters=checked['parameters'],
        historical_initial_version=build['initial']['version'],scenario_draft_id=checked['id']))
    sid=created['session_id'];workflow.api.call('POST','/sessions/'+sid+'/init')
    workflow.configure(sid)
    workflow.save('cases.json',dict(afsim=afsim,narrative=sid))
    print('Prepared actual source-bound22 cases',afsim,sid,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('serve','prepare'))
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    if args.mode=='serve':workflow.api.serve()
    else:prepare()


if __name__=='__main__':main()
