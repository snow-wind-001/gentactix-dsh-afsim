"""Recheck saved public QA evidence without network/model calls or state writes."""
import json
import re
from pathlib import Path

ROOT = Path('.cache/qa/state-observation-map-2026-11-01')
JOURNALS = Path('.cache/qa/scenario-admission-2026-11-01/browser/dsh-home/sessions')


def read(name):
    return json.loads((ROOT / name).read_text())


def main():
    cases = []
    for prefix in ('', 'contrast-'):
        before = read(prefix + 'production-chat-before.json')
        response = read(prefix + 'production-chat-response.json')
        review = read(prefix + 'production-chat-review.json')
        assert response['http'] == 200
        after = response['body']
        world = before['war_state']
        assert after['war_state'] == world
        blocks = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', after['chat_messages'][-1]['content'], re.S)
        assert len(blocks) == 1
        answer = json.loads(blocks[0])
        expected = dict(turn=world['mission']['turn'], elapsed_seconds=world['simulation_clock']['elapsed_seconds'],
            unit_count=len(world['red_units']) + len(world['blue_units']),
            objective_policy=world['mission']['definition']['campaign_definition']['objective_policy'],
            mission_condition=world['mission']['metrics']['condition'], requires_town_occupation=False,
            full_history_accepted=False)
        assert answer == expected == review['answer'] == review['expected']
        # Policy and history booleans above are reviewed scope facts, not inferred from success.
        assert expected['objective_policy'] == 'defensive-delay-1'
        assert world['mission']['winner'] is None
        assert len(review['native_sessions']) == 1
        sid = review['native_sessions'][0]['session_id']
        paths = list(JOURNALS.glob('*/' + sid + '/session.v4.jsonl'))
        assert len(paths) == 1
        calls, bindings = [], []
        # Read only public input and tool-call fields; do not export reasoning blocks.
        for row in map(json.loads, paths[0].read_text().splitlines()):
            data = row.get('data', {})
            if row.get('type') == 'user/message':
                for block in data.get('content', []):
                    text = block.get('text', '')
                    index = text.rfind('{"observation"')
                    if index >= 0:
                        o = json.loads(text[index:])['observation']
                        bindings.append((o['mission']['id'], o['execution']['process_id'], o['current_time']))
            if row.get('type') == 'tool/call' and data.get('name') == 'get_afsim_observation':
                calls.append(json.loads(data['arguments']))
        binding = (world['mission']['id'], before['afsim']['process_id'], world['current_time'])
        assert bindings == [binding], 'Native input belongs to another or ambiguous world'
        assert [x.get('offset', 0) for x in calls] == [0, 16, 32]
        assert all(not x.get('ids') for x in calls)
        assert sum(x.get('limit', 16) for x in calls) >= expected['unit_count']
        cases.append(dict(case=prefix or 'main', answer=answer, native_session=sid,
            public_world_binding=dict(mission_id=binding[0], process_id=binding[1], current_time=binding[2]),
            native_page_offsets=[x.get('offset', 0) for x in calls], world_unchanged=True))
    assert cases[0]['answer']['mission_condition'] is True
    assert cases[1]['answer']['mission_condition'] is False
    browsers = {name: read(name + '.json') for name in ['map-browser-review', 'map-app-review', 'map-supplement-review']}
    for result in browsers.values():
        assert result['passed'] and not result['errors']
    assert not browsers['map-app-review']['mutations'] and not browsers['map-supplement-review']['writes']
    result = dict(passed=True, model_calls=0, queries=cases,
        browser_checks={k: v['count'] for k, v in browsers.items()},
        scope='Offline saved public evidence recheck, not new live calls or full-history acceptance')
    (ROOT / 'evidence-recheck.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('PASS2world-bound Native fact queries and browser evidence recheck')


if __name__ == '__main__':
    main()
