"""Error handling implementations with Null Object pattern."""

import json
import logging
from abc import ABC, abstractmethod

from typing_compat import Any, Callable, Dict, Optional

from callpyback.core.context import ExecutionContext


class ErrorLoggingConfig:
    """Configuration for error handler logging."""

    def __init__(
        self,
        include_arguments: bool = True,
        max_arg_length: int = 200,
        max_error_message_length: int = 150,
        mask_sensitive_keys: bool = True,
        sensitive_keys: Optional[set] = None,
    ):
        self.include_arguments = include_arguments
        self.max_arg_length = max_arg_length
        self.max_error_message_length = max_error_message_length
        self.mask_sensitive_keys = mask_sensitive_keys
        self.sensitive_keys = sensitive_keys or {
            'password', 'token', 'secret', 'key', 'auth', 'credential',
            'pass', 'pwd', 'api_key', 'access_token', 'refresh_token'
        }


# Global logging configuration
_ERROR_LOG_CONFIG = ErrorLoggingConfig()
logger = logging.getLogger(__name__)


def configure_error_logging(**kwargs) -> None:
    """Configure global error logging settings."""
    global _ERROR_LOG_CONFIG
    for key, value in kwargs.items():
        if hasattr(_ERROR_LOG_CONFIG, key):
            setattr(_ERROR_LOG_CONFIG, key, value)


def _safe_serialize_arguments(arguments: Dict[str, Any], config: ErrorLoggingConfig) -> str:
    """Safely serialize function arguments for logging."""
    if not config.include_arguments:
        return f"<{len(arguments)} arguments>"

    if not arguments:
        return "{}"

    try:
        # Create a copy to avoid modifying original
        safe_args = {}
        for key, value in arguments.items():
            # Mask sensitive values
            if config.mask_sensitive_keys and any(
                sensitive in key.lower() for sensitive in config.sensitive_keys
            ):
                safe_args[key] = "***MASKED***"
            else:
                # Try to represent the value safely
                try:
                    # Test if value is JSON serializable
                    json.dumps(value)
                    safe_args[key] = value
                except (TypeError, ValueError):
                    # If not serializable, use string representation
                    str_repr = str(value)
                    if len(str_repr) > 50:
                        safe_args[key] = f"<{type(value).__name__}: {str_repr[:47]}...>"
                    else:
                        safe_args[key] = f"<{type(value).__name__}: {str_repr}>"

        # Serialize to JSON string
        json_str = json.dumps(safe_args, default=str, ensure_ascii=False)

        # Truncate if too long
        if len(json_str) > config.max_arg_length:
            truncated = json_str[:config.max_arg_length - 3] + "..."
            return truncated

        return json_str

    except Exception as e:
        # Fallback to basic representation
        return f"<serialization_error: {e.__class__.__name__}>"


def _truncate_error_message(error: Exception, config: ErrorLoggingConfig) -> str:
    """Safely truncate error message."""
    error_msg = str(error)
    if len(error_msg) > config.max_error_message_length:
        return error_msg[:config.max_error_message_length - 3] + "..."
    return error_msg


def structured_log_message(
    prefix: str,
    description: str,
    context: ExecutionContext,
    error: Optional[Exception] = None,
    action: str = "",
    extra_fields: Optional[Dict[str, Any]] = None,
    config: Optional[ErrorLoggingConfig] = None,
) -> str:
    """
    Create structured log message string for error handlers.

    Args:
        prefix: Action prefix in CAPS (e.g., "TIMEOUT ERROR HANDLED")
        description: Human-readable description
        context: Execution context
        error: Exception that occurred (optional)
        action: Action being taken
        extra_fields: Additional fields to include
        config: Logging configuration (uses global if None)

    Returns:
        Formatted log message string
    """
    config = config or _ERROR_LOG_CONFIG

    # Build the log message components
    components = [
        f"{prefix} | {description}",
        f"[Function: {context.function_signature.name}]",
        f"[Module: {context.function_signature.module}]",
    ]

    # Add error information if provided
    if error:
        components.extend([
            f"[Error Type: {error.__class__.__name__}]",
            f"[Error Message: {_truncate_error_message(error, config)}]",
        ])

    # Add arguments
    args_str = _safe_serialize_arguments(context.arguments, config)
    components.append(f"[Arguments: {args_str}]")

    # Add timestamp
    components.append(f"[Timestamp: {context.timestamp:.2f}]")

    # Add extra fields
    if extra_fields:
        for key, value in extra_fields.items():
            components.append(f"[{key}: {value}]")

    # Add action if provided
    if action:
        components.append(f"[Action: {action}]")

    # Join all components and return
    return " ".join(components)


class ErrorHandler(ABC):
    """Abstract base class for error handlers (Chain of Responsibility)."""

    def __init__(self, successor: "ErrorHandler"):
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
        else:
            return self._successor.handle_error(error, context)


class NoErrorHandler(ErrorHandler):
    """Null object handler that re-raises errors (terminal handler)."""

    def __init__(self):
        # No successor needed for terminal handler
        pass

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return True  # Always handles by re-raising

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Re-raise the error since no handler could process it."""
        logger.debug(
            structured_log_message(
                prefix="ERROR CHAIN EXHAUSTED",
                description="No handler found for error - chain processing complete",
                context=context,
                error=error,
                action="Re-raising original error for caller handling"
            )
        )
        raise error

    def handle_error(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle error by re-raising (terminal behavior)."""
        return self.handle(error, context)


# Singleton instance for reuse
NO_ERROR_HANDLER = NoErrorHandler()


class TimeoutErrorHandler(ErrorHandler):
    """Handler for timeout-related errors."""

    def __init__(
        self,
        default_return: Any = None,
        successor: ErrorHandler = NO_ERROR_HANDLER
    ):
        super().__init__(successor)
        self._default_return = default_return

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return isinstance(error, (TimeoutError, ConnectionError))

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle timeout error and return default value."""
        logger.warning(
            structured_log_message(
                prefix="TIMEOUT ERROR HANDLED",
                description="Function execution exceeded time limit",
                context=context,
                error=error,
                action=f"Returning default value: {self._default_return}",
                extra_fields={"Default Return": self._default_return}
            )
        )
        return self._default_return


class ValidationErrorHandler(ErrorHandler):
    """Handler for validation errors (usually re-raises)."""

    def __init__(self, successor: ErrorHandler = NO_ERROR_HANDLER):
        super().__init__(successor)

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return isinstance(error, (TypeError, ValueError, AssertionError))

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle validation error by logging and re-raising."""
        logger.error(
            structured_log_message(
                prefix="VALIDATION ERROR DETECTED",
                description="Programming error requires immediate attention",
                context=context,
                error=error,
                action="Re-raising for developer attention",
                extra_fields={"Severity": "High - Programming Error"}
            )
        )
        # Re-raise validation errors as they indicate programming errors
        raise error


class FlexibleValidationErrorHandler(ErrorHandler):
    """Handler for validation errors with configurable behavior."""

    def __init__(
        self,
        reraise_validation_errors: bool = True,
        default_return: Any = None,
        successor: ErrorHandler = NO_ERROR_HANDLER,
    ):
        super().__init__(successor)
        self._reraise_validation_errors = reraise_validation_errors
        self._default_return = default_return

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return isinstance(error, (TypeError, ValueError, AssertionError))

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle validation error based on configuration."""
        action = "Re-raising error" if self._reraise_validation_errors else "Returning default value"

        if self._reraise_validation_errors:
            logger.error(
                structured_log_message(
                    prefix="FLEXIBLE VALIDATION ERROR",
                    description="Configurable validation error handling applied",
                    context=context,
                    error=error,
                    action=action,
                    extra_fields={
                        "Reraise Config": self._reraise_validation_errors,
                        "Default Return": self._default_return,
                        "Handler Mode": "Strict"
                    }
                )
            )
        else:
            logger.warning(
                structured_log_message(
                    prefix="FLEXIBLE VALIDATION ERROR",
                    description="Configurable validation error handling applied",
                    context=context,
                    error=error,
                    action=action,
                    extra_fields={
                        "Reraise Config": self._reraise_validation_errors,
                        "Default Return": self._default_return,
                        "Handler Mode": "Graceful"
                    }
                )
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
        successor: ErrorHandler = NO_ERROR_HANDLER,
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
        logger.warning(
            structured_log_message(
                prefix="NETWORK ERROR HANDLED",
                description="Connection or network-related failure occurred",
                context=context,
                error=error,
                action=f"Returning default value after {self._retry_count} retry attempts",
                extra_fields={
                    "Retry Count": self._retry_count,
                    "Default Return": self._default_return,
                    "Error Category": "Network/Connection"
                }
            )
        )

        # In a real implementation, you might implement retry logic here
        if self._retry_count > 0:
            logger.info(
                structured_log_message(
                    prefix="NETWORK RETRY ATTEMPT",
                    description="Attempting retry for network failure",
                    context=context,
                    action=f"Will retry {self._retry_count} more times before returning default",
                    extra_fields={
                        "Retries Remaining": self._retry_count,
                        "Retry Strategy": "Exponential backoff recommended"
                    }
                )
            )
            # Note: Actual retry implementation would require access to the original function
            # This is simplified for demonstration

        return self._default_return


class BusinessLogicErrorHandler(ErrorHandler):
    """Handler for business logic errors."""

    def __init__(
        self,
        error_mapping: Optional[dict] = None,
        successor: ErrorHandler = NO_ERROR_HANDLER,
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
            logger.info(
                structured_log_message(
                    prefix="BUSINESS LOGIC ERROR MAPPED",
                    description="Custom error mapping successfully applied",
                    context=context,
                    error=error,
                    action=f"Returning mapped result: {result}",
                    extra_fields={
                        "Mapped Result": result,
                        "Mapping Strategy": "Custom error type mapping",
                        "Available Mappings": len(self._error_mapping)
                    }
                )
            )
            return result

        # Default business logic error handling
        structured_error_response = {
            "error": True,
            "error_type": "business_logic",
            "message": str(error),
            "function": context.function_signature.name,
            "context": context.arguments,
        }

        logger.error(
            structured_log_message(
                prefix="BUSINESS RULE VIOLATION",
                description="Business logic constraint failed - no mapping available",
                context=context,
                error=error,
                action="Returning structured error response",
                extra_fields={
                    "Response Type": "Structured Error Object",
                    "Contains Context": True,
                    "Error Category": "Business Logic"
                }
            )
        )

        return structured_error_response


class SecurityErrorHandler(ErrorHandler):
    """Handler for security-related errors."""

    def __init__(
        self,
        audit_logger: Optional[logging.Logger] = None,
        successor: ErrorHandler = NO_ERROR_HANDLER,
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
        incident_id = f"{context.function_signature.name}_{int(context.timestamp)}"

        # Log security incident for audit (use structured logging for audit logger too)
        self._audit_logger.critical(
            structured_log_message(
                prefix="SECURITY INCIDENT DETECTED",
                description="Potential security violation requires immediate attention",
                context=context,
                error=error,
                action="Access denied - incident logged for security review",
                extra_fields={
                    "Incident ID": incident_id,
                    "Severity": "CRITICAL",
                    "Requires Review": True,
                    "Access Denied": True
                }
            )
        )

        # Additional warning in main logger
        logger.warning(
            structured_log_message(
                prefix="SECURITY ERROR HANDLED",
                description="Security-related error processed and logged",
                context=context,
                error=error,
                action="Returning generic access denied response",
                extra_fields={
                    "Incident ID": incident_id,
                    "Audit Logged": True,
                    "Response Type": "Generic denial (no sensitive info)"
                }
            )
        )

        # Don't return sensitive information
        return {
            "error": True,
            "error_type": "security",
            "message": "Access denied",
            "incident_id": incident_id,
        }


class DefaultErrorHandler(ErrorHandler):
    """Default error handler that returns a default value."""

    def __init__(
        self,
        default_return: Any = None,
        log_errors: bool = True,
        successor: ErrorHandler = NO_ERROR_HANDLER,
    ):
        super().__init__(successor)
        self._default_return = default_return
        self._log_errors = log_errors

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        return True  # Handles all errors as catch-all handler

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle any unhandled error."""
        if self._log_errors:
            logger.error(
                structured_log_message(
                    prefix="DEFAULT ERROR HANDLER",
                    description="Unhandled error caught by fallback handler",
                    context=context,
                    error=error,
                    action=f"Returning configured default value: {self._default_return}",
                    extra_fields={
                        "Handler Type": "Fallback/Catch-all",
                        "Default Return": self._default_return,
                        "Stack Trace Available": True
                    }
                )
            )
            # Add stack trace in a separate log entry for clarity
            logger.error(
                f"STACK TRACE for {context.function_signature.name} | {error.__class__.__name__}: {str(error)}",
                exc_info=True
            )

        return self._default_return


class ConditionalErrorHandler(ErrorHandler):
    """Handler that applies conditions before handling errors."""

    def __init__(
        self,
        condition_func: Callable[[Exception, ExecutionContext], bool],
        handler_func: Callable[[Exception, ExecutionContext], Any],
        successor: ErrorHandler = NO_ERROR_HANDLER,
    ):
        super().__init__(successor)
        self._condition_func = condition_func
        self._handler_func = handler_func

    def can_handle(self, error: Exception, context: ExecutionContext) -> bool:
        """Check if condition function returns True."""
        try:
            return self._condition_func(error, context)
        except Exception as e:
            logger.warning(
                structured_log_message(
                    prefix="CONDITIONAL HANDLER ERROR",
                    description="Condition function failed during evaluation",
                    context=context,
                    error=e,  # Log the condition error, not the original error
                    action="Skipping conditional handler due to condition failure",
                    extra_fields={
                        "Original Error": error.__class__.__name__,
                        "Condition Function": getattr(self._condition_func, '__name__', 'anonymous'),
                        "Handler Skipped": True
                    }
                )
            )
            return False

    def handle(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle error using custom handler function."""
        try:
            logger.info(
                structured_log_message(
                    prefix="CONDITIONAL HANDLER TRIGGERED",
                    description="Custom condition met - applying specialized handler",
                    context=context,
                    error=error,
                    action="Executing custom handler logic",
                    extra_fields={
                        "Condition Function": getattr(self._condition_func, '__name__', 'anonymous'),
                        "Handler Function": getattr(self._handler_func, '__name__', 'anonymous'),
                        "Handler Type": "Custom conditional"
                    }
                )
            )
            return self._handler_func(error, context)
        except Exception as handler_error:
            logger.error(
                structured_log_message(
                    prefix="CONDITIONAL HANDLER FAILED",
                    description="Custom handler function encountered an error",
                    context=context,
                    error=handler_error,  # Log the handler error
                    action="Re-raising original error due to handler failure",
                    extra_fields={
                        "Original Error": f"{error.__class__.__name__}: {str(error)[:50]}",
                        "Handler Function": getattr(self._handler_func, '__name__', 'anonymous'),
                        "Fallback Action": "Re-raise original"
                    }
                )
            )
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

    def add_conditional_handler(
        self,
        condition_func: Callable[[Exception, ExecutionContext], bool],
        handler_func: Callable[[Exception, ExecutionContext], Any],
    ):
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
        handler_chain = NO_ERROR_HANDLER

        for name, handler_class, kwargs in reversed(self._handlers):
            kwargs["successor"] = handler_chain
            handler_chain = handler_class(**kwargs)

        return handler_chain


# Convenience functions for creating common error handler chains
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


# Example usage of logging configuration
def example_error_logging_setup():
    """Example of how to configure error logging for different environments."""

    # Development environment - detailed logging
    configure_error_logging(
        include_arguments=True,
        max_arg_length=300,
        max_error_message_length=200,
        mask_sensitive_keys=True,
        sensitive_keys={'password', 'token', 'secret', 'api_key'}
    )

    # Production environment - more restricted logging
    # configure_error_logging(
    #     include_arguments=False,  # Don't log arguments in production
    #     max_arg_length=100,
    #     max_error_message_length=100,
    #     mask_sensitive_keys=True,
    #     sensitive_keys={'password', 'token', 'secret', 'api_key', 'user_data'}
    # )

    # Example log output with detailed arguments:
    # ERROR - VALIDATION ERROR DETECTED | Programming error requires immediate attention
    # [Function: calculate_score] [Module: myapp.services] [Error Type: ValueError]
    # [Error Message: Score must be between 0 and 100]
    # [Arguments: {"user_id": 12345, "score": 150, "game_type": "puzzle"}]
    # [Timestamp: 1672531200.45] [Severity: High - Programming Error]
    # [Action: Re-raising for developer attention]
