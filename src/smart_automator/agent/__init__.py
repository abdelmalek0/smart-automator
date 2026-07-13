from .context import ActionResult, AgentContext, AgentOptions

__all__ = ["ActionResult", "AgentContext", "AgentOptions", "Executor"]


def __getattr__(name: str):
    if name == "Executor":
        from .executor import Executor
        return Executor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
