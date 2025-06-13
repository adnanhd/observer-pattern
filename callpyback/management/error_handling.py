"""Error handling implementations."""

import logging
from abc import ABC, abstractmethod

from typing_compat import Any, Optional

from callpyback.core.context import ExecutionContext


class ErrorHandler(ABC):
    """Abstract base class for error handlers (Chain of Responsibility)."""

    def __init__(self, successor: Optional["ErrorHandler"] = None):
        self._successor = successor

    @abstractmethod
    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        """Check if this handler can handle the error."""
        pass

    @abstractmethod
    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle the error and return result."""
        pass

    def handle_error(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle error using chain of responsibility."""
        if self.can_handle(error, context):
            return self.handle(error, context)
        elif self._successor:
            return self._successor.handle_error(error, context)
        else:
            # No handler found, re-raise
            raise error


class TimeoutErrorHandler(ErrorHandler):
    """Handler for timeout-related errors."""

    def __init__(
        self, default_return: Any = None, successor: Optional[ErrorHandler] = None
    ):
        super().__init__(successor)
        self._default_return = default_return

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return isinstance(error, (TimeoutError, ConnectionError))

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle timeout error and return default value."""
        logging.warning(
            f"Function {context.function_signature.name} timed out: {error}. "
            f"Returning default value: {self._default_return}"
        )
        return self._default_return


class ValidationErrorHandler(ErrorHandler):
    """Handler for validation errors (usually re-raises)."""

    def __init__(self, successor: Optional[ErrorHandler] = None):
        super().__init__(successor)

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return isinstance(error, (TypeError, ValueError, AssertionError))

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle validation error by logging and re-raising."""
        logging.error(
            f"Validation error in {context.function_signature.name}: {error}. "
            f"Arguments: {context.arguments}"
        )
        # Re-raise validation errors as they indicate programming errors
        raise error


class FlexibleValidationErrorHandler(ErrorHandler):
    """Handler for validation errors with configurable behavior."""

    def __init__(
        self,
        reraise_validation_errors: bool = True,
        default_return: Any = None,
        successor: Optional[ErrorHandler] = None,
    ):
        super().__init__(successor)
        self._reraise_validation_errors = reraise_validation_errors
        self._default_return = default_return

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return isinstance(error, (TypeError, ValueError, AssertionError))

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle validation error based on configuration."""
        logging.error(
            f"Validation error in {context.function_signature.name}: {error}. "
            f"Arguments: {context.arguments}"
        )

        if self._reraise_validation_errors:
            # Re-raise validation errors as they indicate programming errors
            raise error
        else:
            # Return default value for user-friendly error handling
            return self._default_return


class NetworkErrorHandler(ErrorHandler):
    """Handler for network-related errors."""

    def __init__(
        self,
        retry_count: int = 0,
        default_return: Any = None,
        successor: Optional[ErrorHandler] = None,
    ):
        super().__init__(successor)
        self._retry_count = retry_count
        self._default_return = default_return

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        network_errors = (ConnectionError, OSError)
        # Check if it's a network-related error by name for broader compatibility
        error_name = error.__class__.__name__
        network_error_names = (
            "ConnectionError",
            "TimeoutError",
            "URLError",
            "HTTPError",
        )

        return isinstance(error, network_errors) or any(
            name in error_name for name in network_error_names
        )

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle network error with optional retry logic."""
        logging.warning(
            f"Network error in {context.function_signature.name}: {error}. "
            f"Retry count: {self._retry_count}"
        )

        # In a real implementation, you might implement retry logic here
        if self._retry_count > 0:
            logging.info(
                f"Retrying {context.function_signature.name} "
                f"({self._retry_count} retries remaining)"
            )
            # Note: Actual retry implementation would require access to the original function
            # This is simplified for demonstration

        return self._default_return


class BusinessLogicErrorHandler(ErrorHandler):
    """Handler for business logic errors."""

    def __init__(
        self,
        error_mapping: Optional[dict] = None,
        successor: Optional[ErrorHandler] = None,
    ):
        super().__init__(successor)
        self._error_mapping = error_mapping or {}

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        # Handle specific business logic exceptions
        business_indicators = ["business", "domain", "rule", "policy"]
        error_message = str(error).lower()
        error_type = error.__class__.__name__.lower()

        return (
            any(indicator in error_message for indicator in business_indicators)
            or any(indicator in error_type for indicator in business_indicators)
            or type(error) in self._error_mapping
        )

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle business logic error with custom mapping."""
        error_type = type(error)

        if error_type in self._error_mapping:
            result = self._error_mapping[error_type]
            logging.info(
                f"Business logic error in {context.function_signature.name}: {error}. "
                f"Mapped to result: {result}"
            )
            return result

        # Default business logic error handling
        logging.error(
            f"Business rule violation in {context.function_signature.name}: {error}. "
            f"Context: {context.arguments}"
        )

        # Return structured error information
        return {
            "error": True,
            "error_type": "business_logic",
            "message": str(error),
            "function": context.function_signature.name,
            "context": context.arguments,
        }


class SecurityErrorHandler(ErrorHandler):
    """Handler for security-related errors."""

    def __init__(
        self,
        audit_logger: Optional[logging.Logger] = None,
        successor: Optional[ErrorHandler] = None,
    ):
        super().__init__(successor)
        self._audit_logger = audit_logger or logging.getLogger("security_audit")

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        security_indicators = [
            "permission",
            "auth",
            "access",
            "security",
            "unauthorized",
        ]
        error_message = str(error).lower()
        error_type = error.__class__.__name__.lower()

        return any(
            indicator in error_message for indicator in security_indicators
        ) or any(indicator in error_type for indicator in security_indicators)

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle security error with audit logging."""
        # Log security incident for audit
        self._audit_logger.critical(
            f"SECURITY INCIDENT: {error} in {context.function_signature.name}. "
            f"Arguments: {context.arguments}. Timestamp: {context.timestamp}"
        )

        # Don't return sensitive information
        return {
            "error": True,
            "error_type": "security",
            "message": "Access denied",
            "incident_id": f"{context.function_signature.name}_{context.timestamp}",
        }


class DefaultErrorHandler(ErrorHandler):
    """Default error handler that returns a default value."""

    def __init__(
        self,
        default_return: Any = None,
        log_errors: bool = True,
        successor: Optional[ErrorHandler] = None,
    ):
        super().__init__(successor)  # Pass successor to parent
        self._default_return = default_return
        self._log_errors = log_errors

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return True  # Handles all errors as terminal handler

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle any unhandled error."""
        if self._log_errors:
            logging.error(
                f"Unhandled error in {context.function_signature.name}: "
                f"{error.__class__.__name__}: {error}. "
                f"Arguments: {context.arguments}. "
                f"Returning default: {self._default_return}",
                exc_info=True,
            )

        return self._default_return


class ConditionalErrorHandler(ErrorHandler):
    """Handler that applies conditions before handling errors."""

    def __init__(
        self,
        condition_func: callable,
        handler_func: callable,
        successor: Optional[ErrorHandler] = None,
    ):
        super().__init__(successor)
        self._condition_func = condition_func
        self._handler_func = handler_func

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        """Check if condition function returns True."""
        try:
            return self._condition_func(error, context)
        except Exception as e:
            logging.warning(f"Error in condition function: {e}")
            return False

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle error using custom handler function."""
        try:
            return self._handler_func(error, context)
        except Exception as e:
            logging.error(f"Error in custom handler function: {e}")
            raise error  # Re-raise original error if handler fails


class ErrorHandlerBuilder:
    """Builder class for creating error handler chains."""

    def __init__(self):
        self._handlers = []

    def add_timeout_handler(self, default_return: Any = None):
        """Add timeout error handler to chain."""
        self._handlers.append(
            ("timeout", TimeoutErrorHandler, {"default_return": default_return})
        )
        return self

    def add_validation_handler(self, reraise: bool = True, default_return: Any = None):
        """Add validation error handler to chain."""
        if reraise:
            self._handlers.append(("validation", ValidationErrorHandler, {}))
        else:
            self._handlers.append(
                (
                    "validation",
                    FlexibleValidationErrorHandler,
                    {
                        "reraise_validation_errors": False,
                        "default_return": default_return,
                    },
                )
            )
        return self

    def add_flexible_validation_handler(
        self, reraise: bool = True, default_return: Any = None
    ):
        """Add flexible validation error handler to chain."""
        self._handlers.append(
            (
                "validation",
                FlexibleValidationErrorHandler,
                {
                    "reraise_validation_errors": reraise,
                    "default_return": default_return,
                },
            )
        )
        return self

    def add_network_handler(self, retry_count: int = 0, default_return: Any = None):
        """Add network error handler to chain."""
        self._handlers.append(
            (
                "network",
                NetworkErrorHandler,
                {"retry_count": retry_count, "default_return": default_return},
            )
        )
        return self

    def add_business_logic_handler(self, error_mapping: Optional[dict] = None):
        """Add business logic error handler to chain."""
        self._handlers.append(
            (
                "business",
                BusinessLogicErrorHandler,
                {"error_mapping": error_mapping or {}},
            )
        )
        return self

    def add_security_handler(self, audit_logger: Optional[logging.Logger] = None):
        """Add security error handler to chain."""
        self._handlers.append(
            ("security", SecurityErrorHandler, {"audit_logger": audit_logger})
        )
        return self

    def add_conditional_handler(self, condition_func: callable, handler_func: callable):
        """Add conditional error handler to chain."""
        self._handlers.append(
            (
                "conditional",
                ConditionalErrorHandler,
                {"condition_func": condition_func, "handler_func": handler_func},
            )
        )
        return self

    def add_default_handler(self, default_return: Any = None, log_errors: bool = True):
        """Add default error handler to chain."""
        self._handlers.append(
            (
                "default",
                DefaultErrorHandler,
                {"default_return": default_return, "log_errors": log_errors},
            )
        )
        return self

    def build(self) -> ErrorHandler:
        """Build the error handler chain."""
        if not self._handlers:
            return DefaultErrorHandler()

        # Build chain from last to first
        handler_chain = None

        for name, handler_class, kwargs in reversed(self._handlers):
            # For DefaultErrorHandler, don't pass successor (it should be terminal)
            if name == "default":
                kwargs["successor"] = None  # Always terminal
            else:
                kwargs["successor"] = handler_chain
            handler_chain = handler_class(**kwargs)

        return handler_chain


# Convenience function for creating common error handler chains
def create_standard_error_chain(default_return: Any = None) -> ErrorHandler:
    """Create a standard error handler chain for common use cases."""
    return (
        ErrorHandlerBuilder()
        .add_security_handler()
        .add_timeout_handler(default_return)
        .add_network_handler(retry_count=1, default_return=default_return)
        .add_validation_handler()
        .add_business_logic_handler()
        .add_default_handler(default_return)
        .build()
    )


def create_simple_error_chain(default_return: Any = None) -> ErrorHandler:
    """Create a simple error handler chain for basic use cases."""
    return (
        ErrorHandlerBuilder()
        .add_timeout_handler(default_return)
        .add_default_handler(default_return)
        .build()
    )


def create_user_friendly_error_chain(default_return: Any = None) -> ErrorHandler:
    """Create a user-friendly error handler chain that doesn't re-raise validation errors."""
    return (
        ErrorHandlerBuilder()
        .add_timeout_handler(default_return)
        .add_flexible_validation_handler(reraise=False, default_return=default_return)
        .add_default_handler(default_return)
        .build()
    )


def create_validation_error_chain(default_return: Any = None) -> ErrorHandler:
    """Create an error handler chain that includes validation (re-raises validation errors)."""
    return (
        ErrorHandlerBuilder()
        .add_timeout_handler(default_return)
        .add_validation_handler()
        .add_default_handler(default_return)
        .build()
    )


def create_robust_error_chain(
    default_return: Any = None,
    error_mapping: Optional[dict] = None,
    audit_logger: Optional[logging.Logger] = None,
) -> ErrorHandler:
    """Create a comprehensive error handler chain for production use."""
    return (
        ErrorHandlerBuilder()
        .add_security_handler(audit_logger)
        .add_timeout_handler(default_return)
        .add_network_handler(retry_count=2, default_return=default_return)
        .add_validation_handler()
        .add_business_logic_handler(error_mapping)
        .add_default_handler(default_return)
        .build()
    )
