import json
import sys
import unittest
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profile_audit import AuditError, ProfileReader, audit


CHANNEL = {"page_id": "123", "name": "A page", "platform": "facebook"}
IDENTITY = {"id": "123", "name": "A page"}


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def json(self):
        return self.payload


class Session:
    def __init__(self, values):
        self.values, self.calls = list(values), []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.values.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ProfileAuditTests(unittest.TestCase):
    def test_verified_profile_read_only_bearer(self):
        session = Session([Response(IDENTITY), Response({**IDENTITY, "about": "Old bio", "website": "https://example.com"})])
        result = audit("a", CHANNEL, ProfileReader("secret-test", session))
        self.assertEqual(result["profile"]["about"], "Old bio")
        self.assertIsNone(result["profile"]["description"])
        self.assertEqual(result["external_writes"], 0)
        self.assertEqual(len(session.calls), 2)
        for url, kwargs in session.calls:
            self.assertNotIn("secret-test", url)
            self.assertNotIn("access_token", kwargs["params"])
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-test")

    def test_wrong_identity_stops_before_profile(self):
        for identity in [{"id": "999", "name": "A page"}, {"id": "123", "name": "Other"}]:
            session = Session([Response(identity)])
            with self.assertRaisesRegex(AuditError, "identity_mismatch"):
                audit("a", CHANNEL, ProfileReader("test", session))
            self.assertEqual(len(session.calls), 1)

    def test_page_name_overrides_display_name(self):
        result = audit("a", {**CHANNEL, "name": "Short label", "page_name": "A page"}, ProfileReader("test", Session([Response(IDENTITY), Response(IDENTITY)])))
        self.assertEqual(result["status"], "read_verified")

    def test_200_error_payload_and_raw_error_redaction(self):
        session = Session([Response({"error": {"code": 190, "message": "secret-test"}})])
        with self.assertRaises(AuditError) as raised:
            audit("a", CHANNEL, ProfileReader("secret-test", session))
        self.assertEqual(raised.exception.details["api_error_code"], 190)
        self.assertNotIn("secret-test", json.dumps(raised.exception.details))

    def test_timeout_redacted(self):
        session = Session([requests.Timeout("secret-test")])
        with self.assertRaises(AuditError) as raised:
            audit("a", CHANNEL, ProfileReader("secret-test", session))
        self.assertEqual(raised.exception.details, {"reason": "request_failed"})

    def test_missing_token_never_requests(self):
        session = Session([])
        with self.assertRaises(AuditError):
            ProfileReader(None, session)
        self.assertEqual(session.calls, [])

    def test_optional_field_permission_failure_keeps_actual_bio(self):
        error = Response({"error": {"code": 100, "message": "hidden"}}, 400)
        session = Session([Response(IDENTITY), error, Response(IDENTITY), Response({**IDENTITY, "about": "Actual bio"}), error, Response({**IDENTITY, "website": ""})])
        result = audit("a", CHANNEL, ProfileReader("test", session))
        self.assertEqual(result["profile"]["about"], "Actual bio")
        self.assertIsNone(result["profile"]["description"])
        self.assertEqual(result["profile"]["website"], "")
        self.assertEqual(result["unavailable_fields"]["description"]["api_error_code"], 100)

    def test_profile_id_changes_fail_closed(self):
        session = Session([Response(IDENTITY), Response({"id": "999", "name": "A page"})])
        with self.assertRaisesRegex(AuditError, "profile_identity_mismatch"):
            audit("a", CHANNEL, ProfileReader("test", session))

    def test_nonfacebook_never_requests(self):
        session = Session([])
        with self.assertRaisesRegex(AuditError, "invalid_facebook_channel"):
            audit("a", {**CHANNEL, "platform": "threads"}, ProfileReader("test", session))
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
