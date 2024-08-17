"""
This module contains the composition class, which is a wrapper for composition functions.
"""

import sys

from typing import Callable, Any, TypeVar
from functools import partial, reduce, wraps

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec


def _none_wrapper(func: Callable[..., Any]):
    return lambda x: func(x) if x is not None else None


__all__ = ["Composition", "composition_function", "compose_two_functions"]


class Composition(object):
    """Wrapper for composition functions"""

    def __init__(self, *funcs: Callable[..., Any], ignore_none: bool = False):
        assert all(map(callable, funcs)), "All functions must be callable"
        self._funcs = tuple(reversed(funcs))
        self._ignore_none = ignore_none

    def add_proloque(self, func: Callable[[Any], Any]):
        """Add a function to the proloque"""
        assert callable(func), "Callback must be callable"
        if self._ignore_none:
            func = _none_wrapper(func)
        self._funcs = (*self._funcs, func)
        return self

    def add_epiloque(self, func: Callable[[Any], Any]):
        """Add a function to the epilogue"""
        assert callable(func), "Callback must be callable"
        if self._ignore_none:
            func = _none_wrapper(func)
        self._funcs = (func, *self._funcs)
        return self

    def __call__(self, *args: Any, **kwargs: Any):
        return compose(*self._funcs)(*args, **kwargs)

    @property
    def composition(self) -> Callable[..., Any]:
        """Return the composed function"""
        return compose(*self._funcs)


def composition_function(func: Callable[..., Any]) -> Composition:
    """Decorator for composition functions"""
    return Composition(func)


P = ParamSpec("P")
MidValT = TypeVar("MidValT")
ResultT = TypeVar("ResultT")


def compose_two_functions(
    f: Callable[P, MidValT], g: Callable[[MidValT], ResultT], wrap: bool = True
) -> Callable[P, ResultT]:
    """Compose two functions"""
    assert callable(f), "First function must be callable"
    assert callable(g), "Second function must be callable"

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ResultT:
        return g(f(*args, **kwargs))

    if wrap:
        wrapper = wraps(f)(wrapper)
    return wrapper


def compose(
    func: Callable[P, Any], *functions: Callable[[Any], Any]
) -> Callable[P, Any]:
    """Compose functions"""
    return wraps(func)(
        reduce(partial(compose_two_functions, wrap=False), reversed(functions), func)
    )


def on_proloque(
    func: Callable[P, MidValT]
) -> Callable[[Callable[[MidValT], ResultT]], Callable[P, ResultT]]:
    """Decorator for post-processing functions"""

    @wraps(func)
    def wrapper(fn: Callable[[MidValT], ResultT]) -> Callable[P, ResultT]:
        return compose_two_functions(func, fn)

    return wrapper


def on_epiloque(
    func: Callable[[MidValT], ResultT]
) -> Callable[[Callable[P, MidValT]], Callable[P, ResultT]]:
    """Decorator for post-processing functions"""

    @wraps(func)
    def wrapper(fn: Callable[P, MidValT]) -> Callable[P, ResultT]:
        return compose_two_functions(fn, func)

    return wrapper
