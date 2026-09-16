import unittest

from app.auth import (
    _csrf_from_body,
    _oidc_metadata,
    hash_password,
    staff_access_allowed,
    verify_password,
)


class PasswordTests(unittest.TestCase):
    def test_argon2_hash_roundtrip_and_wrong_password(self):
        password_hash = hash_password("correct horse battery staple")

        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertNotIn("correct horse", password_hash)
        self.assertTrue(verify_password(password_hash, "correct horse battery staple"))
        self.assertFalse(verify_password(password_hash, "wrong password"))


class StaffAccessTests(unittest.TestCase):
    def test_owner_manager_editor_permissions(self):
        self.assertTrue(staff_access_allowed("/team", "GET", "owner"))
        self.assertFalse(staff_access_allowed("/team", "GET", "manager"))
        self.assertTrue(staff_access_allowed("/students", "GET", "manager"))
        self.assertFalse(staff_access_allowed("/students", "GET", "editor"))
        self.assertTrue(staff_access_allowed("/1/segments/2", "POST", "editor"))
        self.assertFalse(staff_access_allowed("/1/delete", "POST", "manager"))
        self.assertFalse(staff_access_allowed("/1/publish", "POST", "editor"))


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
