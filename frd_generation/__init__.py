"""Generate Functional Requirements Documents from parsed BRD data."""

from importlib import import_module

_frd_agent = import_module("frd_generation.mcp_clients&llms.frd_agent")
FRDGeneration = _frd_agent.FRDGeneration
FRDUserStory = _frd_agent.FRDUserStory
generate_frd = _frd_agent.generate_frd
generate_frd_package = _frd_agent.generate_frd_package
serialize_brd_data = _frd_agent.serialize_brd_data

__all__ = [
    "FRDGeneration",
    "FRDUserStory",
    "generate_frd",
    "generate_frd_package",
    "serialize_brd_data",
]
