"""Read-only Facebook profile audit. Never updates a profile or prints credentials."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import requests


class AuditError(Exception):
    def __init__(self, reason, http_status=None, api_error_code=None):
        self.details = {"reason": reason}
        if http_status is not None:
            self.details["http_status"] = http_status
        if isinstance(api_error_code, (int, float)):
            self.details["api_error_code"] = api_error_code
        super().__init__(reason)


class ProfileReader:
    def __init__(self, token, session=None):
        if not isinstance(token, str) or not token:
            raise AuditError("missing_page_access_token")
        self.token = token
        self.session = session or requests.Session()

    def get(self, path, fields):
        try:
            response = self.session.get(
                "https://graph.facebook.com/v25.0/" + path,
                params={"fields": fields},
                headers={"Authorization": "Bearer " + self.token}, timeout=30)
            data = response.json()
        except requests.RequestException:
            raise AuditError("request_failed") from None
        except ValueError:
            raise AuditError("non_json_response") from None
        if not isinstance(data, dict):
            raise AuditError("unexpected_response_shape", response.status_code)
        if response.status_code != 200 or "error" in data:
            error = data.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise AuditError("api_read_failed", response.status_code, code)
        return data


def audit(channel_key, channel, reader):
    expected_id = str(channel["page_id"])
    expected_name = channel.get("page_name", channel.get("name"))
    if channel.get("platform") != "facebook" or not expected_id.isdecimal() or not expected_name:
        raise AuditError("invalid_facebook_channel")
    identity = reader.get("me", "id,name")
    if str(identity.get("id")) != expected_id or identity.get("name") != expected_name:
        raise AuditError("identity_mismatch")
    fields = ["about", "description", "website"]
    unavailable = {}
    try:
        profile = reader.get(expected_id, "id,name," + ",".join(fields))
    except AuditError as error:
        if error.details["reason"] != "api_read_failed":
            raise
        profile = reader.get(expected_id, "id,name")
        for field in fields:
            try:
                result = reader.get(expected_id, "id,name," + field)
                if str(result.get("id")) != expected_id or result.get("name") != expected_name:
                    raise AuditError("profile_identity_mismatch")
                if field in result:
                    profile[field] = result[field]
                else:
                    unavailable[field] = {"reason": "field_not_returned"}
            except AuditError as field_error:
                if field_error.details["reason"] == "profile_identity_mismatch":
                    raise
                unavailable[field] = field_error.details
    if str(profile.get("id")) != expected_id or profile.get("name") != expected_name:
        raise AuditError("profile_identity_mismatch")
    for field in fields:
        if field not in profile and field not in unavailable:
            unavailable[field] = {"reason": "field_not_returned"}
    return {"channel": channel_key, "status": "read_verified", "identity": identity,
            "profile": {key: profile.get(key) for key in ["id", "name"] + fields},
            "returned_fields": list(profile), "unavailable_fields": unavailable,
            "checked_at": datetime.now(timezone.utc).isoformat(), "external_writes": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True)
    args = parser.parse_args()
    try:
        channels = json.loads((Path(__file__).parent / "channels.json").read_text(encoding="utf-8"))
        if args.channel not in channels:
            raise AuditError("unknown_channel")
        result = audit(args.channel, channels[args.channel], ProfileReader(os.environ.get("PAGE_ACCESS_TOKEN")))
        code = 0
    except AuditError as error:
        result = {"channel": args.channel, "status": "read_failed", "error": error.details,
                  "external_writes": 0, "checked_at": datetime.now(timezone.utc).isoformat()}
        code = 1
    except (OSError, ValueError, KeyError, TypeError):
        result = {"channel": args.channel, "status": "read_failed", "error": {"reason": "invalid_local_channel_config"}, "external_writes": 0}
        code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
