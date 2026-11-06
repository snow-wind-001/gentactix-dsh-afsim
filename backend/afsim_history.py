"""AFSIM dispatches hash-bound source frames; no planner or combat rules."""
import hashlib

from gentactix import history_replay
from . import afsim_world


def compile_scene(world):
    history_replay.validate(world)
    record = world['history_replay']
    references = [{'name': p['name'], 'lat': p['lat'], 'lng': p['lng']} for p in record['geo_references']]
    # These are geographic references, deliberately separate from unit ledgers.
    scene = afsim_world.compile_scene({'red_units': references, 'blue_units': []}, [], 1)
    token = hashlib.sha256((record['dataset_hash'] + ':' + str(record['cursor'])).encode()).hexdigest()
    scene['script'] += f'execute at_time 1 sec absolute\n writeln("GTXHISTORY|{token}");\nend_execute\n'
    scene.update(history_token=token, scope=record['scope'])
    return scene


def execute(session, cursor, cancel_check=None, progress=None):
    if session.get('war_state'):
        history_replay.validate(session['war_state'])
    world = history_replay.frame_for_session(session, cursor)
    scene = compile_scene(world)
    _, evidence = afsim_world.run_scene(session, scene, cancel_check, progress)
    if evidence.get('history_token') != scene['history_token']:
        raise ValueError('AFSIM未回传当前史料帧身份；拒绝提交')
    if cancel_check and cancel_check():
        raise RuntimeError('已取消史料重现，原帧保留')
    world['afsim'] = {**evidence, 'phase': 'historical_replay', 'model_skipped': True,
                      'effects_source': world['history_replay']['version'], 'context_strategy': 'sourced_event_frames',
                      'historical_roster_count': len(world['red_units']) + len(world['blue_units']),
                      'geographic_reference_count': len(world['history_replay']['geo_references']),
                      'combat_entity_count': 0, 'battlefield_initialized': False}
    return world
