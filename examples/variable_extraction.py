#!/usr/bin/env python3
"""
Variable Extraction Example
Demonstrates capturing local variables during function execution.
"""

from callpyback import CallPyBack, on_completion

# Global data storage
captured_data = []


def analyze_variables(local_variables):
    """Analyze and store captured variables."""
    if local_variables:
        # Filter out null variables (not found)
        valid_vars = {
            k: v
            for k, v in local_variables.items()
            if not str(v).startswith("<Variable")
        }

        analysis = {
            "total_vars": len(local_variables),
            "valid_vars": len(valid_vars),
            "numeric_vars": sum(
                1 for v in valid_vars.values() if isinstance(v, (int, float))
            ),
            "string_vars": sum(1 for v in valid_vars.values() if isinstance(v, str)),
            "variables": valid_vars,
        }

        captured_data.append(analysis)
        print(f"📋 Captured {analysis['valid_vars']} variables:")
        for name, value in valid_vars.items():
            print(f"    {name} = {value} ({type(value).__name__})")


@CallPyBack(
    observers=[on_completion(analyze_variables)],
    variable_names=[
        "input_data",
        "processed",
        "result_type",
        "final_output",
        "step_count",
    ],
)
def data_processing_pipeline(data, transform_type="upper"):
    """Complex data processing with multiple intermediate variables."""
    input_data = data  # noqa
    step_count = 0

    # Step 1: Initial processing
    step_count += 1
    if transform_type == "upper":
        processed = data.upper() if isinstance(data, str) else str(data).upper()
    elif transform_type == "reverse":
        processed = data[::-1] if isinstance(data, str) else str(data)[::-1]
    elif transform_type == "numeric":
        processed = len(data) if isinstance(data, str) else abs(data)
    else:
        processed = data

    # Step 2: Type analysis
    step_count += 1
    result_type = type(processed).__name__

    # Step 3: Final formatting
    step_count += 1
    final_output = f"[{result_type}] {processed}"

    return final_output


if __name__ == "__main__":
    print("=== Variable Extraction Example ===")

    # Test different data processing scenarios
    test_cases = [
        ("hello world", "upper"),
        ("python rocks", "reverse"),
        ("test string", "numeric"),
        (12345, "upper"),
        (-99, "numeric"),
        ("unknown", "default"),
    ]

    print("Processing data with variable extraction:")
    for data, transform in test_cases:
        result = data_processing_pipeline(data, transform)
        print(f"  Input: {data} ({type(data).__name__})")
        print(f"  Transform: {transform}")
        print(f"  Output: {result}")
        print()

    # Summary of captured data
    print("Variable Extraction Summary:")
    print(f"  Total executions: {len(captured_data)}")

    total_vars = sum(analysis["valid_vars"] for analysis in captured_data)
    total_numeric = sum(analysis["numeric_vars"] for analysis in captured_data)
    total_string = sum(analysis["string_vars"] for analysis in captured_data)

    print(f"  Total variables captured: {total_vars}")
    print(f"  Numeric variables: {total_numeric}")
    print(f"  String variables: {total_string}")

    # Show variable evolution across executions
    print("\nVariable Evolution:")
    for i, analysis in enumerate(captured_data):
        print(f"  Execution {i+1}: {analysis['valid_vars']} vars captured")
        if "step_count" in analysis["variables"]:
            print(f"    Processing steps: {analysis['variables']['step_count']}")
