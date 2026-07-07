"""Check route plugins configuration."""
import httpx
from app.config import settings

base = settings.APISIX_ADMIN_BASE_URL.rstrip("/")
r = httpx.get(
    f"{base}/apisix/admin/routes",
    headers={"X-API-KEY": settings.APISIX_ADMIN_KEY},
    verify=False,
    timeout=10,
)
data = r.json()
routes = data.get("list", [])
print(f"Total routes: {len(routes)}")
for route in routes[:5]:
    v = route.get("value", {})
    rid = v.get("id", "?")
    name = v.get("name", "unnamed")
    plugins = list(v.get("plugins", {}).keys())
    print(f"  {rid}: {name} -> plugins: {plugins}")
