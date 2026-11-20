"""
TicketDesk IT Support Ticket Tracking POC - AWS Lambda Attachment Processor
Phase 7: Serverless Integration

This Lambda function is triggered asynchronously by Amazon S3 's3:ObjectCreated:*'
events whenever an attachment is uploaded to the TicketDesk S3 bucket under the
'attachments/' prefix.

Key Architecture & Design Decisions:
1. S3 Event Parsing & URL Decoding:
   - Amazon S3 event notifications URL-encode object keys (e.g., spaces become '+'
     or '%20', and special characters become '%XX').
   - Uses urllib.parse.unquote_plus() to safely decode keys before processing.

2. Prefix Filtering & Folder Marker Handling:
   - Strictly enforces that only objects within the 'attachments/' prefix are processed.
   - Automatically detects and ignores S3 directory markers (keys ending in '/' or
     zero-byte folder placeholders created by console/CLI uploads).
   - Objects outside 'attachments/' are flagged as SKIPPED without failing.

3. Metadata & Extension Classification:
   - Inspects file extension and categorizes into:
     * images (.png, .jpg, .jpeg, .gif, .webp)
     * documents (.pdf, .docx, .doc, .xlsx, .pptx)
     * logs_and_text (.txt, .log, .json, .csv, .xml)
     * other (any unrecognized extensions)

4. Structured CloudWatch Logging & Security:
   - Emits standardized, machine-readable JSON log events to CloudWatch Logs.
   - Security: Structured logs contain ONLY technical metadata (bucket, key, size,
     extension, category, timestamp, ETag, sequencer).
   - Strictly NO secrets, passwords, user tokens, or raw file contents are ever logged.

5. Batch Error Handling Strategy (Pattern 1 - Non-Retrying Isolated Batch):
   - Each S3 record is processed in an isolated try/except block.
   - If an individual record fails, it is marked as FAILED with an ERROR log entry,
     and processing continues for remaining records in the batch.
   - The handler completes with statusCode 200 and summary counts (processed vs. failed).
   - Architectural Rationale for POC:
     * S3 invokes Lambda asynchronously. Raising an uncaught exception would cause AWS
       Lambda to automatically retry the entire batch twice with exponential backoff,
       potentially causing retry loops and unnecessary compute costs for corrupt files.
     * In Phase 8, CloudWatch Metric Filters detect any log entry with level: 'ERROR'
       and immediately trigger alarms, giving operators direct visibility without
       requiring costly DLQ infrastructure.

6. Idempotency Notice:
   - This handler is currently stateless, metadata-, and logging-oriented.
   - Formal persistent idempotency (e.g., deduplication using a DynamoDB or RDS
     state store) is intentionally not implemented for this internship POC to
     minimize cloud infrastructure and cost.
   - S3's native 'sequencer' and 'eTag' fields are captured and logged to provide
     full auditability and trace duplicate event deliveries.

7. Optional SNS Notification:
   - If SNS_TOPIC_ARN is configured, publishes an alert summary to the topic.
   - If SNS_TOPIC_ARN is unset or empty (default for POC), SNS publishing is skipped,
     guaranteeing zero unexpected costs.
"""

import os
import json
import logging
import urllib.parse
from datetime import datetime, timezone

# Initialize standard Python logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configurable constants
EXPECTED_PREFIX = "attachments/"
SUPPORTED_EXTENSIONS = {
    "images": {".png", ".jpg", ".jpeg", ".gif", ".webp"},
    "documents": {".pdf", ".docx", ".doc", ".xlsx", ".pptx"},
    "logs_and_text": {".txt", ".log", ".json", ".csv", ".xml"},
}


def get_current_utc_timestamp() -> str:
    """Returns current UTC time formatted as an ISO-8601 string with 'Z' suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log_structured_event(level: str, event_type: str, data: dict):
    """
    Emits a structured JSON log message to standard output for CloudWatch Logs.
    Structured logs enable precise filtering, CloudWatch Insights queries, and metric alarms.
    
    Security: Only non-sensitive operational metadata is logged.
    """
    log_entry = {
        "timestamp": get_current_utc_timestamp(),
        "level": level.upper(),
        "event_type": event_type,
        "service": "ticketdesk-attachment-processor",
        **data,
    }
    json_str = json.dumps(log_entry)
    if level.lower() == "error":
        logger.error(json_str)
    elif level.lower() == "warning":
        logger.warning(json_str)
    else:
        logger.info(json_str)


def classify_file_type(extension: str) -> str:
    """Classifies file extension into human-readable categories."""
    ext = extension.lower()
    for category, extensions in SUPPORTED_EXTENSIONS.items():
        if ext in extensions:
            return category
    return "other"


def parse_s3_record(record: dict) -> dict:
    """
    Parses an individual S3 event record from the 'Records' list.
    Safely decodes URL-encoded keys and extracts core object metadata.
    """
    event_name = record.get("eventName", "Unknown")
    event_time = record.get("eventTime", get_current_utc_timestamp())
    s3_info = record.get("s3", {})

    bucket_name = s3_info.get("bucket", {}).get("name", "")
    bucket_arn = s3_info.get("bucket", {}).get("arn", "")

    raw_key = s3_info.get("object", {}).get("key", "")
    # Amazon S3 event notifications URL-encode keys (spaces become '+' or '%20')
    object_key = urllib.parse.unquote_plus(raw_key) if raw_key else ""
    object_size = s3_info.get("object", {}).get("size", 0)
    e_tag = s3_info.get("object", {}).get("eTag", "")
    sequencer = s3_info.get("object", {}).get("sequencer", "")

    _, ext = os.path.splitext(object_key)
    file_category = classify_file_type(ext)

    return {
        "event_name": event_name,
        "event_time": event_time,
        "bucket_name": bucket_name,
        "bucket_arn": bucket_arn,
        "object_key": object_key,
        "raw_key": raw_key,
        "object_size_bytes": object_size,
        "etag": e_tag,
        "sequencer": sequencer,
        "file_extension": ext.lower(),
        "file_category": file_category,
    }


def send_optional_sns_notification(summary: dict) -> bool:
    """
    Optionally publishes an alert message to an Amazon SNS topic.
    If SNS_TOPIC_ARN is not set in the environment, this is safely skipped
    to ensure zero unnecessary costs for the internship POC.
    """
    topic_arn = os.getenv("SNS_TOPIC_ARN", "").strip()
    if not topic_arn:
        # SNS notification is optional; skip if unconfigured
        return False

    try:
        import boto3
        sns_client = boto3.client("sns")
        subject = f"TicketDesk Alert: New Attachment Processed ({summary.get('file_category', 'file')})"
        message = (
            f"TicketDesk IT Support Attachment Notification\n"
            f"--------------------------------------------\n"
            f"File Name: {summary.get('object_key')}\n"
            f"File Size: {summary.get('object_size_bytes', 0)} bytes\n"
            f"Category:  {summary.get('file_category')}\n"
            f"Bucket:    {summary.get('bucket_name')}\n"
            f"Timestamp: {summary.get('event_time')}\n"
            f"ETag:      {summary.get('etag')}\n"
            f"Sequencer: {summary.get('sequencer')}\n"
        )
        sns_client.publish(
            TopicArn=topic_arn,
            Subject=subject[:100],  # SNS subject max length 100 chars
            Message=message,
        )
        log_structured_event(
            "INFO",
            "SNS_NOTIFICATION_SENT",
            {"topic_arn": topic_arn, "object_key": summary.get("object_key")},
        )
        return True
    except Exception as e:
        log_structured_event(
            "WARNING",
            "SNS_NOTIFICATION_FAILED",
            {
                "topic_arn": topic_arn,
                "object_key": summary.get("object_key"),
                "error": str(e),
            },
        )
        return False


def lambda_handler(event: dict, context=None) -> dict:
    """
    Main AWS Lambda entry point for S3 ObjectCreated events.
    
    Args:
        event (dict): AWS event payload containing 'Records' from Amazon S3.
        context (object): AWS Lambda execution context (optional/mockable).

    Returns:
        dict: Standard Lambda response containing status code and processing metrics.
    """
    request_id = getattr(context, "aws_request_id", "local-test-request")
    record_count = len(event.get("Records", [])) if isinstance(event, dict) and isinstance(event.get("Records"), list) else 0

    log_structured_event(
        "INFO",
        "INVOCATION_STARTED",
        {"request_id": request_id, "record_count": record_count},
    )

    if not isinstance(event, dict) or "Records" not in event or not isinstance(event["Records"], list):
        log_structured_event(
            "WARNING",
            "INVALID_EVENT_PAYLOAD",
            {"request_id": request_id, "detail": "Payload contains no valid 'Records' list"},
        )
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "No valid S3 records to process",
                "processed_count": 0,
                "failed_count": 0,
                "results": [],
            }),
        }

    records = event["Records"]
    results = []
    processed_count = 0
    failed_count = 0

    for idx, record in enumerate(records):
        try:
            parsed = parse_s3_record(record)
            object_key = parsed["object_key"]

            # Guard 1: Detect folder marker or empty key
            if not object_key or object_key.endswith("/"):
                log_structured_event(
                    "INFO",
                    "SKIPPED_FOLDER_MARKER",
                    {"index": idx, "key": object_key, "bucket": parsed["bucket_name"]},
                )
                results.append({
                    "index": idx,
                    "status": "SKIPPED",
                    "reason": "Folder marker or empty key",
                    "key": object_key,
                })
                continue

            # Guard 2: Enforce attachments/ prefix filter
            if not object_key.startswith(EXPECTED_PREFIX):
                log_structured_event(
                    "INFO",
                    "SKIPPED_NON_ATTACHMENT_PREFIX",
                    {
                        "index": idx,
                        "key": object_key,
                        "expected_prefix": EXPECTED_PREFIX,
                        "bucket": parsed["bucket_name"],
                    },
                )
                results.append({
                    "index": idx,
                    "status": "SKIPPED",
                    "reason": f"Key does not start with '{EXPECTED_PREFIX}'",
                    "key": object_key,
                })
                continue

            # Core Processing: Valid attachment metadata extracted
            log_structured_event(
                "INFO",
                "ATTACHMENT_PROCESSED_SUCCESSFULLY",
                {
                    "index": idx,
                    "request_id": request_id,
                    "bucket": parsed["bucket_name"],
                    "key": parsed["object_key"],
                    "size_bytes": parsed["object_size_bytes"],
                    "extension": parsed["file_extension"],
                    "category": parsed["file_category"],
                    "event_name": parsed["event_name"],
                    "event_time": parsed["event_time"],
                    "etag": parsed["etag"],
                    "sequencer": parsed["sequencer"],
                },
            )

            # Optional SNS notification (only executed if SNS_TOPIC_ARN is configured)
            sns_sent = send_optional_sns_notification(parsed)

            results.append({
                "index": idx,
                "status": "PROCESSED",
                "key": parsed["object_key"],
                "bucket": parsed["bucket_name"],
                "size_bytes": parsed["object_size_bytes"],
                "category": parsed["file_category"],
                "sns_notified": sns_sent,
            })
            processed_count += 1

        except Exception as err:
            failed_count += 1
            log_structured_event(
                "ERROR",
                "RECORD_PROCESSING_FAILED",
                {
                    "index": idx,
                    "request_id": request_id,
                    "error": str(err),
                },
            )
            results.append({
                "index": idx,
                "status": "FAILED",
                "error": str(err),
            })

    log_structured_event(
        "INFO",
        "INVOCATION_COMPLETED",
        {
            "request_id": request_id,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "total_records": len(records),
        },
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "S3 event processing completed",
            "processed_count": processed_count,
            "failed_count": failed_count,
            "results": results,
        }),
    }
