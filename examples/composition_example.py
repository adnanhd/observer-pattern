from callpyback.tools import Composition


# Define some simple functions to compose
def double(x: int) -> int:
    return x * 2


def square(x: int) -> int:
    return x * x


def subtract_five(x: int) -> int:
    return x - 5


# Create a composition of functions
comp = Composition(double, square, subtract_five)

# Optionally, add a prologue and epilogue
comp.add_proloque(lambda x: x + 10).add_epiloque(lambda x: x / 2)

# Call the composed function
result = comp(3)
print(result)  # Expected output: (((((3 + 10) * 2) ** 2) - 5) / 2)

# Retrieve the composed function itself
composed_function = comp.composition
print(composed_function(3))  # Should produce the same result
