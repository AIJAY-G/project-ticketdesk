"""
Unit tests for the application health check endpoint.
Verifies that the /health route returns HTTP 200 and healthy JSON status
for reverse proxy and load balancer liveness probes.
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app


class TestHealthCheckEndpoint(unittest.TestCase):
    """Test case for /health endpoint."""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_check_returns_200(self):
        """Verify GET /health returns HTTP 200 with service status."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "ticketdesk")


if __name__ == "__main__":
    unittest.main()
