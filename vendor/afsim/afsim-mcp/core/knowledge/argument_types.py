"""AFSIM argument types: what `<length-value>` actually means.

The shipped command index writes every numeric argument as a placeholder --
`altitude <length-value>`, `end_time <time-value>` -- and the placeholder is
where the syntax stops being checkable. Two tokens are needed and the second
one is a unit, so `altitude 5000m msl` is rejected for a reason the index
cannot express, and `end_time 00:00:30` is rejected because `<time-value>` is
a real followed by a unit, not a clock. Every one of those was found by
running mission until it stopped complaining.

The AFSIM documentation defines the productions properly, in
documentation/html/docs/argumenttypes.html, as a definition list:

    <dt id="length-value">length-value <em> &lt;real&gt;</em>...

with the accepted spellings for each unit in the table under `<dt id="...-units">`.
Both are read straight out of the markup, so the unit spellings are AFSIM's
own and not a list someone typed.
"""

import json
import re
from pathlib import Path

CACHE_MAX_AGE_HOURS = 48

PAGE_RELATIVE = Path("documentation") / "html" / "docs" / "argumenttypes.html"

# A definition-list entry: <dt id="length-value">length-value <em>&lt;real&gt;</em>...
DEFINITION_RE = re.compile(r'<dt id="([^"]+)">(.*?)</dt>', re.S)
ARG_RE = re.compile(r"&lt;([A-Za-z0-9_.-]+)&gt;")
# A unit entry followed by the table listing its acceptable spellings.
UNITS_RE = re.compile(r'<dt id="([^"]+-units)">.*?</dt>\s*<dd>(.*?)</dd>', re.S)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
PLACEHOLDER_RE = re.compile(r"<(?:[A-Za-z0-9_]+-)?value>")

_UNIT_LIST_RE = re.compile(r"[A-Za-z]+")


def _text(fragment):
    fragment = TAG_RE.sub(" ", fragment)
    fragment = (
        fragment.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&#8212;", "-")
        .replace("&nbsp;", " ")
    )
    return " ".join(fragment.split())


_HEADER_CELLS = {"unit of measure", "allowable input values", "value", "meaning", "kind"}


def _is_header_row(cells):
    """True for a table's header row, however it was marked up.

    The AFSIM pages use <th>, which the cell regex already skips, but a
    header written as <td> was counted as data and put "Allowable" and
    "Input" into the list of unit spellings AFSIM accepts.
    """
    return _text(cells[0]).lower() in _HEADER_CELLS


class ArgumentTypes:
    """Productions and unit spellings declared by the AFSIM documentation."""

    def __init__(self, host):
        self.host = host

    def index_path(self):
        return self.host.state_dir / "afsim_argument_types.json"

    def page_path(self):
        for root in (self.host.resolve_afsim_root(),):
            if not root:
                continue
            candidate = Path(root) / PAGE_RELATIVE
            if candidate.is_file():
                return candidate
        return None

    def build(self):
        page = self.page_path()
        if page is None:
            return {
                "built": False,
                "reason": f"{PAGE_RELATIVE.as_posix()} not found under AFSIM_ROOT",
                "hint": "Argument types are read from the AFSIM documentation. Without "
                "this page a command's syntax stops at its placeholders, and the "
                "spacing and unit rules have to be discovered by running mission.",
            }
        raw = page.read_text(encoding="utf-8", errors="ignore")

        productions = {}
        descriptions = {}
        units = {}

        # A definition is a <dt> plus, optionally, the <dd> that follows it
        # before the next <dt>. A <dt> with no <dd> of its own is an alias
        # heading for the definition that comes next: boolean-value is
        # declared empty and the prose and the accepted-value table belong to
        # boolean. Reading whichever table cell happened to be nearby produced
        # descriptions like "acceleration-units -> Length/Time 2", which is
        # the unit-of-measure column of a table, not a definition.
        for dt in re.finditer(r'<dt id="([^"]+)">(.*?)</dt>(.*?)(?=<dt |</dl>)', raw, re.S):
            name, body, following = dt.group(1), dt.group(2), dt.group(3)
            args = ARG_RE.findall(body)
            dd = re.match(r"\s*<dd>(.*)", following, re.S)
            if args and args != [name]:
                productions[name] = args
            elif dd:
                productions[name] = []
                lead = re.match(r"\s*<p>(.*?)</p>", dd.group(1), re.S)
                prose = _text(lead.group(1)) if lead else ""
                if prose:
                    descriptions[name] = prose[:240]
                tables = {}
                for row in ROW_RE.finditer(dd.group(1)):
                    cells = CELL_RE.findall(row.group(1))
                    if len(cells) >= 2 and not _is_header_row(cells):
                        tables.setdefault(_text(cells[0]), []).append(_text(cells[1]))
                if tables:
                    units[name] = [
                        {"unit_of_measure": label, "accepted": " ".join(values)}
                        for label, values in tables.items()
                    ]
            else:
                # A heading with no <dd> of its own. It is not an alias for
                # the heading that follows: latitude-value and
                # longitude-value are siblings sharing one definition, and
                # string-value and string are likewise grouped with
                # file-name. Routing one to the other produced
                # "latitude-value is a longitude", so these stay an opaque
                # single token with no invented description.
                productions[name] = []

        for match in UNITS_RE.finditer(raw):
            name, body = match.group(1), match.group(2)
            if name in units:
                continue
            rows = []
            for row in ROW_RE.findall(body):
                cells = CELL_RE.findall(row)
                if len(cells) >= 2 and not _is_header_row(cells):
                    rows.append({"unit_of_measure": _text(cells[0]), "accepted": _text(cells[1])})
            if rows:
                units[name] = rows

        return {
            "built": True,
            "source": str(page),
            "production_count": len(productions),
            "unit_table_count": len([n for n in units if n.endswith("-units")]),
            "value_table_count": len(units),
            "productions": productions,
            "descriptions": descriptions,
            "units": units,
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

    def unit_spellings(self, data, unit_name):
        """The literal strings AFSIM accepts for a unit production."""
        rows = (data.get("units") or {}).get(unit_name)
        if not rows:
            return []
        spellings = []
        for row in rows:
            accepted = row.get("accepted", "")
            # A composite such as "<length-units> / <time-units>" names other
            # productions rather than literals; follow one level so speed-units
            # still reports the words AFSIM actually parses.
            if "<" in accepted:
                for inner in ARG_RE.findall(accepted):
                    if inner != unit_name:
                        spellings.extend(self.unit_spellings(data, inner))
                continue
            spellings.extend(_UNIT_LIST_RE.findall(accepted))
        seen = set()
        ordered = []
        for item in spellings:
            if item.lower() in seen:
                continue
            seen.add(item.lower())
            ordered.append(item)
        return ordered

    def describe(self, name):
        data = self.load()
        if not data.get("built"):
            return None, data
        return (data.get("productions") or {}).get(name), data

    def explain(self, name, data):
        """A placeholder resolved into its real parts and accepted spellings."""
        production = (data.get("productions") or {}).get(name)
        if production is None:
            return None
        parts = []
        for part in production:
            spellings = self.unit_spellings(data, part)
            parts.append(
                {
                    "name": part,
                    "accepted_spellings": spellings,
                    "note": (
                        "A separate token. The value and its unit are two words: "
                        f"'5000 {spellings[0]}' not '5000{spellings[0]}'."
                        if spellings
                        else None
                    ),
                }
            )
        return {
            "type": name,
            "written_as": " ".join(f"<{p}>" for p in production) or "<value>",
            "parts": parts,
            "description": (data.get("descriptions") or {}).get(name),
        }

    def expand(self, syntax, data):
        """Inline every placeholder in a syntax line, with its spelling list."""
        found = []
        expanded = syntax
        for name in dict.fromkeys(PLACEHOLDER_RE.findall(syntax)):
            inner = name.strip("<>")
            detail = self.explain(inner, data)
            if detail is None:
                continue
            found.append(detail)
            expanded = expanded.replace(f"<{inner}>", detail["written_as"])
        return expanded, found
