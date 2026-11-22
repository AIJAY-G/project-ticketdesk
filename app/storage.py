import os
import re
import uuid
import shutil
import logging
from pathlib import Path
from urllib.parse import quote
import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile, HTTPException

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Validation rules
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".txt", ".log", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB in bytes
PRESIGNED_URL_EXPIRATION = 900     # 15 minutes in seconds

# S3 Object Key Configuration (Matches Lambda event notification filter prefix)
S3_ATTACHMENT_PREFIX = "attachments/"


def get_s3_bucket() -> str | None:
    """Returns the configured S3 bucket name from environment, or None if unset."""
    bucket = os.getenv("S3_BUCKET_NAME")
    return bucket.strip() if bucket and bucket.strip() else None


def get_aws_region() -> str:
    """Returns the configured AWS region, defaulting to ap-south-1."""
    return os.getenv("AWS_REGION", "ap-south-1").strip()


def is_s3_enabled() -> bool:
    """Returns True if Amazon S3 is configured for attachment storage."""
    return get_s3_bucket() is not None


def get_s3_client():
    """
    Returns a boto3 S3 client using environment configuration.
    In EC2 deployment, boto3 automatically uses the IAM Instance Profile.
    Never hardcode AWS credentials in code or repository files.
    """
    return boto3.client("s3", region_name=get_aws_region())


def format_s3_key(filename_or_key: str) -> str:
    """
    Constructs a canonical S3 object key matching the Lambda notification
    filter prefix 'attachments/'.
    Guarantees the key format: 'attachments/<UUID>_<sanitized_filename>'
    """
    clean_name = filename_or_key.strip().lstrip("/")
    if clean_name.startswith(S3_ATTACHMENT_PREFIX):
        return clean_name
    return f"{S3_ATTACHMENT_PREFIX}{clean_name}"


def sanitize_filename(filename: str) -> tuple[str, str]:
    """
    Sanitizes an incoming filename and validates its extension.
    Returns (sanitized_base_name, lower_case_extension).
    Raises HTTPException(400) if the extension is not in ALLOWED_EXTENSIONS.
    """
    # Strip any directory path components to prevent path traversal
    base_name = os.path.basename(filename)
    stem, ext = os.path.splitext(base_name)
    ext_lower = ext.lower()

    if ext_lower not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' is not supported. Allowed formats: {allowed}",
        )

    # Replace spaces and special characters with underscores, keeping alphanumerics, hyphens, and dots
    clean_stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", stem).strip("._")
    if not clean_stem:
        clean_stem = "attachment"

    return clean_stem, ext_lower


def generate_unique_filename(filename: str) -> str:
    """
    Generates a collision-resistant unique filename by prefixing a UUID hex string.
    Example: '3f2b8a91c0e4_network_diagram.png'
    """
    clean_stem, ext = sanitize_filename(filename)
    unique_id = uuid.uuid4().hex[:12]
    return f"{unique_id}_{clean_stem}{ext}"


def validate_file_size(file: UploadFile) -> int:
    """
    Checks that the uploaded file size does not exceed MAX_FILE_SIZE (10 MB).
    Returns the file size in bytes.
    Raises HTTPException(400) if the file exceeds the maximum allowed size.
    """
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    if size > MAX_FILE_SIZE:
        size_mb = size / (1024 * 1024)
        limit_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds {limit_mb:.0f} MB limit (uploaded file is {size_mb:.2f} MB)",
        )
    return size


def save_attachment(file: UploadFile) -> tuple[str | None, str | None]:
    """
    Validates and stores an uploaded file.
    - If S3 is configured: uploads to S3 under 'attachments/<unique_filename>'
      matching the Lambda s3:ObjectCreated trigger prefix filter.
    - If S3 is not configured: saves locally to 'app/uploads/<unique_filename>'

    Returns:
        (attachment_reference, local_saved_path_or_none)
        - attachment_reference: String to store in Ticket.attachment (e.g. 'attachments/...' or local filename)
        - local_saved_path: Full path on disk if saved locally, or None if saved to S3
    """
    if not file or not file.filename:
        return None, None

    # Step 1: Validate extension and sanitize filename
    unique_filename = generate_unique_filename(file.filename)

    # Step 2: Validate file size (max 10 MB)
    validate_file_size(file)

    # Step 3: Store in Amazon S3 if configured
    if is_s3_enabled():
        bucket = get_s3_bucket()
        s3_key = format_s3_key(unique_filename)
        s3 = get_s3_client()
        try:
            extra_args = {}
            if file.content_type:
                extra_args["ContentType"] = file.content_type
            s3.upload_fileobj(
                file.file,
                bucket,
                s3_key,
                ExtraArgs=extra_args if extra_args else None,
            )
            logger.info("Successfully uploaded attachment to s3://%s/%s", bucket, s3_key)
            return s3_key, None
        except ClientError as e:
            logger.error("S3 upload failed for bucket %s, key %s: %s", bucket, s3_key, e)
            raise HTTPException(
                status_code=500,
                detail="Failed to upload attachment to cloud storage. Please try again later.",
            )
        except Exception as e:
            logger.error("Unexpected error during S3 upload: %s", e)
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while storing the attachment.",
            )

    # Step 4: Fall back to local disk storage
    local_path = os.path.join(UPLOAD_DIR, unique_filename)
    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return unique_filename, local_path
    except Exception as e:
        logger.error("Failed to save attachment locally to %s: %s", local_path, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to save attachment to local storage.",
        )


def get_attachment_download_target(attachment_ref: str) -> dict[str, str] | None:
    """
    Resolves an attachment reference to either:
    1. An S3 pre-signed URL (15-minute expiration)
    2. A secure local file path on disk

    Returns a dict with:
        {"type": "s3_presigned", "url": "<url>", "filename": "<filename>"}
        or
        {"type": "local_file", "path": "<abs_path>", "filename": "<filename>"}
        or None if not found or invalid.
    """
    if not attachment_ref or not attachment_ref.strip():
        return None

    ref = attachment_ref.strip()

    # Case 1: Legacy "s3://bucket/key" reference
    if ref.startswith("s3://"):
        parts = ref[5:].split("/", 1)
        if len(parts) == 2:
            bucket, key = parts[0], parts[1]
            filename = os.path.basename(key)
            try:
                s3 = get_s3_client()
                url = s3.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": bucket,
                        "Key": key,
                        "ResponseContentDisposition": _attachment_content_disposition(filename),
                    },
                    ExpiresIn=PRESIGNED_URL_EXPIRATION,
                )
                return {"type": "s3_presigned", "url": url, "filename": filename}
            except Exception as e:
                logger.error("Failed to generate presigned URL for legacy S3 URI %s: %s", ref, e)
                raise HTTPException(status_code=500, detail="Failed to generate secure download link.")

    # Case 2: Canonical S3 object key with 'attachments/' prefix
    bucket = get_s3_bucket()
    if ref.startswith(S3_ATTACHMENT_PREFIX) and bucket:
        try:
            s3 = get_s3_client()
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": ref,
                    "ResponseContentDisposition": _attachment_content_disposition(os.path.basename(ref)),
                },
                ExpiresIn=PRESIGNED_URL_EXPIRATION,
            )
            return {"type": "s3_presigned", "url": url, "filename": os.path.basename(ref)}
        except Exception as e:
            logger.error("Failed to generate presigned URL for S3 key %s: %s", ref, e)
            raise HTTPException(status_code=500, detail="Failed to generate secure download link.")

    # Case 3: Local file on disk (including existing files like 'VPC not working.png')
    clean_filename = os.path.basename(ref)
    local_path = os.path.abspath(os.path.join(UPLOAD_DIR, clean_filename))
    upload_dir_abs = os.path.abspath(UPLOAD_DIR)

    # Path traversal protection: ensure resolved path is strictly within UPLOAD_DIR
    resolved_path = Path(local_path).resolve()
    resolved_upload_dir = Path(upload_dir_abs).resolve()
    if resolved_path.is_relative_to(resolved_upload_dir) and resolved_path.is_file():
        return {
            "type": "local_file",
            "path": str(resolved_path),
            "filename": clean_filename,
        }

    # Case 4: Backward compatibility - S3 is enabled and ref is an S3 key without 'attachments/' prefix
    # Normalizes to 'attachments/<ref>' or generates URL for fallback key
    if bucket:
        s3_key = format_s3_key(ref)
        try:
            s3 = get_s3_client()
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": s3_key,
                    "ResponseContentDisposition": _attachment_content_disposition(os.path.basename(s3_key)),
                },
                ExpiresIn=PRESIGNED_URL_EXPIRATION,
            )
            return {"type": "s3_presigned", "url": url, "filename": os.path.basename(s3_key)}
        except Exception as e:
            logger.error("Failed to generate presigned URL for fallback S3 key %s: %s", s3_key, e)

    return None


def _attachment_content_disposition(filename: str) -> str:
    filename = os.path.basename(filename).replace("\r", "").replace("\n", "")
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename.encode("ascii", "ignore").decode("ascii"))
    if not ascii_filename:
        ascii_filename = "attachment"
    encoded_filename = quote(filename, safe="")
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
