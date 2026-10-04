import base64
import hashlib
import json
import tempfile
import unittest
import sys
import importlib
from pathlib import Path
from unittest.mock import patch
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import profile_update
except ModuleNotFoundError:
    sys.modules["profile_update"] = importlib.import_module("profile_update_helper")
from profile_update import (FacebookAbout, UpdateError, canonical_payload,
                            run_update, verify_plan, verify_repository)


def presence(value="Old", present=True):
    return {"present": present, "value": value}


class FakeAPI:
    def __init__(self, current=None, error=None, applies=True, read_error_after=False):
        self.current = current if current is not None else presence()
        self.error, self.applies, self.read_error_after = error, applies, read_error_after
        self.writes = 0
        self.before_write = lambda: None
    def read(self, payload):
        if self.writes and self.read_error_after:
            raise UpdateError("request_failed")
        return self.current
    def write(self, payload):
        self.before_write()
        self.writes += 1
        if self.applies:
            self.current = presence(payload["about_after"])
        if self.error:
            raise self.error


class FakeSync:
    def __init__(self, fails=False):
        self.states, self.fails = [], fails
    def __call__(self, path):
        ledger = json.loads(path.read_text(encoding="utf-8"))
        self.states.append(list(ledger.values())[-1]["state"])
        if self.fails:
            raise UpdateError("ledger_push_failed")


class SignedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()  # Synthetic test key; no real key is read.
        public = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.channel = {"page_id": "123", "name": "A page", "platform": "facebook", "editor_public_key": public}
        self.payload = {"channel": "a", "page_id": "123", "page_name": "A page", "about_before": presence(), "about_after": "New"}
        self.plan = self.signed(self.payload)
    def signed(self, payload):
        digest = hashlib.sha256(canonical_payload(payload)).hexdigest()
        return {"payload": payload, "payload_sha256": digest,
                "root_signature": base64.b64encode(self.key.sign(digest.encode("ascii"))).decode()}
    def run_plan(self, api=None, publish=True, sync=None, plan=None):
        return run_update(plan or self.plan, "a", self.channel, api or FakeAPI(), self.root, publish,
                          sync if sync is not None else FakeSync())
    def test_signed_plan_accepted(self):
        payload, digest = verify_plan(self.plan, "a", self.channel)
        self.assertEqual(payload, self.payload)
        self.assertEqual(len(digest), 64)
    def test_hash_tampering_and_resigning_without_real_key_rejected(self):
        altered = json.loads(json.dumps(self.plan))
        altered["payload"]["about_after"] = "Unauthorized"
        with self.assertRaisesRegex(UpdateError, "payload_hash_mismatch"):
            verify_plan(altered, "a", self.channel)
        altered["payload_sha256"] = hashlib.sha256(canonical_payload(altered["payload"])).hexdigest()
        with self.assertRaisesRegex(UpdateError, "invalid_root_signature"):
            verify_plan(altered, "a", self.channel)
    def test_extra_write_fields_rejected_even_if_signed(self):
        for field in ["website", "name", "description"]:
            with self.assertRaisesRegex(UpdateError, "invalid_payload_schema"):
                verify_plan(self.signed({**self.payload, field: "Other"}), "a", self.channel)
    def test_wrong_channel_page_and_name_rejected(self):
        for field, value in [("channel", "b"), ("page_id", "999"), ("page_name", "Other")]:
            with self.assertRaisesRegex(UpdateError, "plan_channel_identity_mismatch"):
                verify_plan(self.signed({**self.payload, field: value}), "a", self.channel)
    def test_dry_run_does_not_create_ledger_or_call_sync_or_post(self):
        api, sync = FakeAPI(), FakeSync()
        result = self.run_plan(api, publish=False, sync=sync)
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(api.writes, 0)
        self.assertEqual(sync.states, [])
        self.assertEqual(list(self.root.iterdir()), [])
    def test_success_reserved_durable_before_post_and_readback(self):
        api, sync = FakeAPI(), FakeSync()
        api.before_write = lambda: self.assertEqual(sync.states, ["reserved"])
        result = self.run_plan(api, sync=sync)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(sync.states, ["reserved", "written_pending_readback", "verified"])
        self.assertEqual(api.writes, 1)
        self.assertEqual(self.run_plan(api, sync=sync)["status"], "verified_already_matches")
        self.assertEqual(api.writes, 1)
    def test_sync_failure_before_post_prevents_write(self):
        api = FakeAPI()
        with self.assertRaisesRegex(UpdateError, "ledger_push_failed"):
            self.run_plan(api, sync=FakeSync(True))
        self.assertEqual(api.writes, 0)
        self.assertEqual(self.run_plan(api)["status"], "hold_prior_attempt")
        self.assertEqual(api.writes, 0)
    def test_before_changed_holds_without_ledger_or_write(self):
        api = FakeAPI(presence("Someone edited this"))
        self.assertEqual(self.run_plan(api)["status"], "hold_before_changed")
        self.assertEqual(api.writes, 0)
        self.assertFalse((self.root / "profile_update_ledger.json").exists())
    def test_absent_before_is_supported_without_claiming_empty(self):
        plan = self.signed({**self.payload, "about_before": presence(None, False)})
        api = FakeAPI(presence(None, False))
        result = self.run_plan(api, plan=plan)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(api.writes, 1)
    def test_empty_and_absent_before_are_different(self):
        plan = self.signed({**self.payload, "about_before": presence(None, False)})
        api = FakeAPI(presence("", True))
        self.assertEqual(self.run_plan(api, plan=plan)["status"], "hold_before_changed")
        self.assertEqual(api.writes, 0)
    def test_invalid_presence_schema_rejected(self):
        for before in [None, "", {"present": False, "value": ""}, {"present": 0, "value": None}, {"present": True}]:
            with self.assertRaisesRegex(UpdateError, "invalid_before_presence"):
                verify_plan(self.signed({**self.payload, "about_before": before}), "a", self.channel)
    def test_ambiguous_write_unchanged_is_held_without_retry(self):
        api = FakeAPI(error=UpdateError("request_failed", ambiguous=True), applies=False)
        self.assertEqual(self.run_plan(api)["status"], "hold_write_unconfirmed")
        self.assertEqual(api.writes, 1)
        self.assertEqual(self.run_plan(api)["status"], "hold_prior_attempt")
        self.assertEqual(api.writes, 1)
    def test_ambiguous_write_applied_reconciles_via_read_only(self):
        api = FakeAPI(error=UpdateError("request_failed", ambiguous=True))
        self.assertEqual(self.run_plan(api)["status"], "verified_reconciled")
        self.assertEqual(api.writes, 1)
    def test_known_failure_also_holds_without_retry(self):
        api = FakeAPI(error=UpdateError("api_request_failed", 400, 200), applies=False)
        sync = FakeSync()
        self.assertEqual(self.run_plan(api, sync=sync)["status"], "hold_write_unconfirmed")
        self.assertEqual(sync.states, ["reserved", "failed"])
        self.assertEqual(self.run_plan(api)["status"], "hold_prior_attempt")
        self.assertEqual(api.writes, 1)
    def test_new_signature_cannot_bypass_unreconciled_old_attempt(self):
        api = FakeAPI(error=UpdateError("request_failed", ambiguous=True), applies=False)
        self.run_plan(api)
        new_plan = self.signed({**self.payload, "about_after": "Another new bio"})
        self.assertEqual(self.run_plan(api, plan=new_plan)["status"], "hold_other_unreconciled_plan")
        self.assertEqual(api.writes, 1)
    def test_success_unreadable_remains_pending_no_retry(self):
        api = FakeAPI(read_error_after=True)
        self.assertEqual(self.run_plan(api)["status"], "hold_readback_failed")
        api.read_error_after = False
        self.assertEqual(self.run_plan(api)["status"], "verified_already_matches")
        self.assertEqual(api.writes, 1)
    def test_publish_requires_durable_sync(self):
        api = FakeAPI()
        with self.assertRaisesRegex(UpdateError, "durable_sync_required"):
            run_update(self.plan, "a", self.channel, api, self.root, True)
        self.assertEqual(api.writes, 0)
    def test_sync_failure_after_post_preserves_reservation_no_retry(self):
        class FailSecond(FakeSync):
            def __call__(self, path):
                super().__call__(path)
                if len(self.states) == 2:
                    raise UpdateError("ledger_push_failed")
        api = FakeAPI()
        with self.assertRaises(UpdateError):
            self.run_plan(api, sync=FailSecond())
        self.assertEqual(api.writes, 1)
        self.assertEqual(self.run_plan(api)["status"], "verified_already_matches")
        self.assertEqual(api.writes, 1)


class Response:
    def __init__(self, data, code=200):
        self.data, self.status_code = data, code
    def json(self):
        return self.data


class Session:
    def __init__(self, values):
        self.values, self.calls = list(values), []
    def call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value
    def get(self, url, **kwargs):
        return self.call("get", url, **kwargs)
    def post(self, url, **kwargs):
        return self.call("post", url, **kwargs)


class FacebookAdapterTests(unittest.TestCase):
    payload = {"page_id": "123", "page_name": "A page", "about_after": "New"}
    def test_post_contains_only_about_bearer_no_url_token(self):
        session = Session([Response({"success": True})])
        FacebookAbout("test-secret", session).write(self.payload)
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "post")
        self.assertEqual(kwargs["data"], {"about": "New"})
        self.assertNotIn("test-secret", url)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")
    def test_identity_mismatch_prevents_profile_request(self):
        for identity in [{"id": "999", "name": "A page"}, {"id": "123", "name": "Other"}]:
            session = Session([Response(identity)])
            with self.assertRaisesRegex(UpdateError, "live_identity_mismatch"):
                FacebookAbout("test", session).read(self.payload)
            self.assertEqual(len(session.calls), 1)
    def test_absent_about_retains_presence_false(self):
        identity = {"id": "123", "name": "A page"}
        self.assertEqual(FacebookAbout("test", Session([Response(identity), Response(identity)])).read(self.payload), presence(None, False))
    def test_write_timeout_and_5xx_are_ambiguous_redacted(self):
        for response in [requests.Timeout("test-secret"), Response({"error": {"code": 2, "message": "test-secret"}}, 500)]:
            with self.assertRaises(UpdateError) as raised:
                FacebookAbout("test-secret", Session([response])).write(self.payload)
            self.assertTrue(raised.exception.ambiguous)
            self.assertNotIn("test-secret", json.dumps(raised.exception.details))
    def test_400_is_known_failure_200_error_is_not_success(self):
        for code, ambiguous in [(400, False), (200, True)]:
            with self.assertRaises(UpdateError) as raised:
                FacebookAbout("test", Session([Response({"error": {"code": 190, "message": "hidden"}}, code)])).write(self.payload)
            self.assertEqual(raised.exception.ambiguous, ambiguous)
    def test_repository_gate_checks_expected_slug(self):
        class Result:
            returncode = 0
            stdout = "https://github.com/user/other.git\n"
        with patch("profile_update.subprocess.run", return_value=Result()):
            with self.assertRaisesRegex(UpdateError, "repository_identity_mismatch"):
                verify_repository(Path("."), {"repository_slug": "user/expected"})


if __name__ == "__main__":
    unittest.main()
