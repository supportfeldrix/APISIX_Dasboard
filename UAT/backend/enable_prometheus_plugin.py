"""Enable the prometheus plugin on all routes to get per-route metrics.

Run this inside the backend pod:
  python enable_prometheus_plugin.py
"""
import json
import httpx
from app.config import settings

base = settings.APISIX_ADMIN_BASE_URL.rstrip("/")
headers = {"X-API-KEY": settings.APISIX_ADMIN_KEY}

# Fetch all routes
r = httpx.get(f"{base}/apisix/admin/routes", headers=headers, verify=False, timeout=10)
data = r.json()
routes = data.get("list", [])
print(f"Found {len(routes)} routes")

updated = 0
for route in routes:
    v = route.get("value", {})
    rid = v.get("id")
    name = v.get("name", "unnamed")
    plugins = v.get("plugins", {})

    if "prometheus" in plugins:
        print(f"  [{rid}] {name} — already has prometheus plugin")
        continue

    # Add prometheus plugin with prefer_name=true for readable labels
    plugins["prometheus"] = {"prefer_name": True}
    
    # PATCH the route to add the plugin
    patch_url = f"{base}/apisix/admin/routes/{rid}"
    patch_data = {"plugins": plugins}
    
    resp = httpx.patch(
        patch_url,
        json=patch_data,
        headers=headers,
        verify=False,
        timeout=10,
    )
    
    if resp.status_code < 300:
        print(f"  [{rid}] {name} — prometheus plugin ENABLED ✓")
        updated += 1
    else:
        print(f"  [{rid}] {name} — FAILED ({resp.status_code}): {resp.text[:100]}")

print(f"\nDone. Updated {updated}/{len(routes)} routes.")
print("Per-route metrics will appear after the next request to each route.")
