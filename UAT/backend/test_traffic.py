"""Test traffic report."""
from app.services.traffic_report_service import get_traffic_report
result = get_traffic_report("realtimewsprovider-vendor-jwt", "2026-05-15")
print(f"Total requests: {result['total_requests']}")
print(f"Minutes with data: {len(result['minutes'])}")
print(f"Peak per minute: {result['peak_per_minute']}")
if result["minutes"]:
    print(f"First: {result['minutes'][0]}")
    print(f"Last: {result['minutes'][-1]}")
