"""Render sourced WWII China teaching records; --check verifies generated files."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.render_long_march import render as render_series

DATA = ROOT / "data/anti_japanese_war"


def format_quantity(value, qualifier):
    if qualifier in {"约", "近", "不足", "至少", "超过"}:
        return qualifier + str(value)
    return str(value) + qualifier


def render():
    outputs = render_series(
        DATA, "anti_japanese_war_anchors.json", "抗日战争", "全民族抗战（1937—1945）",
        "render_anti_japanese_war.py",
        "铁路修复、补给流量、地下组织存续、空中遮断、疲劳及跨场景继承",
        quantity_formatter=format_quantity)
    scenarios = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    # The source roster is separately versioned. Make its supported slice and
    # bibliography retrievable without turning unknown quantities into facts.
    from gentactix import historical_initial, historical_operations
    indexed = {r['battle']: r for r in historical_initial.catalog() if r['status'] == 'profiled'}
    for s in scenarios:
        if s['name'] not in indexed:
            continue
        definition = historical_initial.definition(s['name'])
        lines = ['', '## 具名历史初态与局部配置', '',
                 f"初态版本：`{definition['id']}/{definition['version']}`。参战参考不是逐单位实到兵力；缺载人数、装备和阵地保持未知。"]
        for phase in definition['phases']:
            try:
                selected = historical_operations.partition({'definition': definition, 'phase_id': phase['id']})
            except ValueError:
                continue
            lines.append(f"- **{phase['label']}（{phase['date']['label']}）**：" +
                         '、'.join(u['name'] for u in definition['units'] if u['id'] in selected) + '。')
            lines.append('  范围：' + phase['scope'])
        lines.extend(['', '各阶段独立核验到场状态；后续与场外部队保留参考，不自动填进开局。局部可配置不等于全战役或历史战损已经验收。',
                      '', '本版初态来源（未逐页核验原始档案）：'])
        for source in definition['sources'].values():
            lines.append(f"- [{source['title']}]({source['url']})，{source['publisher']}。{source['limitations']}")
        outputs[ROOT / 'corpus' / (s['name'] + '.md')] += '\n'.join(lines) + '\n'
    matrix = io.StringIO(newline="")
    writer = csv.writer(matrix)
    writer.writerow(["scenario_id", "battle", "phase", "theater", "local_posture", "parent_id", "scope", "rule_status"])
    matrix_lines = ["", "## 阶段与战场矩阵", "",
                    "分类用于资料组织与教学，未新增自动规则切换。上级与子场景战果不得重复累加。", "",
                    "| 编号 | 阶段 | 战场 | 局部态势 | 上级场景 |", "|---|---|---|---|---|"]
    for s in scenarios:
        writer.writerow([s["id"], s["name"], s["phase"], s["theater"], s["local_posture"],
                         s.get("parent_id", ""), s["scope"], "teaching_only"])
        matrix_lines.append(f'| {s["id"]} | {s["phase"]} | {s["theater"]} | {s["local_posture"]} | {s.get("parent_id") or "—"} |')
    outputs[DATA / "matrix.csv"] = matrix.getvalue()
    outputs[DATA / "INDEX.md"] += "\n".join(matrix_lines) + "\n"
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, content in render().items():
        encoded = content.encode("utf-8")
        if args.check:
            if not path.exists() or path.read_bytes() != encoded:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded)
    if stale:
        print("Out of date:\n" + "\n".join(stale))
        return 1
    print("Anti-Japanese War documents checked" if args.check else "Anti-Japanese War documents rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
