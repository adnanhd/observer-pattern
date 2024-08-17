from callpyback.basics.callbacklist import CallbackList
import time

# Create a CallbackList instance
callbackList = CallbackList(allowed_parameters={"s", "b"})

# Add a lambda function as a callback
callbackList.add_callback(
    lambda s, b: print("Got callback 1, s is %s b is %d" % (s, b))
)


# Define another function to be used as a callback
def anotherCallback(s, b):
    time.sleep(1)
    print("Got callback 2, s is %s b is %d" % (s, b))


def anotherCallback2(s, b):
    time.sleep(1)
    print("Got callback 3, s is %s b is %d" % (s, b))


def anotherCallback3(s, b):
    time.sleep(1)
    print("Got callback 4, s is %s b is %d" % (s, b))


# Add the second function as a callback
callbackList.add_callback(anotherCallback)
callbackList.add_callback(anotherCallback2)
callbackList.add_callback(anotherCallback3)

# Invoke the callbacks with the provided arguments
callbackList.run_callbacks(s="Hello world", b=True)

import abc


class Foo(abc.ABC):
    def foo(self):
        print("i am Foo")


class Bar(abc.ABC):
    def foo(self):
        print("i am Bar")


class Baz(Foo, Bar): ...


Baz().foo()
