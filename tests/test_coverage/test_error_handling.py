"""Tests to increase coverage for error handling module."""

import pytest
import logging
from unittest.mock import Mock, patch, MagicMock

from callpyback.management.error_handling import (
    ErrorHandler,
    TimeoutErrorHandler,
    ValidationErrorHandler,
    FlexibleValidationErrorHandler,
    NetworkErrorHandler,
    BusinessLogicErrorHandler,
    SecurityErrorHandler,
    DefaultErrorHandler,
    ConditionalErrorHandler,
    ErrorHandlerBuilder,
    create_standard_error_chain,
    create_simple_error_chain,
    create_user_friendly_error_chain,
    create_validation_error_chain,
    create_robust_error_chain,
)
from callpyback.core.context import ExecutionContext, FunctionSignature


@pytest.fixture
def sample_context():
    """Create sample execution context."""
    signature = FunctionSignature("test_func", "test_module", ("param1",))
    return ExecutionContext(
        function_signature=signature, arguments={"param1": "test_value"}, state=None
    )


class TestTimeoutErrorHandler:
    """Test TimeoutErrorHandler implementation."""

    def test_timeout_error_handler_can_handle_timeout_error(self, sample_context):
        """Test TimeoutErrorHandler handles TimeoutError."""
        handler = TimeoutErrorHandler(default_return="timeout_default")

        error = TimeoutError("Operation timed out")
        assert handler.can_handle(error, sample_context) is True

    def test_timeout_error_handler_can_handle_connection_error(self, sample_context):
        """Test TimeoutErrorHandler handles ConnectionError."""
        handler = TimeoutErrorHandler(default_return="timeout_default")

        error = ConnectionError("Connection failed")
        assert handler.can_handle(error, sample_context) is True

    def test_timeout_error_handler_cannot_handle_other_errors(self, sample_context):
        """Test TimeoutErrorHandler doesn't handle other errors."""
        handler = TimeoutErrorHandler(default_return="timeout_default")

        error = ValueError("Not a timeout")
        assert handler.can_handle(error, sample_context) is False

    @patch("callpyback.management.error_handling.logging")
    def test_timeout_error_handler_handle(self, mock_logging, sample_context):
        """Test TimeoutErrorHandler.handle method."""
        handler = TimeoutErrorHandler(default_return="timeout_result")

        error = TimeoutError("Timed out")
        result = handler.handle(error, sample_context)

        assert result == "timeout_result"
        mock_logging.warning.assert_called_once()

    def test_timeout_error_handler_with_successor(self, sample_context):
        """Test TimeoutErrorHandler with successor chain."""
        successor = Mock()
        successor.handle_error.return_value = "successor_result"

        handler = TimeoutErrorHandler(
            default_return="timeout_result", successor=successor
        )

        # Test with timeout error (should handle itself)
        timeout_error = TimeoutError("Timeout")
        result = handler.handle_error(timeout_error, sample_context)
        assert result == "timeout_result"
        successor.handle_error.assert_not_called()

        # Test with other error (should pass to successor)
        other_error = ValueError("Not timeout")
        result = handler.handle_error(other_error, sample_context)
        assert result == "successor_result"
        successor.handle_error.assert_called_once_with(other_error, sample_context)


class TestValidationErrorHandler:
    """Test ValidationErrorHandler implementation."""

    def test_validation_error_handler_can_handle_type_error(self, sample_context):
        """Test ValidationErrorHandler handles TypeError."""
        handler = ValidationErrorHandler()

        error = TypeError("Wrong type")
        assert handler.can_handle(error, sample_context) is True

    def test_validation_error_handler_can_handle_value_error(self, sample_context):
        """Test ValidationErrorHandler handles ValueError."""
        handler = ValidationErrorHandler()

        error = ValueError("Invalid value")
        assert handler.can_handle(error, sample_context) is True

    def test_validation_error_handler_can_handle_assertion_error(self, sample_context):
        """Test ValidationErrorHandler handles AssertionError."""
        handler = ValidationErrorHandler()

        error = AssertionError("Assertion failed")
        assert handler.can_handle(error, sample_context) is True

    def test_validation_error_handler_cannot_handle_other_errors(self, sample_context):
        """Test ValidationErrorHandler doesn't handle other errors."""
        handler = ValidationErrorHandler()

        error = RuntimeError("Runtime error")
        assert handler.can_handle(error, sample_context) is False

    @patch("callpyback.management.error_handling.logging")
    def test_validation_error_handler_handle_reraises(
        self, mock_logging, sample_context
    ):
        """Test ValidationErrorHandler.handle reraises errors."""
        handler = ValidationErrorHandler()

        error = ValueError("Validation failed")

        with pytest.raises(ValueError, match="Validation failed"):
            handler.handle(error, sample_context)

        mock_logging.error.assert_called_once()


class TestFlexibleValidationErrorHandler:
    """Test FlexibleValidationErrorHandler implementation."""

    def test_flexible_validation_handler_reraise_true(self, sample_context):
        """Test FlexibleValidationErrorHandler with reraise=True."""
        handler = FlexibleValidationErrorHandler(
            reraise_validation_errors=True, default_return="default"
        )

        error = ValueError("Validation failed")

        with patch("callpyback.management.error_handling.logging"):
            with pytest.raises(ValueError):
                handler.handle(error, sample_context)

    def test_flexible_validation_handler_reraise_false(self, sample_context):
        """Test FlexibleValidationErrorHandler with reraise=False."""
        handler = FlexibleValidationErrorHandler(
            reraise_validation_errors=False, default_return="handled_error"
        )

        error = ValueError("Validation failed")

        with patch("callpyback.management.error_handling.logging"):
            result = handler.handle(error, sample_context)
            assert result == "handled_error"


class TestNetworkErrorHandler:
    """Test NetworkErrorHandler implementation."""

    def test_network_error_handler_can_handle_connection_error(self, sample_context):
        """Test NetworkErrorHandler handles ConnectionError."""
        handler = NetworkErrorHandler()

        error = ConnectionError("Network failed")
        assert handler.can_handle(error, sample_context) is True

    def test_network_error_handler_can_handle_os_error(self, sample_context):
        """Test NetworkErrorHandler handles OSError."""
        handler = NetworkErrorHandler()

        error = OSError("OS network error")
        assert handler.can_handle(error, sample_context) is True

    def test_network_error_handler_can_handle_by_name(self, sample_context):
        """Test NetworkErrorHandler handles errors by name."""
        handler = NetworkErrorHandler()

        # Create custom error with network-related name
        class HTTPError(Exception):
            pass

        error = HTTPError("HTTP failed")
        assert handler.can_handle(error, sample_context) is True

    @patch("callpyback.management.error_handling.logging")
    def test_network_error_handler_handle_with_retry(
        self, mock_logging, sample_context
    ):
        """Test NetworkErrorHandler.handle with retry count."""
        handler = NetworkErrorHandler(retry_count=3, default_return="network_default")

        error = ConnectionError("Network failed")
        result = handler.handle(error, sample_context)

        assert result == "network_default"
        mock_logging.warning.assert_called_once()
        mock_logging.info.assert_called_once()


class TestBusinessLogicErrorHandler:
    """Test BusinessLogicErrorHandler implementation."""

    def test_business_logic_handler_can_handle_by_mapping(self, sample_context):
        """Test BusinessLogicErrorHandler handles errors by mapping."""
        error_mapping = {ValueError: {"status": "error", "code": "INVALID"}}
        handler = BusinessLogicErrorHandler(error_mapping=error_mapping)

        error = ValueError("Business rule violated")
        assert handler.can_handle(error, sample_context) is True

    def test_business_logic_handler_can_handle_by_message(self, sample_context):
        """Test BusinessLogicErrorHandler handles errors by message content."""
        handler = BusinessLogicErrorHandler()

        error = RuntimeError("Business rule violation")
        assert handler.can_handle(error, sample_context) is True

    def test_business_logic_handler_can_handle_by_type_name(self, sample_context):
        """Test BusinessLogicErrorHandler handles errors by type name."""
        handler = BusinessLogicErrorHandler()

        class DomainError(Exception):
            pass

        error = DomainError("Domain logic failed")
        assert handler.can_handle(error, sample_context) is True

    def test_business_logic_handler_handle_with_mapping(self, sample_context):
        """Test BusinessLogicErrorHandler.handle with error mapping."""
        error_mapping = {ValueError: {"status": "mapped", "code": "VAL_ERROR"}}
        handler = BusinessLogicErrorHandler(error_mapping=error_mapping)

        error = ValueError("Business failed")

        with patch("callpyback.management.error_handling.logging"):
            result = handler.handle(error, sample_context)
            assert result == {"status": "mapped", "code": "VAL_ERROR"}

    def test_business_logic_handler_handle_without_mapping(self, sample_context):
        """Test BusinessLogicErrorHandler.handle without specific mapping."""
        handler = BusinessLogicErrorHandler()

        error = RuntimeError("Business rule failed")

        with patch("callpyback.management.error_handling.logging"):
            result = handler.handle(error, sample_context)
            assert result["error"] is True
            assert result["error_type"] == "business_logic"
            assert "Business rule failed" in result["message"]


class TestSecurityErrorHandler:
    """Test SecurityErrorHandler implementation."""

    def test_security_error_handler_can_handle_by_message(self, sample_context):
        """Test SecurityErrorHandler handles security-related errors by message."""
        handler = SecurityErrorHandler()

        error = RuntimeError("Permission denied")
        assert handler.can_handle(error, sample_context) is True

        error = RuntimeError("Unauthorized access")
        assert handler.can_handle(error, sample_context) is True

    def test_security_error_handler_can_handle_by_type_name(self, sample_context):
        """Test SecurityErrorHandler handles security-related errors by type name."""
        handler = SecurityErrorHandler()

        class PermissionError(Exception):
            pass

        error = PermissionError("Access denied")
        assert handler.can_handle(error, sample_context) is True

    def test_security_error_handler_handle(self, sample_context):
        """Test SecurityErrorHandler.handle method."""
        mock_logger = Mock()
        handler = SecurityErrorHandler(audit_logger=mock_logger)

        error = RuntimeError("Security violation")
        result = handler.handle(error, sample_context)

        assert result["error"] is True
        assert result["error_type"] == "security"
        assert result["message"] == "Access denied"
        assert "incident_id" in result

        mock_logger.critical.assert_called_once()


class TestDefaultErrorHandler:
    """Test DefaultErrorHandler implementation."""

    def test_default_error_handler_can_handle_any_error(self, sample_context):
        """Test DefaultErrorHandler can handle any error."""
        handler = DefaultErrorHandler()

        for error_class in [ValueError, TypeError, RuntimeError, ConnectionError]:
            error = error_class("Any error")
            assert handler.can_handle(error, sample_context) is True

    def test_default_error_handler_handle_with_logging(self, sample_context):
        """Test DefaultErrorHandler.handle with logging enabled."""
        handler = DefaultErrorHandler(default_return="default_value", log_errors=True)

        error = RuntimeError("Unhandled error")

        with patch("callpyback.management.error_handling.logging") as mock_logging:
            result = handler.handle(error, sample_context)
            assert result == "default_value"
            mock_logging.error.assert_called_once()

    def test_default_error_handler_handle_without_logging(self, sample_context):
        """Test DefaultErrorHandler.handle with logging disabled."""
        handler = DefaultErrorHandler(default_return="default_value", log_errors=False)

        error = RuntimeError("Unhandled error")

        with patch("callpyback.management.error_handling.logging") as mock_logging:
            result = handler.handle(error, sample_context)
            assert result == "default_value"
            mock_logging.error.assert_not_called()


class TestConditionalErrorHandler:
    """Test ConditionalErrorHandler implementation."""

    def test_conditional_error_handler_condition_true(self, sample_context):
        """Test ConditionalErrorHandler when condition returns True."""

        def condition(error, context):
            return "critical" in str(error).lower()

        def handler_func(error, context):
            return "handled_conditionally"

        handler = ConditionalErrorHandler(condition, handler_func)

        error = RuntimeError("Critical system error")
        assert handler.can_handle(error, sample_context) is True

        result = handler.handle(error, sample_context)
        assert result == "handled_conditionally"

    def test_conditional_error_handler_condition_false(self, sample_context):
        """Test ConditionalErrorHandler when condition returns False."""

        def condition(error, context):
            return "critical" in str(error).lower()

        def handler_func(error, context):
            return "handled_conditionally"

        handler = ConditionalErrorHandler(condition, handler_func)

        error = RuntimeError("Normal error")
        assert handler.can_handle(error, sample_context) is False

    def test_conditional_error_handler_condition_exception(self, sample_context):
        """Test ConditionalErrorHandler when condition function raises."""

        def failing_condition(error, context):
            raise RuntimeError("Condition failed")

        def handler_func(error, context):
            return "handled"

        handler = ConditionalErrorHandler(failing_condition, handler_func)

        error = ValueError("Test error")

        with patch("callpyback.management.error_handling.logging"):
            assert handler.can_handle(error, sample_context) is False

    def test_conditional_error_handler_handler_exception(self, sample_context):
        """Test ConditionalErrorHandler when handler function raises."""

        def condition(error, context):
            return True

        def failing_handler(error, context):
            raise RuntimeError("Handler failed")

        handler = ConditionalErrorHandler(condition, failing_handler)

        error = ValueError("Test error")

        with patch("callpyback.management.error_handling.logging"):
            with pytest.raises(ValueError):  # Original error re-raised
                handler.handle(error, sample_context)


class TestErrorHandlerBuilder:
    """Test ErrorHandlerBuilder implementation."""

    def test_error_handler_builder_timeout_handler(self):
        """Test ErrorHandlerBuilder.add_timeout_handler."""
        builder = ErrorHandlerBuilder()
        result = builder.add_timeout_handler("timeout_default")

        assert result is builder  # Should return self for chaining
        assert len(builder._handlers) == 1
        assert builder._handlers[0][0] == "timeout"

    def test_error_handler_builder_validation_handler_reraise(self):
        """Test ErrorHandlerBuilder.add_validation_handler with reraise=True."""
        builder = ErrorHandlerBuilder()
        result = builder.add_validation_handler(reraise=True)

        assert result is builder
        assert len(builder._handlers) == 1
        assert builder._handlers[0][0] == "validation"

    def test_error_handler_builder_validation_handler_no_reraise(self):
        """Test ErrorHandlerBuilder.add_validation_handler with reraise=False."""
        builder = ErrorHandlerBuilder()
        result = builder.add_validation_handler(reraise=False, default_return="handled")

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_flexible_validation_handler(self):
        """Test ErrorHandlerBuilder.add_flexible_validation_handler."""
        builder = ErrorHandlerBuilder()
        result = builder.add_flexible_validation_handler(
            reraise=False, default_return="flex"
        )

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_network_handler(self):
        """Test ErrorHandlerBuilder.add_network_handler."""
        builder = ErrorHandlerBuilder()
        result = builder.add_network_handler(retry_count=3, default_return="network")

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_business_logic_handler(self):
        """Test ErrorHandlerBuilder.add_business_logic_handler."""
        builder = ErrorHandlerBuilder()
        mapping = {ValueError: {"status": "error"}}
        result = builder.add_business_logic_handler(error_mapping=mapping)

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_security_handler(self):
        """Test ErrorHandlerBuilder.add_security_handler."""
        builder = ErrorHandlerBuilder()
        logger = Mock()
        result = builder.add_security_handler(audit_logger=logger)

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_conditional_handler(self):
        """Test ErrorHandlerBuilder.add_conditional_handler."""
        builder = ErrorHandlerBuilder()
        condition = lambda e, c: True
        handler_func = lambda e, c: "conditional"
        result = builder.add_conditional_handler(condition, handler_func)

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_default_handler(self):
        """Test ErrorHandlerBuilder.add_default_handler."""
        builder = ErrorHandlerBuilder()
        result = builder.add_default_handler(default_return="default", log_errors=False)

        assert result is builder
        assert len(builder._handlers) == 1

    def test_error_handler_builder_build_empty(self):
        """Test ErrorHandlerBuilder.build with no handlers."""
        builder = ErrorHandlerBuilder()
        chain = builder.build()

        assert isinstance(chain, DefaultErrorHandler)

    def test_error_handler_builder_build_chain(self):
        """Test ErrorHandlerBuilder.build with multiple handlers."""
        builder = ErrorHandlerBuilder()
        chain = (
            builder.add_timeout_handler("timeout")
            .add_validation_handler()
            .add_default_handler("default")
            .build()
        )

        assert isinstance(chain, TimeoutErrorHandler)
        # Chain should be built from last to first


class TestErrorChainFactories:
    """Test error handler chain factory functions."""

    def test_create_standard_error_chain(self):
        """Test create_standard_error_chain function."""
        chain = create_standard_error_chain(default_return="standard")
        assert isinstance(chain, SecurityErrorHandler)

    def test_create_simple_error_chain(self):
        """Test create_simple_error_chain function."""
        chain = create_simple_error_chain(default_return="simple")
        assert isinstance(chain, TimeoutErrorHandler)

    def test_create_user_friendly_error_chain(self):
        """Test create_user_friendly_error_chain function."""
        chain = create_user_friendly_error_chain(default_return="friendly")
        assert isinstance(chain, TimeoutErrorHandler)

    def test_create_validation_error_chain(self):
        """Test create_validation_error_chain function."""
        chain = create_validation_error_chain(default_return="validation")
        assert isinstance(chain, TimeoutErrorHandler)

    def test_create_robust_error_chain(self):
        """Test create_robust_error_chain function."""
        chain = create_robust_error_chain(
            default_return="robust",
            error_mapping={ValueError: {"status": "mapped"}},
            audit_logger=Mock(),
        )
        assert isinstance(chain, SecurityErrorHandler)


class TestErrorHandlerChaining:
    """Test error handler chaining behavior."""

    def test_error_handler_chain_execution(self, sample_context):
        """Test that error handler chains execute correctly."""
        # Create a chain: Timeout -> Default
        default_handler = DefaultErrorHandler(default_return="default_result")
        timeout_handler = TimeoutErrorHandler(
            default_return="timeout_result", successor=default_handler
        )

        # Test timeout error (should be handled by timeout handler)
        timeout_error = TimeoutError("Timed out")
        result = timeout_handler.handle_error(timeout_error, sample_context)
        assert result == "timeout_result"

        # Test other error (should be passed to default handler)
        other_error = ValueError("Not timeout")
        result = timeout_handler.handle_error(other_error, sample_context)
        assert result == "default_result"

    def test_error_handler_chain_no_successor_reraises(self, sample_context):
        """Test that chain without successor re-raises unhandled errors."""
        timeout_handler = TimeoutErrorHandler(default_return="timeout_result")

        other_error = ValueError("Not timeout")
        with pytest.raises(ValueError):
            timeout_handler.handle_error(other_error, sample_context)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
