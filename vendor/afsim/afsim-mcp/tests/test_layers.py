"""Layer discipline.

The point of splitting the code is that a fact cannot quietly turn into a
judgement, and a lower layer cannot quietly depend on a higher one. Both are
checked here rather than left to review.
"""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent

# 0 = reads the AFSIM installation, 4 = the MCP surface.
LAYERS = {
    "knowledge": 0,
    "policy": 1,
    "runtime": 2,
    "validation": 2,
    "analysis": 2,
    "results": 2,
    "server": 3,
    "tools": 4,
}


def _layered_files():
    for path in sorted((REPO / "core").rglob("*.py")) + sorted((REPO / "tools").rglob("*.py")):
        if path.stem in LAYERS:
            yield path


def test_no_layer_imports_a_higher_one():
    violations = []
    for path in _layered_files():
        level = LAYERS[path.stem]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            for name in names:
                other = LAYERS.get(name.split(".")[-1])
                if other is not None and other > level:
                    violations.append(f"{path.name} -> {name}")
    assert not violations, f"upward imports: {violations}"


def test_knowledge_layer_does_not_import_policy_or_executors():
    """Reading the installation must not decide anything."""
    for path in (REPO / "core" / "knowledge").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            for name in names:
                assert name.split(".")[-1] not in ("policy", "runtime", "validation", "analysis", "server"), (
                    f"{path.name} imports {name}"
                )


def test_policy_layer_is_pure():
    """policy.py may not reach into the AFSIM install or the executors."""
    tree = ast.parse((REPO / "core" / "policy.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in ("subprocess", "pathlib"), "policy must not touch the system"


def test_tool_surface_stays_small():
    """Every tool has to justify itself; the count is a result, not a goal."""
    from tools import build_tool_specs

    names = {spec["name"] for spec in build_tool_specs()}
    assert len(names) <= 6, f"tool surface grew to {len(names)}: {sorted(names)}"
