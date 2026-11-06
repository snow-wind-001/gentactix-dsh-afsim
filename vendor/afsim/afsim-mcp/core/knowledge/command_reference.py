"""The AFSIM command reference, read from the shipped documentation index.

`documentation/html/command_index.idx` is a machine-readable index of every
input-file command: 9,000+ anchors with their exact syntax. It is the
authoritative source, and it ships with the product, so it belongs in the
knowledge layer rather than in anything authored here.

An earlier evaluation spent roughly 45 run/parse round trips discovering things
this file already states: that a block ends with `end_<keyword>` and not `end`,
that `position` takes exactly two positional arguments, and that a number and
its unit must be separated by a space.
"""

import json
import re
import time
from pathlib import Path

IDX_RELATIVE = Path("documentation") / "html" / "command_index.idx"

PAGE_RE = re.compile(r"^docs/(\S+\.html)$")
FIELD_RE = re.compile(r"^ (\w+) ?(.*)$")
BLOCK_OPEN_RE = re.compile(r"^([a-z_]+) … end_\1$")

REQUIRED_ARG_RE = re.compile(r"<[^>]+>|\{[^}]+\}")
OPTIONAL_SEGMENT_RE = re.compile(r"\[([^\]]+)\]")


class CommandReference:
    """Every AFSIM input-file command and its syntax, as documented."""

    def __init__(self, host):
        self.host = host
        self.subsystems = SubsystemRequirements(host)

    def index_path(self):
        for root in (self.host.resolve_afsim_root(), self.host.resolve_demos_root()):
            if not root:
                continue
            for candidate in [Path(root) / IDX_RELATIVE, Path(root) / "command_index.idx"]:
                if candidate.is_file():
                    return candidate
        return None

    def cache_path(self):
        return self.host.state_dir / "afsim_command_reference.json"

    def load(self, *, refresh=False, max_age_hours=48):
        path = self.index_path()
        if path is None:
            raise self.host.JsonRpcError(
                -32003,
                "AFSIM command reference not found",
                {
                    "hint": "Expected "
                    + str(IDX_RELATIVE)
                    + " under the AFSIM installation. Set afsim_root."
                },
            )
        cache = self.cache_path()
        if not refresh and cache.is_file():
            try:
                if (time.time() - cache.stat().st_mtime) / 3600.0 <= max_age_hours:
                    return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        payload = self._parse(path)
        self.host.write_json(cache, payload)
        return payload

    def _parse(self, path):
        commands = {}
        page = None
        title = None
        pending_anchor = None
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            page_match = PAGE_RE.match(raw)
            if page_match:
                page = page_match.group(1)
                title = None
                pending_anchor = None
                continue
            field = FIELD_RE.match(raw)
            if not field:
                continue
            key, value = field.group(1), field.group(2).strip()
            if key == "page_name":
                page = page or value
            elif key == "title":
                title = value
            elif key == "cmd_anchor":
                pending_anchor = value
            elif key == "cmd_format" and pending_anchor:
                commands[pending_anchor] = self._entry(pending_anchor, value, page, title)
                pending_anchor = None
        by_name = {}
        for anchor, entry in commands.items():
            name = anchor.split(".")[-1]
            slot = by_name.setdefault(name, {"name": name, "forms": []})
            if entry not in slot["forms"]:
                slot["forms"].append(entry)
        return {
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": str(path),
            "command_count": len(commands),
            "distinct_name_count": len(by_name),
            "commands": commands,
            "by_name": by_name,
        }

    @staticmethod
    def _entry(anchor, fmt, page, title):
        block = bool(BLOCK_OPEN_RE.match(fmt))
        return {
            "anchor": anchor,
            "syntax": fmt,
            "page": page,
            "title": title,
            "is_block": block,
            "closer": f"end_{anchor.split('.')[0]}" if block else None,
            "required_args": REQUIRED_ARG_RE.findall(fmt),
            "optional_segments": OPTIONAL_SEGMENT_RE.findall(fmt),
            "context": anchor.split(".")[:-1],
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def documented_requirements(self, names):
        """What the shipped prose documentation says a component needs.

        An empty answer means the documentation never says, which is not the
        same as "needs nothing". The empty case is therefore reported as an
        explicit status rather than as a bare {} that reads like a clean bill
        of health, and the found case carries the same coverage note.
        """
        found = self.subsystems.requirements_for(names)
        asked = sorted({n for n in (names or []) if n})
        coverage = {
            "asked_about": asked,
            "status": "found" if found else "no_requirement_statement_found",
            "note": (
                "Only pages that phrase a requirement in prose are searched. AFSIM "
                "documents most wiring constraints in C++ headers and example scenarios, "
                "not in sentences, so a name missing here is undocumented rather than "
                "dependency-free."
            ),
        }
        result = dict(found)
        result["_coverage"] = coverage
        return result

    def query(self, name=None, keyword=None, limit=25):
        data = self.load(refresh=False)
        if name:
            entry = data["by_name"].get(str(name).lower())
            forms = entry["forms"] if entry else []
            if not forms:
                forms = [
                    entry
                    for anchor, entry in data["commands"].items()
                    if anchor.split(".")[-1] == str(name)
                ]
            if not forms:
                matches = self._search(data, str(name), limit=12)
                if not matches:
                    raise self.host.JsonRpcError(
                        -32602,
                        f"AFSIM command {name!r} not found",
                        {
                            "commands_indexed": data["command_count"],
                            "hint": "Commands are indexed from "
                            "<AFSIM_ROOT>/documentation/html/command_index.idx.",
                        },
                    )
                return {
                    "query": name,
                    "exact": False,
                    "did_you_mean": matches,
                }
            return {
                "query": name,
                "exact": True,
                "forms": self.with_argument_types(forms[:limit]),
            }

        matches = self._search(data, keyword or "", limit)
        return {
            "query": keyword,
            "command_count": data["command_count"],
            "total_matching": len(matches),
            "forms": self.with_argument_types(matches[:limit]),
            "built_at": data["built_at"],
        }

    def with_argument_types(self, forms):
        """Resolve placeholders, and say where each form is legal.

        Two things the command index holds but does not foreground.

        Placeholders: the index stops at `altitude <length-value>`, which does
        not say that the value and its unit are two tokens -- so `altitude
        5000m msl` fails for a reason the index cannot state. The productions
        and unit spellings come from the AFSIM documentation, so this is
        AFSIM's own grammar rather than a list of things that happened to
        work.

        Context: the same keyword is not legal in the same form everywhere.
        `hits_to_establish_track <M> <N>` is two integers inside a sensor's
        mode block, and a `_` in the context list means top level. An agent
        reading only the syntax writes `hits_to_establish_track 3`, is
        rejected, and concludes the command is wrong rather than that it was
        written in the wrong block.
        """
        types = getattr(self.host, "argument_types", None)
        data = types.load() if types is not None else {"built": False}
        explained = []
        for form in forms:
            enriched = dict(form)
            context = list(form.get("context") or [])
            if context:
                enriched["legal_in"] = [
                    "top level" if item == "_" else item for item in context
                ]
                enriched["context_note"] = (
                    "This form is only legal inside the block(s) listed. The same "
                    "keyword can take different arguments in a different block."
                )
            if not data.get("built"):
                explained.append(enriched)
                continue
            expanded, found = types.expand(form.get("syntax", ""), data)
            if found:
                enriched["syntax"] = expanded
                enriched["syntax_as_indexed"] = form.get("syntax")
                enriched["argument_types"] = found
            explained.append(enriched)
        return explained

    @staticmethod
    def _search(data, keyword, limit):
        needle = str(keyword or "").lower().strip()
        if not needle:
            forms = list(data["commands"].values())
        else:
            forms = [
                entry
                for entry in data["commands"].values()
                if needle in entry["syntax"].lower() or needle in entry["anchor"].lower()
            ]
        forms.sort(key=lambda e: (e["context"], e["anchor"]))
        return forms[:limit] if limit else forms


# ------------------------------------------------- required subsystems
# A SAM launcher is inert on its own: the AFSIM documentation states that
# "All SAM launchers need this subsystem in order to function correctly and be
# able to engage targets or assignments". That sentence is the difference
# between a SAM that fires and one that only detects, and it was previously
# only discoverable by reading the HTML docs by hand.


REQUIREMENT_HINTS = (
    " in order to function",
    "must be used with",
    "requires ",
    "need this subsystem",
    "is required for",
    "must have ",
)
SUBSYSTEM_RE = re.compile(r"\b(Wsf[A-Za-z0-9_]*|WSF_[A-Z0-9_]+)\b")
TAG_RE = re.compile(r"<[^>]+>")
HINT_RE = re.compile("|".join(re.escape(hint) for hint in REQUIREMENT_HINTS))


class SubsystemRequirements:
    """What the shipped documentation says a component needs in order to work."""

    def __init__(self, host):
        self.host = host

    def docs_root(self):
        for root in (self.host.resolve_afsim_root(),):
            if not root:
                continue
            for candidate in (
                Path(root) / "documentation" / "html" / "docs",
                Path(root) / "documentation" / "html",
            ):
                if candidate.is_dir():
                    return candidate
        return None

    def requirements_for(self, names):
        """Sentences in the documentation that name these types as needed."""
        root = self.docs_root()
        if root is None or not names:
            return {}
        found = {}
        wanted = {n for n in names if n}
        for page in sorted(root.glob("*.html")):
            try:
                text = TAG_RE.sub(" ", page.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            if not any(name in text for name in wanted):
                continue
            for match in HINT_RE.finditer(text):
                # Split on sentences where possible, but an abbreviation or a
                # table cell can leave debris in front of the hint, so the
                # window is bounded by the last strong break before it.
                start = max(
                    text.rfind(". ", 0, match.start()),
                    text.rfind(chr(10), 0, match.start()),
                    0,
                )
                end = text.find(". ", match.end())
                sentence = text[start : end if end != -1 else match.end() + 200]
                # The page's own subject is often what the sentence calls
                # "this subsystem" -- "All SAM launchers need this subsystem in
                # order to function" names no WSF_ token at all.
                mentioned = [m.group(1) for m in SUBSYSTEM_RE.finditer(sentence)]
                if not mentioned and page.stem in wanted:
                    mentioned = [page.stem]
                if not mentioned or not (set(mentioned) & wanted):
                    continue
                key = page.stem
                statements = found.setdefault(key, {"page": page.name, "statements": []})
                snippet = " ".join(sentence.split())[:300]
                if snippet not in statements["statements"]:
                    statements["statements"].append(snippet)
        if found:
            found["_coverage"] = {
                "asked_about": sorted(wanted),
                "answered": sorted(k for k in found if k != "_coverage"),
                "note": "Only pages that phrase a requirement in prose are searched. "
                "AFSIM documents most wiring constraints in C++ headers and example "
                "scenarios, not in sentences, so a name missing here is undocumented "
                "rather than dependency-free.",
            }
        return found
