"""Read-only historical force references and explicitly estimated exercise inputs.

Force names come from local sourced cards. Counts and tactical coordinates in
the exercise seed are modelling assumptions, never facts inferred from HP.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
from . import history_replay

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / 'data' / 'exercise_basis_archive'
VERSION = 'historical-exercise-basis-1'
CURATED = {
    '第一次战役': ('志愿军第39军', '美骑兵第1师'),
    '第二次战役': ('志愿军第38军', '美第8集团军'),
    '第三次战役': ('志愿军第50军', '美第8集团军'),
    '第四次战役': ('志愿军第50军', '美第8集团军'),
    '第五次战役': ('志愿军第63军', '美第8集团军'),
    '夏秋季防御战役': ('志愿军参战部队', '联合国军参战部队'),
    '秋季战术反击作战': ('志愿军第39军', '联合国军前沿守备部队'),
    '上甘岭战役': ('志愿军第45师第135团', '美第7师'),
    '夏季反击战役含金城战役': ('志愿军第20兵团', '韩国首都师'),
    '长平之战': ('秦军', '赵军'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def basis(battle):
    pack = history_replay.dataset(battle)
    card = ROOT / 'corpus' / (battle + '.md')
    text = card.read_text(encoding='utf-8')
    rows = []
    for index, force in enumerate(pack['forces']):
        side = force['side']
        team = 'red' if side.startswith('中国') or side == '红军' else 'blue'
        rows.append({'id': f'force-{index}', 'team': team, 'name': force['unit'],
            'context': force['description'], 'sources': copy.deepcopy(force['sources']),
            'source_locator': copy.deepcopy(force.get('source_locator', {})),
            'evidence_status': force.get('evidence_status', 'published_account'),
            'actual_personnel': None, 'actual_equipment': None, 'actual_tactical_position': None})
    if not rows:
        short = battle.split('-')[1] if '-' in battle else battle
        names = CURATED[short]
        section = re.search(r'## (?:双方兵力与指挥|兵力与伤亡[^\n]*)\n(.*?)(?=\n## |\Z)', text, re.S)
        refs = [{'title': title, 'url': url} for title, url in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', text)]
        for index, team in enumerate(('red','blue')):
            rows.append({'id': f'force-{index}', 'team': team, 'name': names[index],
                'context': (section[1].strip() if section else text[:2200]),
                'sources': refs, 'source_locator': {'card': str(card.relative_to(ROOT)), 'section': '双方兵力与指挥' if short != '长平之战' else '兵力与伤亡'},
                'evidence_status': 'local_sourced_card_excerpt',
                'actual_personnel': None, 'actual_equipment': None, 'actual_tactical_position': None})
    # The national overview names the local example in its sourced description.
    if '全面反攻与受降总览' in battle:
        row = next(r for r in rows if r['team']=='red')
        row['name'] = '晋察冀军区冀察部队'
    value = {'version': VERSION, 'battle': battle, 'card': str(card.relative_to(ROOT)),
             'card_digest': hashlib.sha256(text.encode()).hexdigest(), 'units': rows,
             'scope': '史料参战单位/隶属参考；不等于某时刻全军到场。演习取局部代表性编组，人数、装备可用量与战术部署另作估计。',
             'events': [{'date':e.get('date_label',e.get('date')), 'event':e['event']} for e in pack['events']],
             'unknowns': ['逐编组实到人数','逐类装备可用量','同一时刻战术部署','历史武器效能标定']}
    value['basis_hash'] = digest(value)
    return value


def resolve(battle, basis_hash):
    """Resolve an explicit reference version without replacing a saved source.

    Archives contain complete public inputs, not world state or model memory.
    A card edit must not silently rewrite a previously constructed exercise.
    """
    if not isinstance(basis_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', basis_hash):
        raise ValueError('史实基础摘要非法')
    current = basis(battle)
    if current['basis_hash'] == basis_hash:
        return current
    try:
        archived = json.loads((ARCHIVE / (basis_hash + '.json')).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('缺少本局固定的史实基础版本，原配置不能替换为当前来源') from exc
    if (not isinstance(archived, dict) or archived.get('version') != VERSION
            or archived.get('battle') != battle or archived.get('basis_hash') != basis_hash
            or digest({k: v for k, v in archived.items() if k != 'basis_hash'}) != basis_hash):
        raise ValueError('固定史实基础的战役、版本或摘要不一致')
    return archived


def exercise_seed(identity):
    from . import combined_arms
    spec = combined_arms.definition(identity); reference = basis(spec['battle'])
    config = combined_arms.configuration(identity)
    config['historical_basis'] = {'battle': reference['battle'], 'basis_hash': reference['basis_hash']}
    for team in ('red','blue'):
        candidates = [r for r in reference['units'] if r['team']==team]
        # Prefer a fighting formation over a headquarters if the card separates them.
        chosen = next((r for r in candidates if not any(k in r['name'] for k in ('中革军委','中央纵队','总部'))), candidates[0])
        row = copy.deepcopy(config['teams'][team][0]); row.update(name=chosen['name'], basis_id=chosen['id'])
        unit = spec['initial_state'][team+'_units'][0]
        row['position'] = {'lat': unit['lat'], 'lng': unit['lng']}
        # These zero quantities mean "not allocated in this exercise seed",
        # never "historically absent". DSH/user may allocate supported equipment.
        row['equipment'] = {key: 0 for key in row['equipment']}
        row['equipment'].update(engineer=6, transport=12)
        row.update(shells=0, aa_rounds=0)
        config['teams'][team] = [row]
    return {'basis': reference, 'configuration': config,'configuration_limits':combined_arms.configuration_limits(),
            'estimates': '种子人数与库存、工兵/运输配额及位置均为演习估计。零装备表示种子未配发，不证明历史没有该装备。',
            'map_center': spec['map_center'], 'map_radius_km': spec['map_radius_km']}
