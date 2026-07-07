"""Backup router — export and import APISIX configuration for disaster recovery."""
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.proxy_service import forward_request, ALLOWED_RESOURCES
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)
router = APIRouter()


class ImportResult(BaseModel):
    resource_type: str
    resource_id: str
    status: str  # "created", "updated", "failed"
    detail: Optional[str] = None


@router.get("/backup/export")
def export_config(
    resource_types: Optional[str] = Query(None, description="Comma-separated resource types to export (default: all)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export APISIX configuration as JSON. Admin only.
    
    Query params:
        resource_types: Comma-separated list (e.g., "routes,services"). Default exports all.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Determine which resources to export
    all_resources = ["routes", "services", "upstreams", "consumers", "ssl", "global_rules", "plugin_metadata"]
    if resource_types:
        resources_to_export = [r.strip() for r in resource_types.split(",") if r.strip() in all_resources]
        if not resources_to_export:
            raise HTTPException(status_code=400, detail=f"Invalid resource types. Valid: {', '.join(all_resources)}")
    else:
        resources_to_export = all_resources

    export_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": current_user.username,
        "version": "1.0.0",
        "resource_types_included": resources_to_export,
        "resources": {},
    }

    for resource_type in resources_to_export:
        try:
            response = forward_request(
                method="GET",
                resource_type=resource_type,
                sub_path="",
                body=None,
                query_params={},
                content_type="application/json",
                username=current_user.username,
            )
            if response.status_code == 200:
                export_data["resources"][resource_type] = response.json()
            else:
                export_data["resources"][resource_type] = {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            export_data["resources"][resource_type] = {"error": str(e)}

    # Log the export action
    log_action(
        db, current_user.username, "EXPORT",
        resource_type="backup",
        details=f"Exported: {', '.join(resources_to_export)}",
    )

    # Return as downloadable JSON file
    content = json.dumps(export_data, indent=2, ensure_ascii=False)
    types_label = "-".join(resources_to_export) if len(resources_to_export) <= 3 else "full"
    filename = f"apisix-backup-{types_label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/backup/import", response_model=List[ImportResult])
def import_config(
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Overwrite existing resources if they exist"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import APISIX configuration from a backup JSON file. Admin only.
    
    Reads the backup file and creates/updates each resource via the Admin API.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Read and parse the uploaded file
    try:
        content = file.file.read()
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    if "resources" not in backup_data:
        raise HTTPException(status_code=400, detail="Invalid backup format: missing 'resources' key")

    results: List[ImportResult] = []
    resources = backup_data["resources"]

    for resource_type, resource_data in resources.items():
        if resource_type not in ALLOWED_RESOURCES:
            results.append(ImportResult(
                resource_type=resource_type,
                resource_id="*",
                status="failed",
                detail=f"Unknown resource type: {resource_type}",
            ))
            continue

        if "error" in resource_data:
            results.append(ImportResult(
                resource_type=resource_type,
                resource_id="*",
                status="failed",
                detail=f"Backup had error: {resource_data['error']}",
            ))
            continue

        # Extract items from the APISIX response format
        items = _extract_items(resource_data)

        for item in items:
            item_id = item.get("id") or item.get("username") or ""
            if not item_id:
                results.append(ImportResult(
                    resource_type=resource_type,
                    resource_id="unknown",
                    status="failed",
                    detail="Item has no id",
                ))
                continue

            # Remove internal fields that shouldn't be sent back
            payload = {k: v for k, v in item.items() if k not in ("create_time", "update_time")}

            try:
                # Use PUT to create or update the resource
                body = json.dumps(payload).encode("utf-8")
                response = forward_request(
                    method="PUT",
                    resource_type=resource_type,
                    sub_path=str(item_id),
                    body=body,
                    query_params={},
                    content_type="application/json",
                    username=current_user.username,
                )

                if response.status_code in (200, 201):
                    results.append(ImportResult(
                        resource_type=resource_type,
                        resource_id=str(item_id),
                        status="created" if response.status_code == 201 else "updated",
                    ))
                elif response.status_code == 409 and not overwrite:
                    results.append(ImportResult(
                        resource_type=resource_type,
                        resource_id=str(item_id),
                        status="skipped",
                        detail="Already exists (use overwrite=true to replace)",
                    ))
                else:
                    results.append(ImportResult(
                        resource_type=resource_type,
                        resource_id=str(item_id),
                        status="failed",
                        detail=f"HTTP {response.status_code}: {response.text[:200]}",
                    ))
            except Exception as e:
                results.append(ImportResult(
                    resource_type=resource_type,
                    resource_id=str(item_id),
                    status="failed",
                    detail=str(e),
                ))

    # Log the import action
    success_count = sum(1 for r in results if r.status in ("created", "updated"))
    fail_count = sum(1 for r in results if r.status == "failed")
    log_action(
        db, current_user.username, "IMPORT",
        resource_type="backup",
        details=f"Imported from '{file.filename}': {success_count} success, {fail_count} failed",
    )

    return results


def _extract_items(resource_data: dict) -> list:
    """Extract individual items from APISIX Admin API response format."""
    # APISIX returns { "list": [ { "key": "...", "value": {...} }, ... ] }
    if "list" in resource_data:
        return [item.get("value", item) for item in resource_data["list"]]
    # Or { "node": { "nodes": [...] } }
    if "node" in resource_data and "nodes" in resource_data["node"]:
        return [node.get("value", node) for node in resource_data["node"]["nodes"]]
    # Or just an array
    if isinstance(resource_data, list):
        return resource_data
    return []
