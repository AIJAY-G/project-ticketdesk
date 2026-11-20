"""
Unit Tests for TicketDesk Lambda Attachment Processor (Phase 7)
Uses Python's standard library 'unittest' and 'unittest.mock'.
Tests execute locally with zero AWS credentials or network calls.
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure the lambda module is accessible from the test runner
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
LAMBDA_DIR = os.path.join(PROJECT_ROOT, "lambda")
if LAMBDA_DIR not in sys.path:
    sys.path.insert(0, LAMBDA_DIR)

from attachment_processor import (
    lambda_handler,
    parse_s3_record,
    classify_file_type,
    get_current_utc_timestamp,
    EXPECTED_PREFIX,
)


class MockLambdaContext:
    """Simulates the AWS Lambda context object."""
    def __init__(self, request_id="mock-aws-request-id-12345"):
        self.aws_request_id = request_id
        self.function_name = "ticketdesk-poc-attachment-processor"
        self.memory_limit_in_mb = 128


def create_s3_test_event(
    key="attachments/test_error_log.txt",
    bucket="ticketdesk-poc-attachments-bucket",
    size=1024,
    event_name="ObjectCreated:Put",
    event_time="2026-11-20T14:30:00.000Z",
    etag="d41d8cd98f00b204e9800998ecf8427e",
    sequencer="0055AED6DCD90281E2",
) -> dict:
    """Helper to generate standard AWS S3 event notification payloads."""
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": "ap-south-1",
                "eventTime": event_time,
                "eventName": event_name,
                "userIdentity": {"principalId": "AWS:AIDAEXAMPLE"},
                "requestParameters": {"sourceIPAddress": "10.0.1.25"},
                "responseElements": {
                    "x-amz-request-id": "EXAMPLE12345",
                    "x-amz-id-2": "EXAMPLE67890",
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "TicketDeskAttachmentRule",
                    "bucket": {
                        "name": bucket,
                        "ownerIdentity": {"principalId": "EXAMPLE"},
                        "arn": f"arn:aws:s3:::{bucket}",
                    },
                    "object": {
                        "key": key,
                        "size": size,
                        "eTag": etag,
                        "sequencer": sequencer,
                    },
                },
            }
        ]
    }


class TestAttachmentProcessor(unittest.TestCase):
    """Test suite for Lambda attachment processing workflow."""

    def setUp(self):
        self.context = MockLambdaContext()

    def test_utc_timestamp_format(self):
        """Verifies that modern timezone-aware UTC timestamps are formatted correctly with 'Z'."""
        ts = get_current_utc_timestamp()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_classify_file_type(self):
        """Validates extension classification across images, documents, and logs."""
        self.assertEqual(classify_file_type(".png"), "images")
        self.assertEqual(classify_file_type(".JPG"), "images")
        self.assertEqual(classify_file_type(".pdf"), "documents")
        self.assertEqual(classify_file_type(".docx"), "documents")
        self.assertEqual(classify_file_type(".txt"), "logs_and_text")
        self.assertEqual(classify_file_type(".log"), "logs_and_text")
        self.assertEqual(classify_file_type(".exe"), "other")
        self.assertEqual(classify_file_type(""), "other")

    def test_parse_s3_record_valid(self):
        """Validates correct parsing of S3 record fields and metadata."""
        event = create_s3_test_event(
            key="attachments/network_dump.log",
            bucket="ticketdesk-poc-bucket",
            size=4096,
        )
        record = event["Records"][0]
        parsed = parse_s3_record(record)

        self.assertEqual(parsed["bucket_name"], "ticketdesk-poc-bucket")
        self.assertEqual(parsed["object_key"], "attachments/network_dump.log")
        self.assertEqual(parsed["object_size_bytes"], 4096)
        self.assertEqual(parsed["file_extension"], ".log")
        self.assertEqual(parsed["file_category"], "logs_and_text")
        self.assertEqual(parsed["event_name"], "ObjectCreated:Put")
        self.assertEqual(parsed["sequencer"], "0055AED6DCD90281E2")

    def test_single_valid_attachment_processed(self):
        """End-to-end test of a standard single attachment upload event."""
        event = create_s3_test_event(
            key="attachments/a8f9b2c1_screenshot.png",
            size=524288,
        )
        response = lambda_handler(event, self.context)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["processed_count"], 1)
        self.assertEqual(body["failed_count"], 0)
        self.assertEqual(len(body["results"]), 1)

        result = body["results"][0]
        self.assertEqual(result["status"], "PROCESSED")
        self.assertEqual(result["key"], "attachments/a8f9b2c1_screenshot.png")
        self.assertEqual(result["category"], "images")
        self.assertEqual(result["size_bytes"], 524288)
        self.assertFalse(result["sns_notified"])  # SNS topic unset by default

    def test_url_encoded_object_key_decoding(self):
        """Validates that S3 keys with URL-encoded special characters decode accurately."""
        # S3 encodes spaces as '+' and special symbols as '%XX'
        raw_key = "attachments/VPN+Configuration%231%20Report.pdf"
        event = create_s3_test_event(key=raw_key)

        response = lambda_handler(event, self.context)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])

        self.assertEqual(body["processed_count"], 1)
        decoded_key = body["results"][0]["key"]
        self.assertEqual(decoded_key, "attachments/VPN Configuration#1 Report.pdf")
        self.assertEqual(body["results"][0]["category"], "documents")

    def test_multi_record_batch_processing(self):
        """Validates processing a batch of multiple records in a single invocation."""
        event = {
            "Records": [
                create_s3_test_event(key="attachments/doc1.pdf", size=1000)["Records"][0],
                create_s3_test_event(key="attachments/img2.jpg", size=2000)["Records"][0],
            ]
        }
        response = lambda_handler(event, self.context)
        body = json.loads(response["body"])

        self.assertEqual(body["processed_count"], 2)
        self.assertEqual(body["failed_count"], 0)
        self.assertEqual(len(body["results"]), 2)

    def test_non_attachment_prefix_skipped(self):
        """Ensures objects uploaded outside 'attachments/' are safely skipped."""
        event = create_s3_test_event(key="database_backups/backup_2026.sql")
        response = lambda_handler(event, self.context)
        body = json.loads(response["body"])

        self.assertEqual(body["processed_count"], 0)
        self.assertEqual(body["failed_count"], 0)
        self.assertEqual(body["results"][0]["status"], "SKIPPED")
        self.assertIn("does not start with", body["results"][0]["reason"])

    def test_folder_marker_skipped_safely(self):
        """Ensures S3 directory creation markers (ending in '/') are ignored."""
        event = create_s3_test_event(key="attachments/", size=0)
        response = lambda_handler(event, self.context)
        body = json.loads(response["body"])

        self.assertEqual(body["processed_count"], 0)
        self.assertEqual(body["results"][0]["status"], "SKIPPED")
        self.assertIn("Folder marker", body["results"][0]["reason"])

    def test_empty_or_malformed_event_payload(self):
        """Validates resilience against empty payloads or missing 'Records'."""
        empty_payloads = [{}, {"Records": []}, None, "invalid-string", {"Records": "not-a-list"}]
        for payload in empty_payloads:
            response = lambda_handler(payload, self.context)
            self.assertEqual(response["statusCode"], 200)
            body = json.loads(response["body"])
            self.assertEqual(body["processed_count"], 0)

    @patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:ap-south-1:123456789012:ticketdesk-poc-notifications"})
    @patch("boto3.client")
    def test_optional_sns_notification_when_configured(self, mock_boto_client):
        """Verifies that SNS publish is triggered when SNS_TOPIC_ARN is configured."""
        mock_sns = MagicMock()
        mock_boto_client.return_value = mock_sns

        event = create_s3_test_event(key="attachments/critical_error.log")
        response = lambda_handler(event, self.context)
        body = json.loads(response["body"])

        self.assertEqual(body["processed_count"], 1)
        self.assertTrue(body["results"][0]["sns_notified"])
        mock_sns.publish.assert_called_once()

    def test_error_isolation_in_batch(self):
        """Ensures an exception on a single malformed record does not abort processing of others."""
        malformed_record = {"s3": None}  # Invalid structure inside record
        valid_record = create_s3_test_event(key="attachments/valid.png")["Records"][0]

        event = {"Records": [malformed_record, valid_record]}
        response = lambda_handler(event, self.context)
        body = json.loads(response["body"])

        self.assertEqual(body["processed_count"], 1)
        self.assertEqual(body["failed_count"], 1)
        self.assertEqual(body["results"][0]["status"], "FAILED")
        self.assertEqual(body["results"][1]["status"], "PROCESSED")


if __name__ == "__main__":
    unittest.main()
