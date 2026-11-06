"""The AFSIM script API: the objects and methods a scenario script can call.

A tactics processor is a script, and a script is written against objects --
PLATFORM, SENSOR, WEAPON, TRACK, PROCESSOR -- and the methods on them. None of
that was reachable through this server: the command index holds input-file
commands, and the event index holds event names, so "what methods does
WsfTrack have" had no answer anywhere. Anyone wiring a processor together was
left guessing names and discovering the truth by running mission until it
stopped saying "Unknown identifier".

The product documents it in documentation/html/docs/script/ -- 330 pages, 295
of them a WSF class, each listing its methods with a return type, an argument
list and a description. That is read here rather than written, so the method
names are AFSIM's own.
"""

import json
import re
from pathlib import Path

CACHE_MAX_AGE_HOURS = 48

PAGES_RELATIVE = Path("documentation") / "html" / "docs" / "script"

# <dt id="WsfTrack.Initialize">void Initialize<span ...>(</span>...</dt>
METHOD_DT_RE = re.compile(
    r'<dt id="(?P<id>[^"]+)">(.*?)</dt>\s*(?:<dd>(.*?)</dd>)?', re.S
)
HEADING_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
SECTION_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
IDENT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _text(fragment):
    if not fragment:
        return ""
    flat = TAG_RE.sub(" ", fragment)
    for entity, character in (("&para;", "¶"), ("&mdash;", "-"), ("&nbsp;", " "),
                              ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                              ("&#8212;", "-"), ("&rsquo;", "'"), ("&lsquo;", "'")):
        flat = flat.replace(entity, character)
    return " ".join(flat.split())


def _signature(fragment):
    """`void Initialize ( )` -> return type, method name, argument text."""
    flat = _text(fragment)
    flat = flat.replace(" (", "(").replace("( ", "(").replace(" )", ")")
    flat = re.sub(r"\s+", " ", flat).strip().rstrip("¶").strip()
    match = IDENT_RE.search(flat)
    if not match:
        return None
    name = match.group(1)
    before = flat[: match.start(1)].strip()
    after = flat[match.end(1) :]
    return {"name": name, "returns": before or "void", "args": after.strip("() ").strip()}


class ScriptApi:
    """Classes the AFSIM scripting language exposes, and their methods."""

    def __init__(self, host):
        self.host = host

    def index_path(self):
        return self.host.state_dir / "afsim_script_api.json"

    def pages_dir(self):
        for root in (self.host.resolve_afsim_root(),):
            if not root:
                continue
            candidate = Path(root) / PAGES_RELATIVE
            if candidate.is_dir():
                return candidate
        return None

    def docs_dir(self):
        for root in (self.host.resolve_afsim_root(),):
            if not root:
                continue
            candidate = Path(root) / PAGES_RELATIVE.parent
            if candidate.is_dir():
                return candidate
        return None

    def _pages(self):
        """Every documentation page that carries script method anchors.

        The scripting directory holds the common language types, but a WSF
        model's own page documents its script methods too, and that is where
        WSF_ASSET_MANAGER lives -- the class whose GetEWRequired /
        GetTARRequired / GetTTRRequired are the rules behind "sensor is of
        unknown type, did you forget to assign a category", and therefore
        behind a platform that qualifies no assets and never fires.
        """
        pages = []
        scripting = self.pages_dir()
        if scripting:
            pages.extend(sorted(scripting.glob("*.html")))
        docs = self.docs_dir()
        if docs:
            # Wsf*.html in the documentation root carries a model's script
            # methods; WSF_*.html does not -- its dotted anchors are
            # input-file commands, which the command index already holds.
            pages.extend(sorted(docs.glob("Wsf*.html")))
        return pages

    def build(self):
        pages = self._pages()
        if not pages:
            return {
                "built": False,
                "reason": f"{PAGES_RELATIVE.as_posix()} not found under AFSIM_ROOT",
                "hint": "The script API is read from the AFSIM scripting documentation. "
                "Without it, script object methods can only be discovered by running "
                "mission until it stops reporting an unknown identifier.",
            }
        classes = {}
        for page in pages:
            try:
                raw = page.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            heading = HEADING_RE.search(raw)
            title = _text(heading.group(1)) if heading else page.stem
            # The heading carries a "¶" permalink marker, which made the title
            # fail the identifier test and fall back to the lower-cased file
            # name. Every method then compared unequal to its own class and was
            # filed as inherited instead of declared: 13 methods found out of
            # 172 on the first page.
            title = title.replace("¶", "")
            title = title.split("—")[0].split("- ")[-1].strip() or page.stem
            if not title or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", title):
                title = page.stem
            methods = []
            for match in METHOD_DT_RE.finditer(raw):
                anchor = match.group("id")
                if "." not in anchor:
                    continue
                owner, _dot, rest = anchor.partition(".")
                if rest and not rest[0].isupper():
                    # A nested anchor, not a method of this class.
                    continue
                parsed = _signature(match.group(2))
                if not parsed or parsed["name"] in ("sig-paren",):
                    continue
                description = _text(match.group(3))
                methods.append(
                    {
                        "name": parsed["name"],
                        "returns": parsed["returns"],
                        "args": parsed["args"],
                        "declared_on": owner,
                        "description": description[:300] or None,
                    }
                )
            if not methods:
                continue
            seen = set()
            unique = []
            for method in methods:
                key = (method["name"], method["declared_on"])
                if key in seen:
                    continue
                seen.add(key)
                unique.append(method)
            unique.sort(key=lambda m: m["name"])
            entry = classes.get(title)
            if entry is None:
                entry = {
                    "name": title,
                    "page": page.name,
                    "script_keyword": _keyword_for(title),
                    "methods": [],
                    "inherited_from": [],
                }
                classes[title] = entry
            for method in unique:
                declared_on = method["declared_on"]
                # The anchor is authored with the class's real spelling while
                # the page heading may differ only in case.
                if declared_on.lower() != title.lower():
                    if declared_on not in entry["inherited_from"]:
                        entry["inherited_from"].append(declared_on)
                else:
                    method["declared_on"] = title
                    entry["methods"].append(method)

        by_method = {}
        for entry in classes.values():
            for method in entry["methods"]:
                by_method.setdefault(method["name"].lower(), set()).add(entry["name"])

        return {
            "built": True,
            "source": [str(pages_dir) for pages_dir in (self.pages_dir(), self.docs_dir()) if pages_dir],
            "class_count": len(classes),
            "method_count": sum(len(c["methods"]) for c in classes.values()),
            "classes": classes,
            "by_method": {name: sorted(owners) for name, owners in by_method.items()},
        }

    def load(self, *, refresh=False):
        path = self.index_path()
        if not refresh and path.is_file():
            try:
                if (Path().stat().st_mtime - path.stat().st_mtime) / 3600.0 < CACHE_MAX_AGE_HOURS:
                    return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        data = self.build()
        if data.get("built"):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return data

    def describe(self, name):
        data = self.load()
        if not data.get("built"):
            return None, data
        entry = (data.get("classes") or {}).get(name)
        if entry:
            return entry, data
        lowered = str(name or "").lower()
        for key, value in (data.get("classes") or {}).items():
            if key.lower() == lowered:
                return value, data
        return None, data

    def find_method(self, method_name):
        data = self.load()
        if not data.get("built"):
            return None, data
        owners = (data.get("by_method") or {}).get(str(method_name or "").lower())
        return (owners or []), data

    def query(self, name=None, keyword=None, limit=None):
        data = self.load()
        if not data.get("built"):
            return self.host.wrap(dict(data))
        classes = data.get("classes") or {}

        if name:
            entry, _data = self.describe(name)
            if entry is not None:
                return self.host.wrap(
                    {
                        "query": name,
                        "found": True,
                        "class": entry["name"],
                        "script_keyword": entry["script_keyword"],
                        "method_count": len(entry["methods"]),
                        "inherited_from": entry["inherited_from"],
                        "methods": entry["methods"],
                        "page": entry["page"],
                        "source": data["source"],
                    }
                )
            owners, _data = self.find_method(name)
            if owners:
                collected = []
                for owner in owners:
                    for method in classes[owner]["methods"]:
                        if method["name"].lower() == str(name).lower():
                            collected.append({"class": owner, **method})
                return self.host.wrap(
                    {
                        "query": name,
                        "found": True,
                        "matched_in": "script method",
                        "classes": owners,
                        "methods": collected,
                        "source": data["source"],
                    }
                )
            return self.host.wrap(
                {
                    "query": name,
                    "found": False,
                    "class_count": data["class_count"],
                    "method_count": data["method_count"],
                    "did_you_mean": self._close(name, classes),
                    "hint": "Script classes are named as the documentation names them, "
                    "e.g. WsfTrack. Pass keyword to search every method on every class.",
                }
            )

        needle = str(keyword or "").lower()
        if needle:
            hits = []
            for entry in classes.values():
                for method in entry["methods"]:
                    haystack = f"{method['name']} {method['args']} {method['description'] or ''}".lower()
                    if needle in haystack:
                        hits.append({"class": entry["name"], **method})
            return self.host.wrap(
                {
                    "query": keyword,
                    "matched_in": "script methods",
                    "class_count": data["class_count"],
                    "method_count": data["method_count"],
                    "total_matching": len(hits),
                    "methods": hits[: int(limit) if limit else len(hits)],
                    "source": data["source"],
                }
            )

        return self.host.wrap(
            {
                "listing": "script_class",
                "class_count": data["class_count"],
                "method_count": data["method_count"],
                "classes": [
                    {
                        "name": c["name"],
                        "script_keyword": c["script_keyword"],
                        "method_count": len(c["methods"]),
                    }
                    for c in sorted(classes.values(), key=lambda c: c["name"])
                ],
                "source": data["source"],
                "hint": "Pass a class name (WsfTrack, WsfPlatform) to list its methods, or "
                "a method name to find which classes declare it. keyword searches the "
                "arguments and descriptions too.",
            }
        )

    @staticmethod
    def _close(name, classes):
        lowered = str(name or "").lower()
        out = []
        for entry in classes.values():
            if lowered and (lowered in entry["name"].lower() or entry["name"].lower() in lowered):
                out.append(entry["name"])
        return sorted(out)[:10]


def _keyword_for(class_name):
    """The bare object name a script refers to, e.g. WsfTrack -> Track.

    Derived from AFSIM's own naming convention rather than declared anywhere in
    the documentation, so it is reported as a convenience and the class name is
    what the caller should rely on.
    """
    name = class_name
    for prefix in ("WsfScript", "Wsf"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix) :]
            break
    return None
