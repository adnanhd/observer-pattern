from callpyback.utils import background_callpyback
from callpyback.callpyback import CallPyBack

custom_callpyback = CallPyBack(
    default_return="default",
    exception_classes=(RuntimeError,),
    pass_vars=("a",),
)


@custom_callpyback.on_call
def on_call(func, func_kwargs):
    print("-----ON CALL CALLBACK-----")
    func_kwargs_repr = ", ".join(f"{key}={val}" for key, val in func_kwargs.items())
    print(f"Function `{func.__name__}` called with parameters: {func_kwargs_repr}.\n")


@custom_callpyback.on_success
def on_success1(func, func_result, func_kwargs):
    print("-----ON SUCCESS CALLBACK-----")
    func_kwargs_repr = ", ".join(f"{key}={val}" for key, val in func_kwargs.items())
    print(f"Function `{func.__name__}` successfully done with a result: {func_result}.")
    print(f"Was called with parameters: {func_kwargs_repr}\n")


@custom_callpyback.on_success
def on_success2(func, func_result, func_kwargs):
    print("-----ON SUCCESS CALLBACK-----")
    func_kwargs_repr = ", ".join(f"{key}={val}" for key, val in func_kwargs.items())
    print(f"Function `{func.__name__}` successfully done with a result: {func_result}.")
    print(f"Was called with parameters: {func_kwargs_repr}\n")


@custom_callpyback.on_failure
def on_failure(func, func_exception, func_kwargs):
    print("-----ON FAILURE CALLBACK-----")
    func_kwargs_repr = ", ".join(f"{key}={val}" for key, val in func_kwargs.items())
    print(f"Function `{func.__name__} failed with an error: {func_exception}!")
    print(f"Was called with parameters: {func_kwargs_repr}\n")


@custom_callpyback.on_end
def on_end(func, func_result, func_exception, func_kwargs, func_scope_vars):
    print("-----ON END CALLBACK-----")
    func_kwargs_repr = ", ".join(f"{key}={val}" for key, val in func_kwargs.items())
    func_scope_vars_repr = ", ".join(
        f"{key}={val}" for key, val in func_scope_vars.items()
    )
    if func_exception:
        print(f"Function `{func.__name__} failed with an error: {func_exception}!")
    else:
        print("No exception was raised")
    print(f"Function `{func.__name__}` done with a result: {func_result}.")
    print(f"Was called with parameters: {func_kwargs_repr}")
    print(f"Local variables of the function: {func_scope_vars_repr}")


@custom_callpyback
def method(x, y, z=None):
    print("Hello world")
    a = 42
    return x + y


result = method(1, 2)
print(f"Result: {result}")
