"""Read-only campaign catalogue audit; no sessions, keys, model or engine calls.

Counts are structural evidence, not certification of historical accuracy.
Default and latest source versions are reported separately; no migration occurs.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gentactix import campaign_scope, historical_initial as hi, historical_operations as ho


def inspect(battle, version, legacy_objectives=None):
    definition = hi.definition(battle, version)
    units = definition['units']
    index = {u['id']: u for u in units}
    phases = []
    for phase in definition['phases']:
        snapshot = hi.initial(battle, phase['id'], version=version)['historical_initial']
        guidance_error = None
        try:
            guidance = ho.objective_guidance(snapshot)
        except ValueError as exc:
            guidance, guidance_error = None, str(exc)
        row = {'id': phase['id'], 'label': phase['label'],
               'execution_window': phase.get('execution_window'),
               'geographic_scope': phase.get('geographic_scope'),
               'process_requirements': [r['kind'] for r in phase.get('process_requirements', [])],
               'interaction':phase.get('interaction'),
               'objective_guidance': guidance,
               'objective_guidance_error': guidance_error,
               'template_ready': False, 'actors': [], 'error': None}
        try:
            row['actors'] = list(ho.configuration_template(snapshot)['actors'])
            row['template_ready'] = True
            row['sides'] = dict(Counter(index[i]['team'] for i in row['actors']))
        except (ValueError, KeyError, TypeError) as exc:
            row['error'] = str(exc)
            row['error_type'] = type(exc).__name__
        phases.append(row)
    try:
        selected = campaign_scope.select(snapshot)
        campaign = {'selection_ready': True, 'actors': selected,
                    'sides': dict(Counter(index[i]['team'] for i in selected)), 'error': None}
    except ValueError as exc:
        campaign = {'selection_ready': False, 'actors': [], 'sides': {}, 'error': str(exc)}
    ancestors = set()
    for identity in campaign['actors']:
        parent = index[identity]['parent_id']
        while parent:
            ancestors.add(parent)
            parent = index[parent]['parent_id']
    campaign['excluded_formation_ancestors'] = [u['id'] for u in units
        if u['id'] in ancestors and u['role'] in ('formation', 'support')]
    campaign['caveat'] = '累计地面候选去重，不证明同日到场、下级完整或会战配置可执行。'
    fact_counts = {field: sum(u['facts'][field]['value'] is not None for u in units)
                   for field in ('personnel', 'equipment', 'position')}
    positions = Counter((u['facts']['position']['value'] or {}).get('kind', 'unknown') for u in units)
    measurements=[r for p in definition['phases'] for r in p.get('measurements',[])]
    path = ROOT / 'data/historical_initial' / definition['id'] / (version + '.json')
    return {'id': definition['id'], 'version': version, 'battle': battle,
            'file': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'nodes': len(units), 'roles': dict(Counter(u['role'] for u in units)),
            'parent_links': sum(u['parent_id'] is not None for u in units),
            'source_records': len(definition['sources']),
            'coverage': definition['coverage'], 'non_null_facts': fact_counts,
            'position_kinds': dict(positions), 'phases': phases, 'campaign_selection': campaign,
            'scoped_measurements':{'count':len(measurements),
                'by_metric':dict(Counter(r['metric'] for r in measurements)),
                'by_statistic':dict(Counter(r['statistic'] for r in measurements)),
                'scope':'阶段数值资料；不计入开局non_null_facts，不证明全建制兵额、当前库存或历史标定。'}}


def totals(rows):
    return {'profiles': len(rows), 'nodes': sum(r['nodes'] for r in rows),
            'phases': sum(len(r['phases']) for r in rows),
            'template_ready_phases': sum(p['template_ready'] for r in rows for p in r['phases']),
            'profiles_with_local_template': sum(any(p['template_ready'] for p in r['phases']) for r in rows),
            'noncontact_ready_phases':sum(p['template_ready'] and bool(p['interaction']) for r in rows for p in r['phases']),
            'campaign_selection_ready': sum(r['campaign_selection']['selection_ready'] for r in rows),
            'coverage_all_true': sum(all(r['coverage'][k] for k in
                ('order_of_battle_complete', 'opening_deployment_complete', 'strength_complete')) for r in rows),
            'non_null_facts': {k: sum(r['non_null_facts'][k] for r in rows)
                               for k in ('personnel', 'equipment', 'position')},
            'roles': dict(sum((Counter(r['roles']) for r in rows), Counter())),
            'scoped_measurements':sum(r['scoped_measurements']['count'] for r in rows),
            'local_actor_distribution': dict(sorted(Counter(len(p['actors']) for r in rows
                for p in r['phases'] if p['template_ready']).items()))}


def audit():
    rows = []
    for record in sorted(hi.catalog(), key=lambda r: r['profile_id']):
        folder = ROOT / 'data/historical_initial' / record['profile_id']
        versions = sorted((p.stem for p in folder.glob('*.json')), key=lambda v: tuple(map(int, v.split('.'))))
        # Inspect ALL stored versions, including superseded ones: malformed data must fail loudly.
        for version in versions:
            row = inspect(record['battle'], version)
            row.update(is_default=version == record['version'], is_latest=version == versions[-1])
            rows.append(row)
    editorial = {}
    for series in ('anti_japanese_war', 'long_march'):
        root = ROOT / 'data' / series
        editorial[series] = {name: len(list(csv.DictReader((root / name).open(encoding='utf-8'))))
                             for name in ('forces.csv', 'timeline.csv', 'figures.csv', 'verification_gaps.csv')}
        editorial[series]['sources'] = len(json.loads((root / 'sources.json').read_text())['sources'])
    paths = [ROOT / r['file'] for r in rows]
    paths += [ROOT / p for p in ('data/historical_initial/index.json', 'data/historical_objectives.json',
        'data/historical_objective_bindings.json',
        'gentactix/historical_initial.py', 'gentactix/historical_operations.py', 'gentactix/campaign_scope.py',
        'gentactix/force_organization.py', 'gentactix/phase_continuity.py', 'backend/phase_routes.py',
        'backend/afsim_state.py', 'backend/scenario_builder.py', 'backend/scenario_assembly.py',
        'tools/qa/campaign_readiness_audit.py')]
    for series in ('anti_japanese_war', 'long_march'):
        paths.extend(ROOT / 'data' / series / name for name in
            ('sources.json', 'scenarios.json', 'forces.csv', 'timeline.csv', 'figures.csv', 'verification_gaps.csv'))
    # A cumulative two-sided selection failure is not a failed local transfer.
    # Report registered windows independently; none of these are execution tests.
    from gentactix import campaign_windows as cw
    windows=[]
    for path in sorted(cw.DATA_ROOT.glob('*/*.json')):
        value=json.loads(path.read_text());pin=cw.pin(value['id'],value['version'])
        snapshot=hi.initial(value['battle'],value['start_phase_id'],version=value['historical_initial']['version'])['historical_initial']
        template=ho.configuration_template(snapshot,'campaign',window=pin,termination_mode='objectives')
        windows.append(dict(id=value['id'],version=value['version'],battle=value['battle'],actors=len(template['actors']),
            source_version=snapshot['version'],interaction=ho.interaction_scope(snapshot),
            template_ready=True,execution_verified=False))
        paths.append(path)
    failures = [{'profile': r['id'], 'version': r['version'], 'phase': p['id'],
                 'type': p['error_type'], 'error': p['error']} for r in rows for p in r['phases']
                if p.get('error_type') not in (None, 'ValueError')]
    return {'format': 'campaign-structural-audit-1', 'created_at': datetime.now(timezone.utc).isoformat(),
            'scope': '只检查本地来源结构与模板入口；未联网复核原件，未运行真实模型或完整历史会战；不读取存档和配置。',
            'readiness_warning': 'hi.readiness固定返回过程未认证，不能把该字段当全场景实测成绩；累计序列、局部非接敌模板、注册窗口分别统计，未运行真实模型或物理过程。',
            'all_version_count': len(rows), 'defaults': totals([r for r in rows if r['is_default']]),
            'latest': totals([r for r in rows if r['is_latest']]), 'editorial': editorial,
            'unexpected_template_errors': failures,
            'registered_windows':windows,
            'input_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'versions': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.cache/qa/campaign-architecture-2026-10-31')
    parser.add_argument('--require-template-health', action='store_true',
                        help='Exit 1 after writing report if a template raises an unexpected exception')
    args = parser.parse_args()
    report = audit()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'catalogue.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    fields = ['id', 'battle', 'default_version', 'latest_version', 'default_nodes', 'latest_nodes',
              'local_phases', 'local_leaf_counts', 'campaign_selection_ready', 'campaign_error',
              'campaign_red', 'campaign_blue', 'known_personnel',
              'known_equipment', 'known_position', 'formation_ancestors_excluded', 'source_notes',
              'scoped_measurements','measurement_statistics']
    with (args.output / 'catalogue.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in (r for r in report['versions'] if r['is_latest']):
            default = next(r for r in report['versions'] if r['id'] == row['id'] and r['is_default'])
            ready = [p for p in row['phases'] if p['template_ready']]
            campaign = row['campaign_selection']
            writer.writerow(dict(id=row['id'], battle=row['battle'], default_version=default['version'],
                latest_version=row['version'], default_nodes=default['nodes'], latest_nodes=row['nodes'],
                local_phases=';'.join(p['id'] for p in ready), local_leaf_counts='/'.join(str(len(p['actors'])) for p in ready),
                campaign_selection_ready=campaign['selection_ready'], campaign_error=campaign['error'],
                campaign_red=campaign['sides'].get('red', '') if campaign['selection_ready'] else '',
                campaign_blue=campaign['sides'].get('blue', '') if campaign['selection_ready'] else '',
                known_personnel=row['non_null_facts']['personnel'], known_equipment=row['non_null_facts']['equipment'],
                known_position=row['non_null_facts']['position'],
                formation_ancestors_excluded=len(campaign['excluded_formation_ancestors']),
                source_notes='；'.join(row['coverage']['notes']),scoped_measurements=row['scoped_measurements']['count'],
                measurement_statistics=json.dumps(row['scoped_measurements']['by_statistic'],ensure_ascii=False)))
    print(json.dumps({k: v for k, v in report.items() if k not in ('versions', 'input_sha256')}, ensure_ascii=False, indent=2))
    if args.require_template_health and report['unexpected_template_errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
