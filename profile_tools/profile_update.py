"""Signed, single-field Facebook About changes with durable ambiguity holds."""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


class UpdateError(Exception):
    def __init__(self, reason, status=None, code=None, ambiguous=False):
        self.details = {"reason": reason}
        if status is not None:
            self.details["http_status"] = status
        if isinstance(code, (int, float)):
            self.details["api_error_code"] = code
        self.ambiguous = ambiguous
        super().__init__(reason)


def canonical_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_plan(plan, channel_key, channel):
    if set(plan) != {"payload", "payload_sha256", "root_signature"}:
        raise UpdateError("invalid_plan_schema")
    payload = plan["payload"]
    fields = {"channel", "page_id", "page_name", "about_before", "about_after"}
    if not isinstance(payload, dict) or set(payload) != fields or not all(isinstance(payload[x], str) for x in fields - {"about_before"}):
        raise UpdateError("invalid_payload_schema")
    before = payload["about_before"]
    if (not isinstance(before, dict) or set(before) != {"present", "value"}
            or not isinstance(before["present"], bool)
            or before["value"] is not None and not isinstance(before["value"], str)
            or not before["present"] and before["value"] is not None):
        raise UpdateError("invalid_before_presence")
    if (payload["channel"] != channel_key or payload["page_id"] != str(channel["page_id"])
            or payload["page_name"] != channel.get("page_name", channel.get("name"))
            or channel.get("platform") != "facebook"):
        raise UpdateError("plan_channel_identity_mismatch")
    if not payload["page_id"].isdecimal() or not payload["about_after"].strip() or len(payload["about_after"]) > 255:
        raise UpdateError("invalid_about_or_page_id")
    if before == {"present": True, "value": payload["about_after"]}:
        raise UpdateError("no_profile_change")
    digest = hashlib.sha256(canonical_payload(payload)).hexdigest()
    if plan["payload_sha256"] != digest:
        raise UpdateError("payload_hash_mismatch")
    try:
        key = serialization.load_pem_public_key(channel["editor_public_key"].encode("utf-8"))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("wrong key type")
        key.verify(base64.b64decode(plan["root_signature"], validate=True), digest.encode("ascii"))
    except (InvalidSignature, ValueError, TypeError, KeyError):
        raise UpdateError("invalid_root_signature") from None
    return payload, digest


class FacebookAbout:
    def __init__(self, token, session=None):
        if not isinstance(token, str) or not token:
            raise UpdateError("missing_page_access_token")
        self.token, self.session = token, session or requests.Session()

    def request(self, method, path, **kwargs):
        try:
            response = getattr(self.session, method)("https://graph.facebook.com/v25.0/" + path,
                headers={"Authorization": "Bearer " + self.token}, timeout=30, **kwargs)
            data = response.json()
        except requests.RequestException:
            raise UpdateError("request_failed", ambiguous=method == "post") from None
        except ValueError:
            raise UpdateError("non_json_response", ambiguous=method == "post") from None
        if not isinstance(data, dict):
            raise UpdateError("unexpected_response_shape", response.status_code, ambiguous=method == "post")
        if response.status_code != 200 or "error" in data:
            error = data.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise UpdateError("api_request_failed", response.status_code, code,
                              ambiguous=method == "post" and not 400 <= response.status_code < 500)
        return data

    def read(self, payload):
        identity = self.request("get", "me", params={"fields": "id,name"})
        expected = {"id": payload["page_id"], "name": payload["page_name"]}
        if any(str(identity.get(k)) != v for k, v in expected.items()):
            raise UpdateError("live_identity_mismatch")
        profile = self.request("get", payload["page_id"], params={"fields": "id,name,about"})
        if any(str(profile.get(k)) != v for k, v in expected.items()):
            raise UpdateError("live_profile_identity_mismatch")
        if profile.get("about") is not None and not isinstance(profile["about"], str):
            raise UpdateError("invalid_live_about_shape")
        return {"present": "about" in profile, "value": profile.get("about")}

    def write(self, payload):
        result = self.request("post", payload["page_id"], data={"about": payload["about_after"]})
        if result.get("success") is not True:
            raise UpdateError("write_result_unconfirmed", ambiguous=True)


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class GitLedgerSync:
    def __init__(self, root, branch="main"):
        self.root, self.branch = Path(root), branch
    def git(self, *args, optional=False):
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if result.returncode and not optional:
            raise UpdateError("git_state_operation_failed")
        return result
    def __call__(self, path):
        name = path.relative_to(self.root).as_posix()
        staged = self.git("diff", "--cached", "--name-only").stdout.splitlines()
        if any(x != name for x in staged):
            raise UpdateError("unrelated_staged_files")
        self.git("add", "--", name)
        if self.git("diff", "--cached", "--quiet", optional=True).returncode:
            self.git("commit", "-m", "Record root-approved About change state", "--", name)
        for _ in range(3):
            if not self.git("push", "origin", "HEAD:refs/heads/" + self.branch, optional=True).returncode:
                return
            self.git("fetch", "origin", self.branch)
            self.git("rebase", "origin/" + self.branch)
        raise UpdateError("ledger_push_failed")


def verify_repository(root, channel):
    result = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True, text=True)
    slug = channel.get("repository_slug")
    if result.returncode or not slug or not re.search(r"github\.com[:/]" + re.escape(slug) + r"(?:\.git)?/?$", result.stdout.strip()):
        raise UpdateError("repository_identity_mismatch")


def run_update(plan, key, channel, api, root, publish=False, sync=None):
    payload, digest = verify_plan(plan, key, channel)
    root = Path(root)
    ledger_path = root / "profile_update_ledger.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    except (OSError, ValueError):
        raise UpdateError("invalid_profile_ledger") from None
    if not isinstance(ledger, dict):
        raise UpdateError("invalid_profile_ledger")
    current = api.read(payload)
    previous = ledger.get(digest)
    after = {"present": True, "value": payload["about_after"]}
    result = {"channel": key, "page_id": payload["page_id"], "payload_sha256": digest,
              "current_about": current, "external_writes_this_run": 0,
              "checked_at": datetime.now(timezone.utc).isoformat()}
    def persist(state, **details):
        ledger[digest] = {"state": state, "channel": key, "page_id": payload["page_id"],
                          "updated_at": datetime.now(timezone.utc).isoformat(), **details}
        atomic_json(ledger_path, ledger)
        if sync:
            sync(ledger_path)
    if not publish:
        return {**result, "status": "dry_run_already_matches" if current == after else
                "dry_run_ready" if current == payload["about_before"] and previous is None else "dry_run_hold"}
    if sync is None:
        raise UpdateError("durable_sync_required")
    if current == after:
        persist("verified", readback_about=current)
        return {**result, "status": "verified_already_matches"}
    if previous is not None:
        return {**result, "status": "hold_prior_attempt", "prior_state": previous.get("state")}
    if any(isinstance(item, dict) and item.get("page_id") == payload["page_id"]
           and item.get("state") != "verified" for item in ledger.values()):
        return {**result, "status": "hold_other_unreconciled_plan"}
    if current != payload["about_before"]:
        return {**result, "status": "hold_before_changed"}
    persist("reserved")  # Remote durable state must exist before the single POST.
    try:
        api.write(payload)
    except UpdateError as error:
        persist("unknown" if error.ambiguous else "failed", error=error.details)
        try:
            actual = api.read(payload)
        except UpdateError:
            return {**result, "status": "hold_write_unconfirmed", "external_writes_this_run": 1}
        if actual == after:
            persist("verified", readback_about=actual)
            return {**result, "status": "verified_reconciled", "current_about": actual, "external_writes_this_run": 1}
        return {**result, "status": "hold_write_unconfirmed", "current_about": actual, "external_writes_this_run": 1}
    persist("written_pending_readback")
    try:
        actual = api.read(payload)
    except UpdateError:
        return {**result, "status": "hold_readback_failed", "external_writes_this_run": 1}
    if actual != after:
        return {**result, "status": "hold_readback_mismatch", "current_about": actual, "external_writes_this_run": 1}
    persist("verified", readback_about=actual)
    return {**result, "status": "verified", "current_about": actual, "external_writes_this_run": 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--plan", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--git-state", action="store_true")
    args = parser.parse_args()
    tool_dir = Path(__file__).resolve().parent
    root = tool_dir.parent
    lock = root / "profile_update_ledger.lock"
    acquired = False
    try:
        channels = json.loads((tool_dir / "channels.json").read_text(encoding="utf-8"))
        channel = channels[args.channel]
        verify_repository(root, channel)
        plan_path = (root / args.plan).resolve()
        if not plan_path.is_relative_to(tool_dir / "plans"):
            raise UpdateError("plan_path_outside_reviewed_directory")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        verify_plan(plan, args.channel, channel)
        if args.publish:
            if not args.git_state:
                raise UpdateError("durable_sync_required")
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                raise UpdateError("profile_update_locked") from None
            acquired = True
        api = FacebookAbout(os.environ.get("PAGE_ACCESS_TOKEN"))
        result = run_update(plan, args.channel, channel, api, root, args.publish,
                            GitLedgerSync(root) if args.publish else None)
    except UpdateError as error:
        result = {"channel": args.channel, "status": "held", "error": error.details}
    except (OSError, ValueError, KeyError, TypeError):
        result = {"channel": args.channel, "status": "held", "error": {"reason": "invalid_local_plan_or_config"}}
    finally:
        if acquired:
            lock.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"verified", "verified_already_matches", "verified_reconciled", "dry_run_ready", "dry_run_already_matches"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
