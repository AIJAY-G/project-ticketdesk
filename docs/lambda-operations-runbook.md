# TicketDesk POC - Phase 7 & Phase 8 Lambda Operations Runbook

> **Target Audience**: Cloud Engineers, DevOps Interns, and IT Support System Administrators  
> **Environment**: Proof of Concept (POC)  
> **AWS Region**: `ap-south-1` (Asia Pacific - Mumbai)  
> **Status**: Verified in Local Sandbox; Ready for Future AWS Deployment

---

## 1. Purpose of the TicketDesk Lambda
The TicketDesk AWS Lambda attachment processor (`ticketdesk-poc-attachment-processor`) provides an **event-driven, serverless background processing pipeline** for IT support ticket attachments.

When users upload attachments (screenshots, logs, error reports, configuration files) through the TicketDesk web application, the application server offloads post-upload tasks to AWS Lambda. The Lambda function:
* Detects incoming uploads in Amazon S3.
* Extracts critical object metadata (bucket, key, size, MIME/extension category, ETag, timestamp, S3 sequencer).
* Emits structured JSON audit trails to Amazon CloudWatch Logs for operational visibility and security auditing.
* Dispatches optional alerts to an Amazon SNS topic (if configured).

---

## 2. Architecture & Trigger Flow

```
[User Browser]
       │
       │ 1. POST /api/tickets (Upload with file)
       ▼
[FastAPI on EC2] ────── 2. PutObject ──────▶ [Amazon S3 Bucket]
                                            (Key: attachments/<uuid>_<filename>)
                                                        │
                                            3. s3:ObjectCreated:* Event
                                                        │
                                                        ▼
                                              [AWS Lambda Function]
                                           (attachment_processor.py)
                                                        │
                                        ┌───────────────┴───────────────┐
                                        ▼                               ▼
                             [CloudWatch Logs]                [Amazon SNS Topic]
                         (/aws/lambda/ticketdesk-*)        (ticketdesk-poc-notifications)
                         - 7-Day Bounded Retention         - Optional Alerting (Disabled)
                         - Metric Alarms (Errors/Throttles)
```

1. The user creates a ticket with an attachment.
2. The TicketDesk backend (`app/storage.py`) uploads the file to the S3 bucket under the prefix `attachments/`.
3. Amazon S3 automatically generates an asynchronous `s3:ObjectCreated:*` notification.
4. AWS Lambda parses the notification payload, extracts object metadata, and logs the execution to CloudWatch Logs.

---

## 3. Expected S3 Object Key Structure
* **Configured Prefix**: `attachments/`
* **Naming Convention**: `attachments/<uuid12>_<sanitized_filename>.<ext>`
* **Example**: `attachments/8f3b2a1c0d4e_network_timeout.log`

> **Safety Notice**: Any objects uploaded outside `attachments/` (e.g., `database_dumps/` or root files) are flagged as `SKIPPED` by the Lambda function without throwing errors or triggering alerts.

---

## 4. Local vs. Cloud Verification Workflow

| Verification Mode | Tools Used | Network Access Required? | AWS Credentials Required? |
| :--- | :--- | :--- | :--- |
| **Local Verification (Current State)** | `python -m unittest`, `scripts/validate_lambda_operations.py` | **No** (Offline) | **No** |
| **Cloud Verification (Future Deployment)** | AWS CLI, AWS Management Console, CloudWatch Logs | **Yes** | **Yes** (IAM Role / Session) |

### Running Local Verification Today
```bash
# 1. Run unit test suite
python -m unittest discover -s tests -v

# 2. Run end-to-end operational validation script
python scripts/validate_lambda_operations.py
```

---

## 5. CloudWatch Logs: Monitoring & Audit Trail

### How to View Lambda Logs in CloudWatch (Future AWS Deployment)
1. Open the **AWS Management Console** and navigate to **CloudWatch**.
2. In the left navigation pane, select **Logs** > **Log groups**.
3. Choose the log group: `/aws/lambda/ticketdesk-poc-attachment-processor`.
4. Open the latest **Log stream** (e.g., `2026/11/20/[$LATEST]abcdef123456...`).

Or query via the **AWS CLI**:
```bash
aws logs filter-log-events \
    --log-group-name "/aws/lambda/ticketdesk-poc-attachment-processor" \
    --region ap-south-1 \
    --filter-pattern '{ $.level = "INFO" }'
```

### Important Log Fields in Structured JSON
Every log event emitted by the Lambda function follows this JSON structure:

```json
{
  "timestamp": "2026-11-20T14:30:43.418671Z",
  "level": "INFO",
  "event_type": "ATTACHMENT_PROCESSED_SUCCESSFULLY",
  "service": "ticketdesk-attachment-processor",
  "index": 0,
  "request_id": "c02f03b2-6f80-4671-8cb3-03a2005c43b3",
  "bucket": "ticketdesk-poc-attachments-xxxx",
  "key": "attachments/a8f9b2c1_screenshot.png",
  "size_bytes": 524288,
  "extension": ".png",
  "category": "images",
  "event_name": "ObjectCreated:Put",
  "event_time": "2026-11-20T14:30:00.000Z",
  "etag": "d41d8cd98f00b204e9800998ecf8427e",
  "sequencer": "0055AED6DCD90281E2"
}
```

### Identifying Successful Processing
Look for log entries with:
* `"level": "INFO"`
* `"event_type": "ATTACHMENT_PROCESSED_SUCCESSFULLY"`
* Output payload response: `"statusCode": 200` with `"status": "PROCESSED"`.

### Identifying Failed Processing
Look for log entries with:
* `"level": "ERROR"`
* `"event_type": "RECORD_PROCESSING_FAILED"`
* The `error` field contains the specific exception trace (e.g. malformed JSON or corrupted record).

---

## 6. Error-Handling Strategy & Retry Architecture

### Chosen Approach: Pattern 1 (Non-Retrying Isolated Batch)
1. **Isolated Processing**: Each S3 record in `event["Records"]` is processed in an independent `try/except` block.
2. **Failure Isolation**: A corrupted record logs an `ERROR` event and increments `failed_count`, but does **not** stop other records in the same batch from completing.
3. **Completion Status**: The function returns HTTP `200` with summary counts (`processed_count` and `failed_count`).
4. **Why We Do Not Raise Uncaught Exceptions for Retries**:
   * S3 triggers Lambda **asynchronously**. If Lambda raises an uncaught exception, AWS automatically retries the entire batch twice with exponential backoff.
   * If a file payload is permanently malformed, automatic retries waste compute cycles and incur unnecessary AWS costs.
   * Instead, the `RECORD_PROCESSING_FAILED` log event fires a CloudWatch Metric Filter alarm immediately, alerting the operations team directly.

---

## 7. Troubleshooting Guide

### Issue A: S3 Upload Occurs, but Lambda Is Not Invoked
* **Possible Cause 1: Prefix Mismatch**:
  * Did the file land in the root of the bucket or in `uploads/` instead of `attachments/`?
  * *Fix*: Verify the application uploads strictly to `attachments/`.
* **Possible Cause 2: Missing Lambda Permission**:
  * Does S3 have permission to invoke Lambda?
  * *Verification*:
    ```bash
    aws lambda get-policy \
        --function-name ticketdesk-poc-attachment-processor \
        --region ap-south-1
    ```
    Ensure `AllowExecutionFromS3Bucket` is present with principal `s3.amazonaws.com` and source ARN matching the S3 bucket.
* **Possible Cause 3: S3 Bucket Notification Configuration Not Applied**:
  * *Verification*:
    ```bash
    aws s3api get-bucket-notification-configuration \
        --bucket <bucket-name> \
        --region ap-south-1
    ```
    Ensure `LambdaFunctionConfigurations` contains the Lambda ARN with filter prefix `attachments/`.

### Issue B: Lambda Emits `RECORD_PROCESSING_FAILED`
* **Check the Log Details**:
  * Query CloudWatch Logs Insights:
    ```
    fields @timestamp, error, key
    | filter level = "ERROR"
    | sort @timestamp desc
    | limit 20
    ```
  * Verify if the S3 event record was truncated or malformed.

### Issue C: CloudWatch Alarm `ticketdesk-poc-lambda-errors` Triggers
* **Meaning**: Lambda recorded 1 or more execution errors in a 5-minute window.
* **Response Steps**:
  1. Inspect the latest CloudWatch Log Streams for `level: "ERROR"`.
  2. Verify if the error is an application parsing bug or an AWS runtime issue (e.g. timeout or memory exhaustion).
  3. Memory limit is currently 128 MB and timeout is 15 seconds. If timeouts occur, check if network latency or large payloads caused execution delays.

---

## 8. Idempotency & Duplicate Delivery Considerations
* **Stateless Metadata Processing**: The current Lambda function does not execute database writes; it parses events, emits logs, and optionally notifies SNS.
* **S3 Duplicate Events**: Amazon S3 provides at-least-once event delivery. In rare cases, duplicate `s3:ObjectCreated` events may arrive for the same object.
* **Deduplication Fields**:
  * **`eTag`**: MD5 checksum / hash of the object content.
  * **`sequencer`**: Hexadecimal sequence string provided by Amazon S3 to determine the exact order of events per object.
* **Enterprise Roadmap**: If future requirements include writing attachment records to Amazon RDS or DynamoDB, use `object_key + sequencer` as a unique primary key to guarantee strict cross-invocation deduplication.

---

## 9. Expected AWS Services & Cost-Conscious Architecture

| AWS Service | POC Usage | Cost Profile (AWS Free Tier) |
| :--- | :--- | :--- |
| **AWS Lambda** | Python 3.12, 128 MB RAM, 15s timeout | **$0.00** (Free Tier includes 1,000,000 requests/month) |
| **Amazon S3** | Event notifications on `attachments/` | **$0.00** (S3 event notifications are free) |
| **CloudWatch Logs** | 7-day retention (`/aws/lambda/ticketdesk-poc-*`) | **$0.00** (Free Tier includes 5 GB ingestion & storage) |
| **CloudWatch Alarms** | 2 alarms (Errors & Throttles) | **$0.00** (Free Tier includes 10 standard metric alarms) |
| **Amazon SNS** | Optional alert delivery (disabled by default) | **$0.00** (Free Tier includes 1M publishes/month) |

### Expensive Services Intentionally Excluded:
* ❌ **NAT Gateway**: Excluded ($0.00 vs. ~$32.40/month). Lambda runs outside VPC.
* ❌ **Amazon DynamoDB**: Excluded (state tracking not required for metadata logging).
* ❌ **Amazon SQS / DLQ**: Excluded (Metric filter alarms used instead of DLQ).
* ❌ **CloudWatch Dashboards**: Excluded ($0.00 vs. $3.00/dashboard/month).
* ❌ **Provisioned Concurrency**: Excluded (on-demand compute is $0 when idle).

---

## 10. Future Deployment & Clean Teardown

When deploying to AWS in a future phase:
1. **Apply Infrastructure**:
   ```bash
   cd terraform
   terraform init
   terraform plan -out=tfplan
   terraform apply tfplan
   ```
2. **Post-Deployment Smoke Test**:
   * Upload a test attachment through the TicketDesk UI.
   * Verify S3 receives the object: `aws s3 ls s3://<bucket-name>/attachments/`.
   * Check CloudWatch logs for `ATTACHMENT_PROCESSED_SUCCESSFULLY`.
3. **Clean Teardown (Prevent Unintended Charges)**:
   ```bash
   terraform destroy -auto-approve
   ```
   * S3 bucket has `force_destroy = false` enabled for data safety; empty the bucket before teardown if deletion is required.
