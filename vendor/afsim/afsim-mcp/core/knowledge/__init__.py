"""The AFSIM knowledge base.

This package reads the AFSIM installation and reports what is there. It makes
no judgements: it does not decide whether a type is "good", whether a run
"passed", or what a scenario should contain. Those are policy, and policy lives
in core/policy.py.

Everything here is derived from the installation, so it can be rebuilt after an
AFSIM upgrade and the extraction rules are pinned by tests. Nothing here is
authored by hand -- an earlier design that tried to infer a scenario from prose
produced the same three-fighter template no matter what was asked for.
"""

from .command_reference import CommandReference
from .event_index import AfsimEventIndex
from .mission_grammar import MissionGrammar
from .argument_types import ArgumentTypes
from .script_api import ScriptApi
from .source import read_normalized
from .type_index import AfsimTypeIndex

__all__ = [
    "AfsimEventIndex",
    "ArgumentTypes",
    "AfsimTypeIndex",
    "CommandReference",
    "MissionGrammar",
    "ScriptApi",
    "read_normalized",
]
