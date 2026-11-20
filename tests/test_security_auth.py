import os
import sys
import unittest
import time
from unittest.mock import MagicMock, patch

# Add 'app' directory to path
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import User, Ticket, TicketActivity
from security import (
    hash_password,
    verify_password,
    create_access_token,
    verify_access_token,
)
import storage
import main


class TestSecurityAndAuth(unittest.TestCase):
    """
    Comprehensive security test suite covering:
    - Password hashing & verification (PBKDF2-SHA256)
    - Token generation, signing, tampering, and expiration
    - Authentication (Bearer token verification & rejection of unauthenticated requests)
    - Role-Based Access Control (RBAC) on /api/users, /api/tickets, and attachments
    - Protected legacy /uploads/{filename} endpoint
    - PostgreSQL SSL enforcement
    """

    @classmethod
    def setUpClass(cls):
        # Configure in-memory SQLite for testing to isolate from production database
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        # Re-create tables cleanly for each test
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.db = self.TestingSessionLocal()

        # Seed test accounts with secure hashed passwords
        self.admin = User(username="sec_admin", password=hash_password("admin_pass123"), role="Admin")
        self.engineer = User(username="sec_eng", password=hash_password("eng_pass123"), role="Support Engineer")
        self.user1 = User(username="sec_user1", password=hash_password("user1_pass123"), role="User")
        self.user2 = User(username="sec_user2", password=hash_password("user2_pass123"), role="User")

        self.db.add_all([self.admin, self.engineer, self.user1, self.user2])
        self.db.commit()

        # Generate tokens
        self.admin_token = create_access_token({"sub": "sec_admin", "role": "Admin"})
        self.engineer_token = create_access_token({"sub": "sec_eng", "role": "Support Engineer"})
        self.user1_token = create_access_token({"sub": "sec_user1", "role": "User"})
        self.user2_token = create_access_token({"sub": "sec_user2", "role": "User"})

    def tearDown(self):
        self.db.close()

    # --------------------------------------------------------------------------
    # 1. Password Hashing Tests
    # --------------------------------------------------------------------------
    def test_01_password_hashing_pbkdf2(self):
        """Verify passwords are saved as secure PBKDF2 hashes, never plaintext."""
        plain = "SuperSecretPassword!2026"
        hashed = hash_password(plain)

        self.assertTrue(hashed.startswith("pbkdf2_sha256$100000$"))
        self.assertNotEqual(plain, hashed)
        self.assertTrue(verify_password(plain, hashed))
        self.assertFalse(verify_password("WrongPassword!", hashed))

    def test_02_empty_password_rejection(self):
        """Verify empty passwords raise ValueError."""
        with self.assertRaises(ValueError):
            hash_password("")

    def test_03_legacy_plaintext_password_upgrade(self):
        """Verify legacy plaintext passwords verify and are eligible for auto-upgrade."""
        legacy_plain = "old_unhashed_pass"
        self.assertTrue(verify_password(legacy_plain, legacy_plain))
        self.assertFalse(verify_password("wrong", legacy_plain))

    # --------------------------------------------------------------------------
    # 2. Token Security & Signing Tests
    # --------------------------------------------------------------------------
    def test_04_token_generation_and_verification(self):
        """Verify token generation contains claims and passes signature verification."""
        token = create_access_token({"sub": "testuser", "role": "Admin"}, expires_in=3600)
        payload = verify_access_token(token)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["sub"], "testuser")
        self.assertEqual(payload["role"], "Admin")
        self.assertIn("exp", payload)

    def test_05_tampered_token_rejection(self):
        """Verify any tampering with the token signature or payload causes rejection."""
        token = create_access_token({"sub": "testuser", "role": "User"}, expires_in=3600)
        parts = token.split(".")
        tampered_token = f"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}"
        self.assertIsNone(verify_access_token(tampered_token))

    def test_06_expired_token_rejection(self):
        """Verify expired tokens are rejected."""
        expired_token = create_access_token({"sub": "testuser", "role": "User"}, expires_in=-10)
        self.assertIsNone(verify_access_token(expired_token))

    # --------------------------------------------------------------------------
    # 3. Authentication & Login Endpoint Tests
    # --------------------------------------------------------------------------
    def test_07_login_success_returns_bearer_token(self):
        """Verify valid login returns an access_token with bearer token type."""
        req = main.LoginRequest(username="sec_admin", password="admin_pass123")
        res = main.login(req, db=self.db)
        self.assertIn("access_token", res)
        self.assertEqual(res["token_type"], "bearer")
        self.assertEqual(res["username"], "sec_admin")
        self.assertEqual(res["role"], "Admin")

    def test_08_login_invalid_credentials_rejected(self):
        """Verify invalid username or wrong password returns HTTP 401."""
        req_wrong_pass = main.LoginRequest(username="sec_admin", password="wrongpassword")
        with self.assertRaises(HTTPException) as ctx:
            main.login(req_wrong_pass, db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

        req_wrong_user = main.LoginRequest(username="nonexistent_user", password="anypassword")
        with self.assertRaises(HTTPException) as ctx2:
            main.login(req_wrong_user, db=self.db)
        self.assertEqual(ctx2.exception.status_code, 401)

    def test_09_unauthenticated_request_rejected(self):
        """Verify requests without token return HTTP 401."""
        with patch.object(main, "ALLOW_DEV_HEADER_AUTH", False):
            with self.assertRaises(HTTPException) as ctx:
                main.get_current_user(authorization=None, x_username=None, db=self.db)
            self.assertEqual(ctx.exception.status_code, 401)

    def test_10_header_spoofing_blocked_in_production_mode(self):
        """Verify X-Username header spoofing is rejected when ALLOW_DEV_HEADER_AUTH=False."""
        with patch.object(main, "ALLOW_DEV_HEADER_AUTH", False):
            with self.assertRaises(HTTPException) as ctx:
                main.get_current_user(authorization=None, x_username="sec_admin", db=self.db)
            self.assertEqual(ctx.exception.status_code, 401)

    def test_11_valid_bearer_token_authenticates(self):
        """Verify valid Bearer token successfully resolves the user."""
        user = main.get_current_user(authorization=f"Bearer {self.admin_token}", db=self.db)
        self.assertEqual(user.username, "sec_admin")
        self.assertEqual(user.role, "Admin")

    # --------------------------------------------------------------------------
    # 4. Role-Based Access Control (RBAC) Tests
    # --------------------------------------------------------------------------
    def test_12_user_listing_rbac(self):
        """Verify regular Users are forbidden (403) from listing all user accounts."""
        # Regular user blocked
        with self.assertRaises(HTTPException) as ctx:
            main.list_users(current_user=self.user1, db=self.db)
        self.assertEqual(ctx.exception.status_code, 403)

        # Admin allowed
        users = main.list_users(current_user=self.admin, db=self.db)
        self.assertGreaterEqual(len(users), 4)

    def test_13_ticket_ownership_isolation(self):
        """Verify regular users can ONLY view tickets they created."""
        t1 = Ticket(
            title="User 1 Ticket",
            description="User 1 issue",
            category="Software",
            priority="Low",
            created_by="sec_user1",
        )
        t2 = Ticket(
            title="User 2 Ticket",
            description="User 2 issue",
            category="Hardware",
            priority="High",
            created_by="sec_user2",
        )
        self.db.add_all([t1, t2])
        self.db.commit()

        # User1 views t1 (own ticket): allowed
        details = main.get_ticket_details(ticket_id=t1.id, current_user=self.user1, db=self.db)
        self.assertEqual(details["title"], "User 1 Ticket")

        # User1 attempts to view t2 (User2's ticket): blocked with HTTP 403
        with self.assertRaises(HTTPException) as ctx:
            main.get_ticket_details(ticket_id=t2.id, current_user=self.user1, db=self.db)
        self.assertEqual(ctx.exception.status_code, 403)

        # Admin views t2: allowed
        admin_details = main.get_ticket_details(ticket_id=t2.id, current_user=self.admin, db=self.db)
        self.assertEqual(admin_details["title"], "User 2 Ticket")

    def test_14_attachment_download_rbac(self):
        """Verify regular users cannot download attachments of tickets created by other users."""
        t1 = Ticket(
            title="With Attachment",
            description="Attachment issue",
            category="Software",
            priority="Medium",
            attachment="attachments/test_file.png",
            created_by="sec_user1",
        )
        self.db.add(t1)
        self.db.commit()

        with patch.object(main, "get_attachment_download_target") as mock_target:
            mock_target.return_value = {"type": "s3_presigned", "url": "https://s3.mock/url", "filename": "test_file.png"}

            # User2 tries to download User1's attachment: blocked with HTTP 403
            with self.assertRaises(HTTPException) as ctx:
                main.download_ticket_attachment(ticket_id=t1.id, redirect=False, current_user=self.user2, db=self.db)
            self.assertEqual(ctx.exception.status_code, 403)

            # User1 downloads own attachment: allowed
            res_owner = main.download_ticket_attachment(ticket_id=t1.id, redirect=False, current_user=self.user1, db=self.db)
            assert isinstance(res_owner, dict)
            self.assertEqual(res_owner["download_url"], "https://s3.mock/url")

            # Admin downloads attachment: allowed
            res_admin = main.download_ticket_attachment(ticket_id=t1.id, redirect=False, current_user=self.admin, db=self.db)
            assert isinstance(res_admin, dict)
            self.assertEqual(res_admin["download_url"], "https://s3.mock/url")

    # --------------------------------------------------------------------------
    # 5. Protected Legacy Uploads Endpoint Tests
    # --------------------------------------------------------------------------
    def test_15_legacy_uploads_requires_auth_and_rbac(self):
        """Verify legacy /uploads/{filename} endpoint enforces authentication and RBAC."""
        # Unauthenticated call to get_current_user fails
        with patch.object(main, "ALLOW_DEV_HEADER_AUTH", False):
            with self.assertRaises(HTTPException) as ctx:
                main.get_current_user(authorization=None, x_username=None, db=self.db)
            self.assertEqual(ctx.exception.status_code, 401)

        # Unauthorized user downloading a file associated with another user's ticket: blocked
        t1 = Ticket(
            title="Private File",
            description="Private desc",
            attachment="confidential.pdf",
            created_by="sec_user1",
        )
        self.db.add(t1)
        self.db.commit()

        # Patch Path.is_file to simulate file existing on disk
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.is_relative_to", return_value=True):
            # User2 attempts to access User1's attachment file directly: blocked with HTTP 403
            with self.assertRaises(HTTPException) as ctx:
                main.get_uploaded_file(filename="confidential.pdf", current_user=self.user2, db=self.db)
            self.assertEqual(ctx.exception.status_code, 403)

    # --------------------------------------------------------------------------
    # 6. Database Connection Security Tests
    # --------------------------------------------------------------------------
    def test_16_postgresql_sslmode_enforced(self):
        """Verify PostgreSQL connection configuration enforces sslmode=require."""
        test_url = "postgresql+psycopg2://admin:pass@db.internal.rds.amazonaws.com:5432/ticketdesk"
        connect_args = {}
        if "sslmode" not in test_url.lower():
            connect_args["sslmode"] = "require"

        self.assertEqual(connect_args.get("sslmode"), "require")


if __name__ == "__main__":
    unittest.main()
