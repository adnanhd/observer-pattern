from callpyback.basics import CallbackHandler, delegatedmethod, ThreadingPolicy


class Metric:
    @delegatedmethod
    def compute(self, x, y):
        print(f"Metric.compute: x={x}, y={y}")

    @delegatedmethod
    def update(self):
        print("Metric.update")


# Create a Metric instance
metric = Metric()

# Create a Handler with ThreadingPolicy
handler = CallbackHandler(policy=ThreadingPolicy())

# Add delegations for 'compute' and 'update'
handler.add_delegation("compute", allowed_parameters={"x", "y"})
handler.add_delegation("update", allowed_parameters=set())


# Define a standalone function for 'compute'
def compute(x, y):
    print(f"Standalone compute: x={x}, y={y}")


# Delegate the standalone function and class methods
handler.delegate_function(compute=compute)
handler.delegate_class(metric)

# Execute the delegated 'compute' and 'update' actions
handler.execute("compute", x=12, y=10)
handler.execute("update")
