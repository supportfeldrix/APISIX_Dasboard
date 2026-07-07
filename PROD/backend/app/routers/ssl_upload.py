"""SSL certificate file upload router."""
import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.proxy_service import forward_request
from app.utils.pem_validator import validate_pem_cert, validate_pem_key

logger = logging.getLogger(__name__)
router = APIRouter()

# Constants
MAX_FILE_SIZE = 1_048_576  # 1 MB
ALLOWED_EXTENSIONS = {".pem", ".crt", ".cer", ".key"}


def _validate_file_extension(filename: str | None) -> None:
    """Raise 422 if the file extension is not in the allowed set."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File extension not allowed. Accepted: .pem, .crt, .cer, .key",
        )
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File extension not allowed. Accepted: .pem, .crt, .cer, .key",
        )


def _validate_file_size(content: bytes, filename: str) -> None:
    """Raise 413 if the file content exceeds the maximum allowed size."""
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed (1 MB)",
        )


def _decode_utf8(content: bytes, filename: str) -> str:
    """Decode file content as UTF-8 or raise 422."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File content is not valid UTF-8 text",
        )


@router.post("/ssl/upload")
async def upload_ssl_files(
    cert_file: UploadFile | None = File(None),
    key_file: UploadFile | None = File(None),
    snis: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload SSL certificate and/or key files and forward to APISIX Admin API."""
    # Validate at least one file is provided
    if cert_file is None and key_file is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one file (certificate or key) must be provided",
        )

    payload: dict = {}

    # Process certificate file
    if cert_file is not None:
        _validate_file_extension(cert_file.filename)
        cert_content = await cert_file.read()
        _validate_file_size(cert_content, cert_file.filename or "cert_file")
        cert_text = _decode_utf8(cert_content, cert_file.filename or "cert_file")
        if not validate_pem_cert(cert_text):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid PEM certificate format",
            )
        payload["cert"] = cert_text

    # Process key file
    if key_file is not None:
        _validate_file_extension(key_file.filename)
        key_content = await key_file.read()
        _validate_file_size(key_content, key_file.filename or "key_file")
        key_text = _decode_utf8(key_content, key_file.filename or "key_file")
        if not validate_pem_key(key_text):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid PEM private key format",
            )
        payload["key"] = key_text

    # Parse snis into array
    if snis.strip():
        snis_list = [s.strip() for s in snis.split(",") if s.strip()]
        if snis_list:
            payload["snis"] = snis_list

    # Forward to APISIX Admin API via proxy_service
    import json

    body_bytes = json.dumps(payload).encode("utf-8")

    try:
        apisix_response = forward_request(
            method="POST",
            resource_type="ssl",
            sub_path="",
            body=body_bytes,
            query_params={},
            content_type="application/json",
            username=current_user.username,
        )
    except HTTPException:
        raise

    # Return APISIX response to client
    if apisix_response.status_code >= 400:
        return JSONResponse(
            content=apisix_response.json() if apisix_response.headers.get("content-type", "").startswith("application/json") else {"detail": apisix_response.text},
            status_code=apisix_response.status_code,
        )

    try:
        response_data = apisix_response.json()
    except Exception:
        response_data = {"raw": apisix_response.text}

    return JSONResponse(
        content={
            "status": "success",
            "apisix_response": response_data,
        },
        status_code=apisix_response.status_code,
    )
