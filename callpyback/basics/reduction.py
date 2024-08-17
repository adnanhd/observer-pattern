from abc import ABC, abstractmethod
from typing import Dict, Any, List, Set, Iterable
from collections import defaultdict
import threading
import math
from typing_extensions import Optional


class Reduction(ABC):
    """Abstract base class for reduction strategies."""

    __slots__ = ("localvars", "returnvars", "_call_hook", "_trace_call_names")

    def __init__(self, trace_calls: Optional[Set[str]] = None):
        self.returnvars: Dict[str, Any] = dict()
        self.localvars: Dict[str, Dict[str, Any]] = dict()
        self._call_hook: List[str] = list()
        self._trace_call_names: Optional[Set[str]] = trace_calls

    def set_trace_call_names(self, names: Optional[Set[str]]):
        self._trace_call_names = names

    def tracer(self, frame, event, arg) -> None:
        """Represents tracer storing local variables from executed function.
        Upon function return, tracer saves function locals to `local_vars`.

        Args:
            frame (Frame): Frame to be traced.
            event (Event): Event for tracing.
        Returns:
            None
        Raises:
            N/A
        """
        name = frame.f_code.co_name
        if event == "call" and (self._trace_call_names is None or name in self._trace_call_names):
            self._call_hook.append(name)
        if event == "return" and name in self._call_hook:
            self.returnvars[name] = arg
            self.localvars[name] = frame.f_locals.copy()

    def reduce_locals(self):
        locals = defaultdict(list)
        for local in self.localvars.values():
            for key, val in local.items():
                locals[key].append(val)

        return {key: self.reduce(vals) for key, vals in locals.items()}

    def reduce_return(self):
        if not self.returnvars:
            return math.nan
        return self.reduce(list(self.returnvars.values()))

    @abstractmethod
    def reduce(self, values: List[Any]) -> Any:
        pass


class SumReduction(Reduction):
    """Sum reduction strategy."""

    def reduce(self, values: List[Any]) -> Any:
        return sum(values)


class MeanReduction(Reduction):
    """Mean reduction strategy."""

    def reduce(self, values: List[Any]) -> Any:
        if values:
            return sum(values) / len(values)
        return math.nan


class MaxReduction(Reduction):
    """Max reduction strategy."""

    def reduce(self, values: List[Any]) -> Any:
        return max(values, default=math.nan)


class MinReduction(Reduction):
    """Min reduction strategy."""

    def reduce(self, values: List[Any]) -> Any:
        return min(values, default=math.nan)


class ListReduction(Reduction):
    """Stack reduction strategy."""

    def reduce(self, values: List[Any]) -> Any:
        return values.copy()


class DictReduction(Reduction):
    """Stack reduction strategy."""

    def reduce(self, values: List[Any]) -> Any:
        return values.copy()

    def reduce_locals(self):
        return self.localvars.copy()

    def reduce_return(self):
        return self.returnvars.copy()
