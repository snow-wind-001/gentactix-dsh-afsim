"""The AFSIM event namespace.

event_output's `enable` and `disable` take event names, and mission rejects
any name it does not know with "Invalid event name for event_output". Those
names are not in the command index -- it holds commands, not the arguments
that name simulation events -- and they are not reliably in the HTML docs
either: documentation/html/docs/event/ carries 80 pages, and 17 of the 21
event names that actually appear in the demos shipped with AFSIM, including
PLATFORM_BROKEN and every SENSOR_TRACK_* and LOCAL_TRACK_* event, are not
among them.

They are declared in the SDK headers instead. Every event result class gives
its `cNAME` string a literal, and those literals are exactly what the
event_output block accepts. That is the same kind of source the type index
reads: a declaration in the shipped product, not a description of one.

The classes are not gathered in one header. The core ones live in
WsfEventResults.hpp, and each extension ships its own -- WsfMilEventResults.hpp
carries the whole WEAPON_* family (WEAPON_FIRED, WEAPON_HIT, WEAPON_MISSED, ...)
plus every SENSOR_TRACK_* and LOCAL_TRACK_* name. Reading only the core header
silently lost 55 names, so the index unions every header whose file name
matches *EventResults*.hpp; the GUI tools' preference classes also use cNAME
but none of them are named that way, so the filename filter keeps the set
exact.
"""

import json
import re
import time
from pathlib import Path

CACHE_MAX_AGE_HOURS = 48
SDK_INCLUDE_RELATIVE = Path("AFSimSdk") / "developer" / "include"

# Bump when the extraction rules change so cached indexes built by older
# rules are regenerated instead of served.
EXTRACTION_VERSION = 2

CNAME_RE = re.compile(r'cNAME\s*=\s*"([A-Z][A-Z0-9_]*)"')
# Each event result class is declared immediately above its cNAME. The classes
# are named after the event ("class PlatformBroken") and carry a visibility
# macro in place of a Wsf prefix; the macro name differs per extension
# (WSF_EXPORT, WSF_MIL_EXPORT, WSF_SPACE_EXPORT, ...).
CLASS_RE = re.compile(r"^\s*class\s+(?:[A-Z][A-Z0-9_]*_EXPORT\s+)?([A-Za-z][A-Za-z0-9_]*)")
# AFSIM writes event times as either seconds or HH:MM:SS.s, depending on the
# time_format the run selected.
_EVT_STAMP = r"^\d+(?::\d+){0,2}(?:\.\d+)?$"


def _evt_name_pattern():
    return re.compile(_EVT_STAMP)


class AfsimEventIndex:
    """Event names mission will accept in an event_output block."""

    def __init__(self, host):
        self.host = host

    def index_path(self):
        return self.host.state_dir / "afsim_events.json"

    def header_paths(self):
        """Every *EventResults*.hpp under the SDK include tree, sorted.

        Extensions declare their event result classes in their own headers
        (wsf_mil, wsf_cyber, wsf_mtt, wsf_space, ...), so the union of these
        files is the accepted-name set. Preference/UI classes also write
        cNAME literals but never in files named like this.
        """
        for root in (self.host.resolve_afsim_root(),):
            if not root:
                continue
            include_root = Path(root) / SDK_INCLUDE_RELATIVE
            if not include_root.is_dir():
                continue
            headers = [
                path
                for path in include_root.rglob("*.hpp")
                if "eventresults" in path.name.lower()
            ]
            return sorted(headers)
        return []

    def _parse_header(self, text, events):
        pending_class = None
        for line in text.splitlines():
            class_match = CLASS_RE.search(line)
            if class_match:
                pending_class = class_match.group(1)
            name_match = CNAME_RE.search(line)
            if not name_match:
                continue
            name = name_match.group(1)
            if name in events:
                continue
            events[name] = {
                "name": name,
                "result_class": pending_class,
            }
        return events

    def observed_names(self):
        """Event names that actually appear in the evt files AFSIM ships.

        The documentation groups events onto pages named platform_events.html
        and platform_killed.html rather than one page per event, so a page
        name is not an event name and matching on it yields nothing for any
        of the 98. What does carry information is whether the event turns up
        in a real run, so that is what gets reported instead.
        """
        root = self.host.resolve_demos_root()
        if not root:
            return set()
        stamp = _evt_name_pattern()
        seen = set()
        for path in Path(root).rglob("*.evt"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                if not line or line[0].isspace():
                    continue
                tokens = line.split()
                if len(tokens) >= 2 and stamp.match(tokens[0]):
                    seen.add(tokens[1])
        return seen

    def build(self):
        headers = self.header_paths()
        if not headers:
            return {
                "built": False,
                "reason": f"no *EventResults*.hpp found under "
                f"{SDK_INCLUDE_RELATIVE.as_posix()} in AFSIM_ROOT",
                "hint": "Event names are read from the AFSIM SDK headers; without them "
                "the only way to learn a valid name is to try it and read the error.",
            }
        observed = self.observed_names()
        events = {}
        for header in headers:
            try:
                text = header.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            self._parse_header(text, events)
        for entry in events.values():
            entry["seen_in_demos"] = entry["name"] in observed
        return {
            "built": True,
            "extraction_version": EXTRACTION_VERSION,
            "sources": [str(h) for h in headers],
            "event_count": len(events),
            "observed_in_demos": sum(1 for e in events.values() if e["seen_in_demos"]),
            "events": events,
        }

    def load(self, *, refresh=False):
        path = self.index_path()
        if not refresh and path.is_file():
            try:
                age_hours = (time.time() - path.stat().st_mtime) / 3600.0
            except OSError:
                age_hours = 0.0
            if age_hours < CACHE_MAX_AGE_HOURS:
                try:
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    if cached.get("extraction_version") == EXTRACTION_VERSION:
                        return cached
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

    def lookup(self, name):
        data = self.load()
        if not data.get("built"):
            return None, data
        wanted = str(name or "").strip().upper()
        entry = data["events"].get(wanted)
        return entry, data

    def resolve(self, name=None, keyword=None, limit=None):
        """Plain payload, no MCP envelope, for callers that combine indexes.

        Always returns a 4-tuple (entry_or_list, index_data, count, close).
        """
        data = self.load()
        if not data.get("built"):
            return None, data, 0, []
        events = data["events"]
        if name:
            wanted = str(name).strip().upper()
            entry = events.get(wanted)
            if entry is None:
                close = [
                    e
                    for e in events.values()
                    if wanted and (wanted in e["name"] or e["name"] in wanted)
                ][:10]
                return None, data, 0, close
            return entry, data, 1, []
        needle = str(keyword or "").strip().upper()
        selected = [e for e in events.values() if not needle or needle in e["name"]]
        selected.sort(key=lambda e: e["name"])
        return selected, data, len(selected), []

    def describe(self, entry, data):
        return {
            "query": entry["name"],
            "found": True,
            "event": entry,
            "usable_as": f"event_output ... enable {entry['name']}",
            "event_count": data["event_count"],
            "source_note": "Declared in the AFSIM SDK headers (core and extension "
            "*EventResults*.hpp). The HTML documentation groups events onto shared "
            "pages and names none of them individually, so a name missing from the "
            "docs is still valid.",
        }

    def query(self, name=None, keyword=None, limit=None):
        entry, data, count, close = self.resolve(name, keyword, limit)
        if not data.get("built"):
            return self.host.wrap(dict(data))
        if name:
            if entry is None:
                return self.host.wrap(
                    {
                        "query": name,
                        "found": False,
                        "event_count": data["event_count"],
                        "did_you_mean": close,
                    "hint": "Event names are read from the AFSIM SDK *EventResults* "
                    "headers (core and every extension). event_output rejects any name "
                    "outside this list.",
                    }
                )
            return self.host.wrap(self.describe(entry, data))
        selected = entry or []
        return self.host.wrap(
            {
                "listing": "event",
                "event_count": data["event_count"],
                "observed_in_demos": data.get("observed_in_demos", 0),
                "total_matching": count,
                "events": selected[: int(limit) if limit else len(selected)],
                "sources": [Path(s).name for s in data.get("sources", [])],
                "hint": "event_output's enable / disable accept these names. The list "
                "comes from the SDK headers, not from the HTML documentation. "
                "seen_in_demos marks the ones AFSIM's own scenarios actually produce.",
            }
        )
