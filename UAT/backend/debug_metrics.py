"""Debug: check what the metrics parser sees."""
import httpx
import re

url = "http://apisix-metrics.cro-apisix-uat.svc.cluster.local:9091/apisix/prometheus/metrics"
r = httpx.get(url, timeout=10)
print(f"Status: {r.status_code}, Body length: {len(r.text)}")

lines = [l for l in r.text.splitlines() if "apisix_http_status" in l and not l.startswith("#")]
print(f"apisix_http_status lines: {len(lines)}")

if lines:
    print(f"\nFirst 3 lines (repr):")
    for l in lines[:3]:
        print(f"  {repr(l[:250])}")

    # Try parsing
    route_metrics = {}
    for line in lines:
        parts = line.split(" ")
        if len(parts) < 2:
            print(f"  SKIP (no space split): {line[:100]}")
            continue
        metric_part = parts[0]
        try:
            value = float(parts[-1])
        except ValueError:
            print(f"  SKIP (bad value): {parts[-1]}")
            continue
        route_match = re.search(r'route="([^"]+)"', metric_part)
        code_match = re.search(r'code="([^"]+)"', metric_part)
        if not route_match or not code_match:
            print(f"  SKIP (no route/code match): {metric_part[:150]}")
            continue
        route_id = route_match.group(1)
        code = code_match.group(1)
        if route_id not in route_metrics:
            route_metrics[route_id] = {}
        route_metrics[route_id][code] = route_metrics[route_id].get(code, 0) + value

    print(f"\nParsed routes: {list(route_metrics.keys())}")
    for route, codes in route_metrics.items():
        print(f"  {route}: {codes}")
else:
    print("\nNO apisix_http_status lines! Checking first 10 non-comment lines:")
    non_comment = [l for l in r.text.splitlines() if l and not l.startswith("#")]
    for l in non_comment[:10]:
        print(f"  {l[:150]}")
