import threading
from functools import wraps

class Monitor:
    def __init__(self):
        self._lock = threading.Lock()

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self._lock:
                result = func(*args, **kwargs)
            return result
        return wrapper

class HoareMonitor(Monitor):
    def __init__(self):
        super().__init__()
        self._condition = threading.Condition(self._lock)
        self._is_condition_met = False

    def wait(self):
        with self._lock:
            while not self._is_condition_met:
                self._condition.wait()

    def signal(self):
        with self._lock:
            self._is_condition_met = True
            self._condition.notify_all()

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self._lock:
                while not self._is_condition_met:
                    self._condition.wait()
                result = func(*args, **kwargs)
            return result
        return wrapper

class MesaMonitor(Monitor):
    def __init__(self):
        super().__init__()
        self._condition = threading.Condition(self._lock)

    def wait(self):
        with self._lock:
            self._condition.wait()

    def signal(self):
        with self._lock:
            self._condition.notify()

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self._lock:
                result = func(*args, **kwargs)
            return result
        return wrapper

# Example usage of the Monitor, HoareMonitor, and MesaMonitor
monitor = Monitor()
hoare_monitor = HoareMonitor()
mesa_monitor = MesaMonitor()

@monitor
def function_a():
    print("Function A is executing")

@monitor
def function_b():
    print("Function B is executing")

@hoare_monitor
def function_c():
    print("Function C is executing after condition is met (Hoare)")

@mesa_monitor
def function_d():
    print("Function D is executing after condition is signaled (Mesa)")

# Example of using the monitors:
# function_a and function_b cannot execute simultaneously
# function_c will execute when the condition is signaled using hoare_monitor.signal()
# function_d will execute when the condition is signaled using mesa_monitor.signal()
