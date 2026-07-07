"""Property-based tests for metrics service."""
import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.services.metrics_service import parse_prometheus, PodMetrics


# Strategy: generate valid Prometheus text format with random pods, CPU, and memory values
@st.composite
def prometheus_text_strategy(draw):
    """Generate valid Prometheus text format with container_cpu and memory metrics."""
    # Generate 1-5 unique pod names
    pod_names = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(
                    whitelist_categories=("Ll", "Nd"),
                    whitelist_characters="-",
                ),
            ),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    lines = []
    pod_data = {}

    for pod in pod_names:
        cpu = draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False))
        mem = draw(st.integers(min_value=0, max_value=10_000_000_000))
        lines.append(f'container_cpu_usage_seconds_total{{pod="{pod}",namespace="default"}} {cpu}')
        lines.append(f'container_memory_working_set_bytes{{pod="{pod}",namespace="default"}} {float(mem)}')
        pod_data[pod] = {"cpu": cpu, "mem": mem}

    text = "\n".join(lines)
    return text, pod_data


# Feature: apisix-dashboard, Property 16: Prometheus metrics parser extracts CPU and memory per pod
@given(data=prometheus_text_strategy())
@h_settings(max_examples=25)
def test_property_16_prometheus_parser_extracts_correct_values(data):
    """Property 16: Prometheus metrics parser extracts CPU and memory per pod."""
    text, expected_pods = data

    results = parse_prometheus(text)

    # Assert the number of PodMetrics objects matches the number of unique pods in the input
    assert len(results) == len(expected_pods)

    # Build a lookup from results
    results_by_pod = {r.pod: r for r in results}

    # Assert parse_prometheus correctly extracts the CPU and memory values grouped by pod name
    for pod_name, expected in expected_pods.items():
        assert pod_name in results_by_pod, f"Pod {pod_name} not found in results"
        pod_metric = results_by_pod[pod_name]
        assert abs(pod_metric.cpu_usage - expected["cpu"]) < 0.001, (
            f"CPU mismatch for {pod_name}: got {pod_metric.cpu_usage}, expected {expected['cpu']}"
        )
        assert pod_metric.memory_bytes == expected["mem"], (
            f"Memory mismatch for {pod_name}: got {pod_metric.memory_bytes}, expected {expected['mem']}"
        )
