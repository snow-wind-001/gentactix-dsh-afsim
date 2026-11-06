"""Audit a terminal real UI retry using public exports, not private SDK journals."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from backend import dsh_simulation, unit_order_submission as proposal
from gentactix import commands, missions, observation_codec


def audit(root, *, authoritative_before=None, authoritative_after=None):
    browser_before = json.loads((root/'before.json').read_text())
    browser_after = json.loads((root/'after.json').read_text())
    # JS export formatting maps 2.0 to 2. Do not change the world's exact hash
    # rules to accommodate a browser artifact: use original Python exports.
    before = json.loads(authoritative_before.read_text()) if authoritative_before else browser_before
    after = json.loads(authoritative_after.read_text()) if authoritative_after else browser_after
    for browser, original in ((browser_before, before), (browser_after, after)):
        assert browser['war_state'] == original['war_state']
        assert browser['command_state'] == original['command_state']
        assert browser['turn_count'] == original['turn_count']
    result = json.loads((root/'result.json').read_text())
    if not result['passed']:
        raise ValueError('The real operation was not accepted; preserve the failure')
    old = before['war_state']; new = after['war_state']
    assert after['turn_count'] == before['turn_count']+1
    assert old['mission']['definition'] == new['mission']['definition']
    assert new['simulation_clock']['elapsed_seconds']-old['simulation_clock']['elapsed_seconds'] == 3600
    index = lambda world: {u['historical_unit_id']: u for _, u in missions.units(world)}
    original = index(old); current = index(new)
    assert len(current) == 22 and current.keys() == original.keys()
    for identity, unit in current.items():
        prior = original[identity]; p = unit['personnel']; previous = prior['personnel']
        assert p['committed'] == previous['committed'] == p['current']+p['casualties']+p['noncombat_losses']
        assert p['casualties'] >= previous['casualties'] and p['noncombat_losses'] >= previous['noncombat_losses']
        assert p.get('source') == previous.get('source')
        assert unit.get('source') == prior.get('source')
        for item, former in zip(unit['equipment'], prior['equipment']):
            assert item['category'] == former['category']
            assert item['committed'] == former['committed'] == item['operational']+item['damaged']+item['destroyed']
            assert item['destroyed'] >= former['destroyed'] and item.get('source') == former.get('source')
    prepared = commands.prepare(before); trace = after['trajectory'][-1]; accepted = []
    rows = [d for d in trace['decisions'] if d.get('source') == 'native_unit_agent']
    assert {d['unit_id'] for d in rows} == set(before['command_state']['unit_agents'])
    for row in rows:
        observer = SimpleNamespace(runs=[r for r in trace['runs'] if r['id'] in row['run_ids']])
        ctx = proposal.context(before, prepared, row['unit_id'], operation_id=row['proposal']['operation_id'])
        args, proof = proposal.submitted(observer, ctx)
        assert proof == row['proposal']
        receipt = next(r for r in reversed(after['command_state']['receipts'])
                       if r['turn'] == after['turn_count'] and r['unit_id'] == row['unit_id'])
        assert receipt['proposal'] == proof and receipt['rationale'] == args['rationale']
        assert receipt['expected_effect'] == args['expected_effect']
        checked = commands.replace_queue(before, [{**args['order'], 'unit_id': row['unit_id']}],
            **{k: prepared['state'][k] for k in ('control_team', 'director', 'no_fire', 'intent')})
        assert commands.step_order(before, checked['orders'][0], prepared['state']) == receipt['planned']
        binding = before['command_state'].get('agent_sessions',{}).get(row['unit_id'])
        current_binding=after['command_state']['agent_sessions'][row['unit_id']]
        if binding is not None:
            assert current_binding['session_id'] == binding['session_id']
        assert proof['session_id'] == current_binding['session_id']
        accepted.append(proof)
    from backend import afsim_state
    view = dsh_simulation.observation_view(old)
    body=trace['prompt'].split('\n当前态势：',1)[1].split('\n史料：',1)[0]
    encoded=json.loads(body)
    restored=observation_codec.decode(encoded,resolve=lambda query:afsim_state.observation(before,query))
    assert json.dumps(restored,sort_keys=True,ensure_ascii=False)==json.dumps(view,sort_keys=True,ensure_ascii=False)
    if encoded.get(observation_codec.TABLE,{}).get('version')==observation_codec.DETAIL_VERSION:
        assert encoded[observation_codec.TABLE]['world_version']==commands.world_version(before)
    assert observation_codec.TABLE in encoded
    return dict(passed=True, turn=after['turn_count'], actors=22, native_proposals=accepted,
        encoded_prompt_found=True, exact_observation_roundtrip=True,
        browser_numeric_values_match_authoritative=True,
        authoritative_before=str(authoritative_before) if authoritative_before else None,
        authoritative_after=str(authoritative_after) if authoritative_after else None,
        source_labels_preserved=True, clock_delta_seconds=3600,
        mission_status=new['mission']['status'], winner=new['mission'].get('winner'),
        losses={t: sum(u['personnel']['casualties'] for u in new[t+'_units']) for t in ('red','blue')},
        run_count=len(trace['runs']),
        compactions=sum(e.get('type') == 'compaction/end' for r in trace['runs'] for e in r.get('events', [])),
        known_open_issue=('Full-window motion and historical calibration require separate acceptance'
            if old['mission']['definition'].get('movement_feedback') else
            'Original motion feedback P0 is not repaired or accepted by this proposal-channel test'),
        scope='Real tool arguments, host normalization, Native identities, accounts and encoded main prompt; not historical efficacy, narrative truth or full campaign acceptance')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--authoritative-before', type=Path)
    parser.add_argument('--authoritative-after', type=Path)
    args = parser.parse_args(); path = args.directory/'audit.json'
    if path.exists(): parser.error('Preserve prior audit evidence')
    result = audit(args.directory, authoritative_before=args.authoritative_before,
                   authoritative_after=args.authoritative_after)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('native_proposals', 'scope')}, ensure_ascii=False))
