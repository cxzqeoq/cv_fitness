import unittest
import uuid
from types import SimpleNamespace

from app.auth import (
    _csrf_from_body,
    _oidc_metadata,
    _is_public,
    staff_access_allowed,
    start_session,
)
from app.routers.auth import _oidc_identity


class SessionTests(unittest.TestCase):
    def test_session_keeps_tenant_with_local_principal(self):
        request = SimpleNamespace(session={"stale": True})
        org_id = uuid.uuid4()

        start_session(request, kind="student", account_id=42, org_id=org_id)

        self.assertEqual(
            request.session["principal"],
            {"kind": "student", "account_id": 42, "org_id": str(org_id)},
        )
        self.assertNotIn("stale", request.session)


class OidcIdentityTests(unittest.TestCase):
    def test_requires_subject_email_and_active_organization_membership(self):
        org_id = uuid.uuid4()
        self.assertEqual(
            _oidc_identity(
                {
                    "sub": "user-1",
                    "email": "USER@example.com",
                    "email_verified": True,
                    "org_id": str(org_id),
                    "org_role": "member",
                }
            ),
            ("user-1", "user@example.com", org_id),
        )
        self.assertIsNone(
            _oidc_identity(
                {
                    "sub": "user-1",
                    "email": "user@example.com",
                    "org_id": str(org_id),
                }
            )
        )


class StaffAccessTests(unittest.TestCase):
    def test_owner_manager_editor_permissions(self):
        self.assertTrue(staff_access_allowed("/team", "GET", "owner"))
        self.assertFalse(staff_access_allowed("/team", "GET", "manager"))
        self.assertTrue(staff_access_allowed("/students", "GET", "manager"))
        self.assertFalse(staff_access_allowed("/students", "GET", "editor"))
        self.assertTrue(staff_access_allowed("/app/1/segments/2", "POST", "editor"))
        self.assertFalse(staff_access_allowed("/app/1/delete", "POST", "manager"))
        self.assertFalse(staff_access_allowed("/app/1/publish", "POST", "editor"))
        self.assertTrue(staff_access_allowed("/programs/1", "POST", "editor"))
        self.assertFalse(staff_access_allowed("/programs/1/enroll", "POST", "editor"))
        self.assertTrue(staff_access_allowed("/programs/1/enroll", "POST", "manager"))

    def test_landing_is_public_and_staff_app_is_private(self):
        self.assertTrue(_is_public("/"))
        self.assertTrue(_is_public("/pilot"))
        self.assertFalse(_is_public("/app"))
        self.assertFalse(_is_public("/app/1"))


class OidcMetadataTests(unittest.TestCase):
    def test_browser_endpoint_stays_public_and_server_calls_use_internal_url(self):
        metadata = _oidc_metadata("https://omra.is/", "http://omra-is:8000/")

        self.assertEqual(metadata["issuer"], "https://omra.is")
        self.assertEqual(metadata["authorization_endpoint"], "https://omra.is/oauth/authorize")
        self.assertEqual(metadata["token_endpoint"], "http://omra-is:8000/oauth/token")
        self.assertEqual(metadata["jwks_uri"], "http://omra-is:8000/jwks.json")
        self.assertEqual(metadata["id_token_signing_alg_values_supported"], ["EdDSA"])


class CsrfParsingTests(unittest.TestCase):
    def test_reads_urlencoded_and_multipart_form_tokens(self):
        self.assertEqual(
            _csrf_from_body(
                b"name=Alice&csrf_token=abc123",
                "application/x-www-form-urlencoded",
            ),
            "abc123",
        )
        self.assertEqual(
            _csrf_from_body(
                b'--boundary\r\nContent-Disposition: form-data; name="csrf_token"\r\n\r\nxyz789\r\n--boundary--\r\n',
                "multipart/form-data; boundary=boundary",
            ),
            "xyz789",
        )


if __name__ == "__main__":
    unittest.main()
