"""
Unit and integration tests for TicketDesk S3 attachment prefix and download functionality.
Verifies compliance with the AWS Lambda s3:ObjectCreated trigger prefix 'attachments/'.
"""

import os
import io
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add app directory to sys.path
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from fastapi import HTTPException, UploadFile
import storage
import main


class TestAttachmentPrefixAndStorage(unittest.TestCase):
    def setUp(self):
        self.original_bucket = os.environ.get("S3_BUCKET_NAME")
        self.original_region = os.environ.get("AWS_REGION")
        self.test_files_to_clean = []

    def tearDown(self):
        # Restore environment variables
        if self.original_bucket is not None:
            os.environ["S3_BUCKET_NAME"] = self.original_bucket
        else:
            os.environ.pop("S3_BUCKET_NAME", None)

        if self.original_region is not None:
            os.environ["AWS_REGION"] = self.original_region
        else:
            os.environ.pop("AWS_REGION", None)

        # Clean up any local files created during tests
        for path in self.test_files_to_clean:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    # --------------------------------------------------------------------------
    # 1. Prefix Configuration & Key Formatting Tests
    # --------------------------------------------------------------------------
    def test_01_prefix_constant(self):
        """Verify S3_ATTACHMENT_PREFIX constant is strictly 'attachments/'."""
        self.assertEqual(storage.S3_ATTACHMENT_PREFIX, "attachments/")

    def test_02_format_s3_key_bare_filename(self):
        """Verify bare filenames receive the 'attachments/' prefix."""
        key = storage.format_s3_key("3f2a89c19b02_network_log.txt")
        self.assertEqual(key, "attachments/3f2a89c19b02_network_log.txt")

    def test_03_format_s3_key_already_prefixed(self):
        """Verify keys already starting with 'attachments/' are not duplicated."""
        key = storage.format_s3_key("attachments/3f2a89c19b02_network_log.txt")
        self.assertEqual(key, "attachments/3f2a89c19b02_network_log.txt")

    def test_04_format_s3_key_leading_slashes(self):
        """Verify leading slashes are safely stripped."""
        key1 = storage.format_s3_key("/attachments/test.png")
        self.assertEqual(key1, "attachments/test.png")
        key2 = storage.format_s3_key("/test.png")
        self.assertEqual(key2, "attachments/test.png")

    # --------------------------------------------------------------------------
    # 2. S3 Upload Prefix & Key Generation Tests
    # --------------------------------------------------------------------------
    def test_05_s3_upload_stores_with_prefix(self):
        """Verify S3 upload stores object using 'attachments/<UUID>_<filename>'."""
        os.environ["S3_BUCKET_NAME"] = "ticketdesk-poc-attachments"

        mock_s3 = MagicMock()
        storage.get_s3_client = lambda: mock_s3

        file_content = b"Error log data content"
        upload = UploadFile(file=io.BytesIO(file_content), filename="vpn_error.log")

        s3_key, local_path = storage.save_attachment(upload)

        self.assertIsNone(local_path)
        self.assertIsNotNone(s3_key)
        assert s3_key is not None
        self.assertTrue(s3_key.startswith("attachments/"), f"Key '{s3_key}' must start with 'attachments/'")

        # Verify pattern: attachments/<12-hex-uuid>_vpn_error.log
        pattern = r"^attachments/[a-f0-9]{12}_vpn_error\.log$"
        self.assertTrue(re.match(pattern, s3_key), f"Key '{s3_key}' did not match pattern '{pattern}'")

        # Verify boto3 upload_fileobj was called with exact bucket and prefix key
        mock_s3.upload_fileobj.assert_called_once()
        args, kwargs = mock_s3.upload_fileobj.call_args
        self.assertEqual(args[1], "ticketdesk-poc-attachments")
        self.assertEqual(args[2], s3_key)

    def test_06_lambda_notification_prefix_compatibility(self):
        """Verify generated S3 object key matches the Lambda notification trigger prefix."""
        os.environ["S3_BUCKET_NAME"] = "ticketdesk-poc-attachments"
        mock_s3 = MagicMock()
        storage.get_s3_client = lambda: mock_s3

        upload = UploadFile(file=io.BytesIO(b"screenshot"), filename="architecture.png")
        s3_key, _ = storage.save_attachment(upload)

        # The Lambda filter_prefix in terraform/lambda.tf is 'attachments/'
        lambda_filter_prefix = "attachments/"
        self.assertIsNotNone(s3_key)
        assert s3_key is not None
        self.assertTrue(
            s3_key.startswith(lambda_filter_prefix),
            f"Object key '{s3_key}' will fail Lambda event filter '{lambda_filter_prefix}'"
        )

    # --------------------------------------------------------------------------
    # 3. S3 Pre-Signed URL Download Tests
    # --------------------------------------------------------------------------
    def test_07_s3_download_target_with_prefix(self):
        """Verify pre-signed URL generation uses the exact 'attachments/...' object key."""
        os.environ["S3_BUCKET_NAME"] = "ticketdesk-poc-attachments"

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = (
            "https://s3.ap-south-1.amazonaws.com/ticketdesk-poc-attachments/attachments/test.png?expires=900"
        )
        storage.get_s3_client = lambda: mock_s3

        target = storage.get_attachment_download_target("attachments/3f2b8a91c0e4_test.png")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target["type"], "s3_presigned")
        self.assertEqual(target["filename"], "3f2b8a91c0e4_test.png")
        self.assertIn("expires=900", target["url"])

        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "ticketdesk-poc-attachments", "Key": "attachments/3f2b8a91c0e4_test.png"},
            ExpiresIn=900,
        )

    def test_08_s3_download_target_fallback_normalization(self):
        """Verify fallback normalizes unprefixed keys to 'attachments/<key>' when S3 is enabled."""
        os.environ["S3_BUCKET_NAME"] = "ticketdesk-poc-attachments"

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/bucket/attachments/legacy.png?expires=900"
        storage.get_s3_client = lambda: mock_s3

        target = storage.get_attachment_download_target("legacy_unprefixed.png")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target["type"], "s3_presigned")
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "ticketdesk-poc-attachments", "Key": "attachments/legacy_unprefixed.png"},
            ExpiresIn=900,
        )

    def test_09_legacy_s3_uri_compatibility(self):
        """Verify legacy 's3://bucket/key' references continue to resolve."""
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/bucket/legacy.png?expires=900"
        storage.get_s3_client = lambda: mock_s3

        target = storage.get_attachment_download_target("s3://old-bucket/attachments/archived.pdf")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target["type"], "s3_presigned")
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "old-bucket", "Key": "attachments/archived.pdf"},
            ExpiresIn=900,
        )

    # --------------------------------------------------------------------------
    # 4. Local Storage Fallback & Legacy Preservation Tests
    # --------------------------------------------------------------------------
    def test_10_local_fallback_when_s3_unset(self):
        """Verify local disk fallback operates without S3 prefix when S3_BUCKET_NAME is unset."""
        os.environ.pop("S3_BUCKET_NAME", None)
        self.assertFalse(storage.is_s3_enabled())

        upload = UploadFile(file=io.BytesIO(b"Local test data"), filename="local_doc.txt")
        ref, local_path = storage.save_attachment(upload)

        self.assertIsNotNone(ref)
        self.assertIsNotNone(local_path)
        assert ref is not None
        assert local_path is not None
        self.test_files_to_clean.append(local_path)

        # Local storage stores filename on disk without 'attachments/' prefix
        self.assertFalse(ref.startswith("attachments/"))
        self.assertTrue(ref.endswith("_local_doc.txt"))
        self.assertTrue(os.path.exists(local_path))

    def test_11_legacy_local_attachment_intact(self):
        """Verify existing legacy attachment 'VPC not working.png' resolves to local disk."""
        os.environ.pop("S3_BUCKET_NAME", None)
        target = storage.get_attachment_download_target("VPC not working.png")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target["type"], "local_file")
        self.assertEqual(target["filename"], "VPC not working.png")
        self.assertTrue(os.path.exists(target["path"]))
        self.assertEqual(os.path.getsize(target["path"]), 7579998)

    # --------------------------------------------------------------------------
    # 5. Security & Validation Rules Retention Tests
    # --------------------------------------------------------------------------
    def test_12_disallowed_extension_rejected(self):
        """Verify disallowed extensions (.exe, .sh, .py) are rejected with HTTP 400."""
        for bad_ext in [".exe", ".sh", ".bat", ".py", ".html"]:
            with self.assertRaises(HTTPException) as ctx:
                storage.sanitize_filename(f"malware{bad_ext}")
            self.assertEqual(ctx.exception.status_code, 400)

    def test_13_oversized_file_rejected(self):
        """Verify upload exceeding 10 MB limit is rejected with HTTP 400."""
        big_file = UploadFile(file=io.BytesIO(b"0" * (11 * 1024 * 1024)), filename="large.pdf")
        with self.assertRaises(HTTPException) as ctx:
            storage.validate_file_size(big_file)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_14_path_traversal_contained(self):
        """Verify path traversal attempts are neutralized by Path.is_relative_to."""
        os.environ.pop("S3_BUCKET_NAME", None)
        traversals = ["../../../etc/passwd", "..", "../../system.ini"]
        for attack in traversals:
            target = storage.get_attachment_download_target(attack)
            if target is not None:
                # If resolved, it MUST be strictly within UPLOAD_DIR
                p = Path(target["path"]).resolve()
                upload_dir = Path(storage.UPLOAD_DIR).resolve()
                self.assertTrue(p.is_relative_to(upload_dir), f"Path traversal leak detected: {p}")


if __name__ == "__main__":
    unittest.main()
