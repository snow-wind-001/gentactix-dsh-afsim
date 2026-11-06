"""Layers, outermost last.

    core/knowledge   facts read out of the AFSIM installation; no judgement
    core/policy      the judgements this server makes, named and overridable
    core/runtime,
    core/validation,
    core/analysis    executors; thin, no knowledge of their own
    core/server      configuration resolution and JSON-RPC dispatch
    tools            the MCP surface: questions a model cannot answer alone

Dependencies point one way only. A lower layer never imports a higher one.
"""

from .knowledge import AfsimTypeIndex, MissionGrammar
from .validation import AfsimValidationService
from .analysis import AnalysisService
from .results import ResultsService
from .runtime import RuntimeService
from .server import MCPServer

__all__ = [
    "AfsimTypeIndex",
    "AfsimValidationService",
    "AnalysisService",
    "MCPServer",
    "MissionGrammar",
    "ResultsService",
    "RuntimeService",
]
