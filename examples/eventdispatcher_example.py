from callpyback.basics.eventdispatcher import EventDispatcher
from callpyback.basics.thread_policy import SinglePolicy, ThreadingPolicy
from enum import Enum


class EventType(Enum):
    EVENT_TYPE_3 = "event_3"
    EVENT_TYPE_5 = "event_5"


# Create an EventDispatcher with SinglePolicy
dispatcher = EventDispatcher(policy=ThreadingPolicy(), allowed_parameters={"s", "b"})

# Append listeners for different event types
dispatcher.append_listener(
    EventType.EVENT_TYPE_3, lambda s, b: print("Got event 3, s is %s b is %d" % (s, b))
)
dispatcher.append_listener(
    EventType.EVENT_TYPE_5, lambda s, b: print("Got event 5, s is %s b is %d" % (s, b))
)
dispatcher.append_listener(
    EventType.EVENT_TYPE_5,
    lambda s, b: print("Got another event 5, s is %s b is %d" % (s, b)),
)

# Dispatch the events, the first argument is always the event type
dispatcher.dispatch(EventType.EVENT_TYPE_3, s="Hello", b=True)
dispatcher.dispatch(EventType.EVENT_TYPE_5, s="World", b=False)
