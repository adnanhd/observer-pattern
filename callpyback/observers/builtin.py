"""Built-in observer implementations."""

import logging
from collections import defaultdict

from typing_compat import Any, Dict, List, Optional

from callpyback.core.context import ExecutionContext, ExecutionFailure, ExecutionResult
from callpyback.observers.base import BaseObserver


class LoggingObserver(BaseObserver):
    """Observer that logs execution events."""

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        log_level: int = logging.INFO,
        priority: int = 10,
    ):
        super().__init__(priority, "LoggingObserver")
        self._logger = logger or logging.getLogger(__name__)
        self._log_level = log_level

    def update(self, context: ExecutionContext) -> None:
        """Log execution event."""
        func_name = context.function_signature.name
        state = context.state.name

        if context.result:
            if isinstance(context.result, ExecutionResult):
                message = (
                    f"Function '{func_name}' completed successfully "
                    f"in {context.result.execution_time:.3f}s"
                )
            elif isinstance(context.result, ExecutionFailure):
                message = (
                    f"Function '{func_name}' failed: {context.result.exception} "
                    f"(execution time: {context.result.execution_time:.3f}s)"
                )
            else:
                message = f"Function '{func_name}' state: {state}"
        else:
            message = f"Function '{func_name}' state: {state}"

        self._logger.log(self._log_level, message)


class MetricsObserver(BaseObserver):
    """Observer that collects execution metrics."""

    def __init__(self, priority: int = 100):
        super().__init__(priority, "MetricsObserver")
        self._counters: Dict[str, int] = defaultdict(int)
        self._execution_times: List[float] = []
        self._function_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "successes": 0, "failures": 0, "total_time": 0.0}
        )

    def update(self, context: ExecutionContext) -> None:
        """Update metrics."""
        func_name = context.function_signature.name
        state = context.state.name

        # Update state counters
        self._counters[f"state_{state}"] += 1

        # Update function-specific stats
        if context.result:
            self._function_stats[func_name]["calls"] += 1

            if isinstance(context.result, ExecutionResult):
                self._function_stats[func_name]["successes"] += 1
                self._function_stats[func_name][
                    "total_time"
                ] += context.result.execution_time
                self._execution_times.append(context.result.execution_time)
            elif isinstance(context.result, ExecutionFailure):
                self._function_stats[func_name]["failures"] += 1
                self._function_stats[func_name][
                    "total_time"
                ] += context.result.execution_time

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        avg_time = (
            sum(self._execution_times) / len(self._execution_times)
            if self._execution_times
            else 0.0
        )

        return {
            "counters": dict(self._counters),
            "average_execution_time": avg_time,
            "total_executions": len(self._execution_times),
            "function_stats": dict(self._function_stats),
        }

    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self._counters.clear()
        self._execution_times.clear()
        self._function_stats.clear()


class TimingObserver(BaseObserver):
    """Observer that tracks detailed timing information."""

    def __init__(self, threshold: float = 1.0, priority: int = 75):
        super().__init__(priority, "TimingObserver")
        self._threshold = threshold
        self._slow_executions: List[Dict[str, Any]] = []

    def update(self, context: ExecutionContext) -> None:
        """Track timing information."""
        if not context.result or not hasattr(context.result, "execution_time"):
            return

        execution_time = context.result.execution_time

        if execution_time > self._threshold:
            self._slow_executions.append(
                {
                    "function_name": context.function_signature.name,
                    "execution_time": execution_time,
                    "timestamp": context.timestamp,
                    "arguments": context.arguments,
                    "success": isinstance(context.result, ExecutionResult),
                }
            )

            # Emit warning for slow execution
            logging.warning(
                f"Slow execution detected: {context.function_signature.name} "
                f"took {execution_time:.3f}s (threshold: {self._threshold}s)"
            )

    def get_slow_executions(self) -> List[Dict[str, Any]]:
        """Get list of slow executions."""
        return self._slow_executions.copy()

    def set_threshold(self, threshold: float) -> None:
        """Set slow execution threshold."""
        self._threshold = threshold
