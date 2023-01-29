import sys
import inspect
import asyncio


DEFAULT_ON_SUCCESS_LAMBDA = lambda *a, **k: None
DEFAULT_ON_FAILURE_LAMBDA = lambda *a, **l: None
DEFAULT_ON_END_LAMBDA = lambda *a, **k: None


class CallPyBack:
    def __init__(
        self,
        on_success=DEFAULT_ON_SUCCESS_LAMBDA,
        on_failure=DEFAULT_ON_FAILURE_LAMBDA,
        on_end=DEFAULT_ON_END_LAMBDA,
        default_return=None,
        pass_vars=[],
    ):
        self.on_success = on_success
        self.on_failure = on_failure
        self.on_end = on_end
        self.default_return = default_return
        self.pass_vars = pass_vars
        self.local_vars = {}

    def run_success_func(self, func_result, func_args, func_kwargs):
        success_kwargs = self.get_success_kwargs(func_result, func_args, func_kwargs)
        if inspect.iscoroutinefunction(self.on_success):
            asyncio.run(self.on_success(**success_kwargs))
        else:
            self.on_success(**success_kwargs)

    def run_failure_func(self, func_exception, func_args, func_kwargs):
        failure_kwargs = self.get_failure_kwargs(func_exception, func_args, func_kwargs)
        if inspect.iscoroutinefunction(self.on_failure):
            asyncio.run(self.on_failure(**failure_kwargs))
        else:
            self.on_failure(**failure_kwargs)

    def run_on_end_func(
        self, func_result, func_exception, func_args, func_kwargs, func_scope_vars
    ):
        on_end_kwargs = self.get_on_end_kwargs(
            func_result, func_exception, func_args, func_kwargs, func_scope_vars
        )
        if inspect.iscoroutinefunction(self.on_end):
            asyncio.run(self.on_end(**on_end_kwargs))
        else:
            self.on_end(**on_end_kwargs)

    def __call__(self, func):
        def tracer(frame, event, arg):
            if event == "return":
                self.local_vars = frame.f_locals.copy()

        def wrapper(*func_args, **func_kwargs):
            sys.setprofile(tracer)
            func_exception, func_result, func_scope_vars = None, None, []
            try:
                func_result = func(*func_args, **func_kwargs)
                func_scope_vars = self.get_func_scope_vars()
                self.run_success_func(func_result, func_args, func_kwargs)
                return func_result
            except Exception as ex:
                func_exception = ex
                func_scope_vars = self.get_func_scope_vars()
                self.run_failure_func(func_exception, func_args, func_kwargs)
                return self.default_return
            finally:
                sys.setprofile(None)
                if self.is_on_end_func_defined():
                    raise func_exception
                self.run_on_end_func(
                    func_result, func_exception, func_args, func_kwargs, func_scope_vars
                )
                return func_result if not func_exception else self.default_return

        return wrapper

    def get_func_scope_vars(self):
        func_scope_vars = {}
        for var_name in self.pass_vars:
            func_scope_vars[var_name] = self.local_vars.get(var_name, "<not-found>")
        self.local_vars = {}
        return func_scope_vars

    def is_on_end_func_defined(self):
        return (
            isinstance(self.on_end, type(DEFAULT_ON_END_LAMBDA))
            and self.on_end.__name__ == DEFAULT_ON_END_LAMBDA.__name__
            and self.on_end == DEFAULT_ON_END_LAMBDA
        )

    def get_success_kwargs(self, func_result, func_args, func_kwargs):
        kwargs = {}
        params = inspect.signature(self.on_success).parameters
        if "func_result" in params:
            kwargs["func_result"] = func_result
        if "func_args" in params:
            kwargs["func_args"] = func_args
        if "func_kwargs" in params:
            kwargs["func_kwargs"] = func_kwargs
        return kwargs

    def get_failure_kwargs(self, func_exception, func_args, func_kwargs):
        kwargs = {}
        params = inspect.signature(self.on_failure).parameters
        if "func_exception" in params:
            kwargs["func_exception"] = func_exception
        if "func_args" in params:
            kwargs["func_args"] = func_args
        if "func_kwargs" in params:
            kwargs["func_kwargs"] = func_kwargs
        return kwargs

    def get_on_end_kwargs(
        self, func_result, func_exception, func_args, func_kwargs, func_scope_vars
    ):
        kwargs = {}
        params = inspect.signature(self.on_end).parameters
        if "func_result" in params:
            kwargs["func_result"] = func_result
        if "func_exception" in params:
            kwargs["func_exception"] = func_exception
        if "func_args" in params:
            kwargs["func_args"] = func_args
        if "func_kwargs" in params:
            kwargs["func_kwargs"] = func_kwargs
        if "func_scope_vars" in params:
            kwargs["func_scope_vars"] = func_scope_vars
        return kwargs
