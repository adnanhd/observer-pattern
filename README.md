# CallPyBack 2.0 - Advanced Callback Decorator

A theoretically sound, production-ready callback decorator system implementing formal design patterns and addressing common limitations in callback architectures.

## 🚀 Features

- **🏗️ Formal Design Patterns**: Observer, State Machine, Chain of Responsibility, Strategy
- **🔒 Thread-Safe**: Concurrent execution with proper synchronization
- **🧠 Memory Safe**: Weak references prevent memory leaks
- **🔧 Type Safe**: Full static type checking with protocols (Python 3.8+)
- **⚡ Performance**: O(log n) operations with efficient data structures
- **🧪 Testable**: Dependency injection enables comprehensive testing
- **📊 Observable**: Built-in metrics and performance monitoring
- **🛡️ Robust**: Error isolation with circuit breaker patterns

## 📦 Installation

```bash
pip install callpyback
```

## 🏃‍♂️ Quick Start

```python
from callpyback import CallPyBack, on_call, on_success, on_failure

# Basic usage
@CallPyBack(observers=[
    on_call(lambda ctx: print(f"Calling {ctx.function_signature.name}")),
    on_success(lambda result: print(f"Success: {result.value}")),
    on_failure(lambda result: print(f"Error: {result.exception}"))
])
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

result = divide(10, 2)  # Prints call and success messages
# Output:
# Calling divide
# Success: 5.0
```

## 🔧 Advanced Features

### Variable Extraction
Capture local variables from function execution:

```python
@CallPyBack(
    observers=[on_success(lambda local_variables: print(f"Variables: {local_variables}"))],
    variable_names=['intermediate', 'final']
)
def calculation(x):
    intermediate = x * 2
    final = intermediate + 10
    return final

calculation(5)
# Output: Variables: {'intermediate': 10, 'final': 20}
```

### Custom Observers
Create sophisticated monitoring systems:

```python
from callpyback import BaseObserver, ExecutionContext

class DatabaseObserver(BaseObserver):
    def update(self, context: ExecutionContext) -> None:
        # Log to database
        self.db.log(context.function_signature.name, context.timestamp)

@CallPyBack(observers=[DatabaseObserver()])
def important_function():
    return "critical result"
```

### Built-in Observers
Leverage ready-made observers for common use cases:

```python
from callpyback.observers.builtin import LoggingObserver, MetricsObserver, TimingObserver

@CallPyBack(observers=[
    LoggingObserver(),              # Structured logging
    MetricsObserver(),              # Performance metrics
    TimingObserver(threshold=1.0)   # Slow execution alerts
])
def monitored_function():
    return "result"
```

### Error Handling
Sophisticated error management with fallback values:

```python
@CallPyBack(
    observers=[on_failure(handle_error)],
    exception_classes=(ValueError, TypeError),
    default_return="fallback_value"
)
def risky_function():
    raise ValueError("Something went wrong")
    
result = risky_function()  # Returns "fallback_value"
```

### Thread Safety
Built-in support for concurrent execution:

```python
@CallPyBack(
    observers=[MetricsObserver()],
    enable_async_observers=True  # Observers run in background
)
def concurrent_function(data):
    return process_data(data)

# Safe to call from multiple threads
```

## 🏛️ Architecture

CallPyBack 2.0 is built on solid theoretical foundations:

### Design Patterns
- **Observer Pattern**: Decoupled event notifications with priority ordering
- **State Machine**: Formal execution flow management with validation
- **Strategy Pattern**: Pluggable algorithms for variable extraction and error handling
- **Chain of Responsibility**: Composable error handling chains
- **Repository Pattern**: Observer lifecycle management with weak references
- **Factory Pattern**: Convenient observer creation functions

### Core Components
- **ExecutionContext**: Immutable state container with full execution information
- **StateMachine**: Thread-safe state transitions with validation
- **ObserverManager**: Concurrent observer coordination with error isolation
- **VariableExtractor**: Safe local variable capture using `sys.setprofile`
- **ErrorHandler**: Chainable error handling with circuit breaker patterns

## 📊 Performance

CallPyBack 2.0 is optimized for production use:

- **Observer Lookup**: O(log n) with indexed priority queues
- **Memory Usage**: Weak references prevent observer memory leaks
- **Concurrency**: Lock-free operations where possible
- **Error Isolation**: Observer failures don't impact function execution
- **Variable Extraction**: Minimal overhead with optional extraction

## 🧪 Testing

CallPyBack provides comprehensive testing support:

```python
from callpyback.core.time_sources import MockTimeSource

# Mock time for deterministic testing
mock_time = MockTimeSource(1000.0)
decorator = CallPyBack(time_source=mock_time)

@decorator
def test_function():
    mock_time.advance(0.5)  # Simulate execution time
    return "result"

# Execution time will be exactly 0.5 seconds
```

## 📈 Migration from CallPyBack 1.x

CallPyBack 2.0 provides backward compatibility:

```python
# Old way (still works)
@CallPyBack(
    on_call=lambda f, kwargs: print("called"),
    on_success=lambda f, result: print("success")
)
def my_function():
    return "result"

# New way (recommended)
@CallPyBack(observers=[
    on_call(lambda ctx: print("called")),
    on_success(lambda result: print("success"))
])
def my_function():
    return "result"
```

## 🔍 Monitoring & Observability

### Built-in Metrics
```python
metrics = MetricsObserver()

@CallPyBack(observers=[metrics])
def monitored_function():
    return "result"

# Get comprehensive metrics
stats = metrics.get_metrics()
print(f"Total executions: {stats['total_executions']}")
print(f"Average time: {stats['average_execution_time']:.3f}s")
```

### Performance Alerts
```python
timing = TimingObserver(threshold=0.1)  # 100ms threshold

@CallPyBack(observers=[timing])
def potentially_slow_function():
    time.sleep(0.2)  # Will trigger slow execution alert
    return "result"
```

## 🛠️ Development

### Setup
```bash
git clone https://github.com/callpyback/callpyback
cd callpyback
pip install -e ".[dev]"
```

### Testing
```bash
# Run tests
pytest

# Run with coverage
pytest --cov=callpyback --cov-report=html

# Type checking
mypy callpyback/

# Code formatting
black callpyback/
isort callpyback/
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Add tests for new functionality
4. Ensure all tests pass (`pytest`)
5. Format code (`black . && isort .`)
6. Submit a pull request

## 📚 Documentation

- [API Reference](https://callpyback.readthedocs.io/api/)
- [User Guide](https://callpyback.readthedocs.io/guide/)
- [Examples](examples/)
- [Migration Guide](https://callpyback.readthedocs.io/migration/)

## 🆚 Comparison with Other Solutions

| Feature | CallPyBack 2.0 | Decorators | functools | Custom Solutions |
|---------|----------------|------------|-----------|------------------|
| Type Safety | ✅ Full | ❌ None | ❌ None | ⚠️ Manual |
| Thread Safety | ✅ Built-in | ❌ Manual | ❌ Manual | ⚠️ Manual |
| Memory Safety | ✅ Weak refs | ❌ Manual | ❌ Manual | ⚠️ Manual |
| Error Isolation | ✅ Circuit breaker | ❌ None | ❌ None | ⚠️ Manual |
| Performance | ✅ O(log n) | ⚠️ O(n) | ⚠️ O(n) | ❓ Varies |
| Extensibility | ✅ Plugin system | ❌ Limited | ❌ Limited | ❓ Varies |
| Testing | ✅ DI + Mocks | ❌ Difficult | ❌ Difficult | ⚠️ Manual |

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by the Gang of Four design patterns
- Built on solid software engineering principles
- Community feedback and contributions

---

**CallPyBack 2.0** - Transform your Python functions into observable, robust, and maintainable components with enterprise-grade callback management.
