"""Test the metrics parser against actual data."""
from app.services.metrics_service import fetch_metrics, parse_apisix_metrics

raw = fetch_metrics()
metrics = parse_apisix_metrics(raw)

print(f"route_requests keys: {list(metrics.get('route_requests', {}).keys())}")
print(f"route_requests count: {len(metrics.get('route_requests', {}))}")

# Debug: manually check what the parser sees
import re
for line in raw.splitlines():
    if "apisix_http_status" in line and not line.startswith("#"):
        parts = line.split(" ")
        if len(parts) < 2:
            print(f"  SKIP (no value): {line[:100]}")
            continue
        metric_part = parts[0]
        try:
            value = float(parts[-1])
        except ValueError:
            print(f"  SKIP (bad value): {line[:100]}")
            continue
        
        code_match = re.search(r'code="([^"]+)"', metric_part)
        route_match = re.search(r'route="([^"]+)"', metric_part)
        print(f"  code={code_match.group(1) if code_match else 'NONE'}, route={route_match.group(1) if route_match else 'NONE'}, value={value}")
