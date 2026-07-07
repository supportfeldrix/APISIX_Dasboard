"""Test PROD traffic report."""
from app.services.traffic_report_service import get_traffic_report
result = get_traffic_report("593676047602418605", "2026-05-15")
print(f"Total requests: {result.get('total_requests', 0)}")
print(f"Minutes: {len(result.get('minutes', []))}")
print(f"Error: {result.get('error', 'none')}")
if result.get("minutes"):
    print(f"First: {result['minutes'][0]}")
