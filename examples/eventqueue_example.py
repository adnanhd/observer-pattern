from enum import Enum
from callpyback import EventQueue, SinglePolicy


class Events(Enum):
    event_1 = "event_1"
    event_2 = "event_2"


# Create an EventQueue with SinglePolicy
queue = EventQueue(policy=SinglePolicy(), allowed_parameters={"s", "n"})

# Append listeners for different event types
queue.append_listener(
    Events.event_1, lambda s, n: print("Got event 1, s is %s n is %d" % (s, n))
)
queue.append_listener(
    Events.event_2, lambda s, n: print("Got event 2, s is %s n is %d" % (s, n))
)
queue.append_listener(
    Events.event_2, lambda s, n: print("Got another event 2, s is %s n is %d" % (s, n))
)

# Enqueue the events, the first argument is always the event type.
# The listeners are not triggered during enqueue.
queue.enqueue(Events.event_1, s="Hello", n=38)
queue.enqueue(Events.event_2, s="World", n=58)

# Process the event queue, dispatch all queued events.
queue.process()
