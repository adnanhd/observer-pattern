"""Variable extraction strategies."""

import sys
from contextlib import contextmanager

from typing_compat import Any, Dict, Generator, List


class NullVariable:
    """Null object for missing variables."""

    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return f"<Variable '{self.name}' not found>"

    def __repr__(self) -> str:
        return f"NullVariable('{self.name}')"


class TracingVariableExtractor:
    """Variable extractor using sys.setprofile."""

    def __init__(self):
        self._local_vars: Dict[str, Any] = {}
        self._original_profile = None

    @contextmanager
    def setup_extraction(self) -> Generator[None, None, None]:
        """Context manager for safe tracer setup."""
        self._original_profile = sys.getprofile()
        sys.setprofile(self._tracer)
        try:
            yield
        finally:
            sys.setprofile(self._original_profile)
            self._local_vars.clear()

    def _tracer(self, frame: Any, event: str, arg: Any) -> None:
        """Tracer function to capture local variables."""
        if event == "return":
            self._local_vars.update(frame.f_locals)

    def extract_variables(self, variable_names: List[str]) -> Dict[str, Any]:
        """Extract requested variables."""
        return {
            name: self._local_vars.get(name, NullVariable(name))
            for name in variable_names
        }


class NoOpVariableExtractor:
    """No-operation variable extractor for when extraction is disabled."""

    @contextmanager
    def setup_extraction(self) -> Generator[None, None, None]:
        yield

    def extract_variables(self, variable_names: List[str]) -> Dict[str, Any]:
        return {}
