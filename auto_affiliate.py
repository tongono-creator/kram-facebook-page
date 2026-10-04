#!/usr/bin/env python3
"""Add one disclosed Shopee affiliate reply to each new original post.

The module is deliberately independent from the publishing bots.  Platform
adapters discover live posts and their real replies; ``AffiliateReconciler``
owns selection, idempotency, reservations, and dry-run behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping
from urllib.parse import urlparse

import requests


DISCLOSURE = "ลิงก์ Affiliate — เพจอาจได้รับค่าคอมมิชชันจากการซื้อผ่านลิงก์นี้"
GRAPH_VERSION = "v25.0"
THREADS_VERSION = "v1.0"
SHOPEE_HOSTS = ("shopee.co.th", "shopee.com", "shope.ee")
URL_RE = re.compile(r"https://[^\s<>]+", re.IGNORECASE)


class ApiError(RuntimeError):
    """An intentionally redacted platform failure."""

    def __init__(self, method: str, status: int, _detail: str = "", *, code: Any = None):
        self.method, self.status, self.code = method.upper(), status, code
        suffix = f", code {code}" if code not in (None, "") else ""
        super().__init__(f"{self.method} failed (HTTP {status}{suffix})")

    @property
    def rejected(self) -> bool:
        """The server answered and refused the write, so nothing was created."""
        return 400 <= self.status < 500 and self.status not in {408, 409, 429}

    def __repr__(self) -> str:
        return f"ApiError({str(self)!r})"


class StateSyncError(RuntimeError):
    pass


class ReconciliationRequired(RuntimeError):
    """A prior write may have succeeded and must not be retried automatically."""


def parse_since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--since must include a timezone")
    return parsed.astimezone(timezone.utc)


def parse_timestamp(value: str) -> datetime:
    try:
        return parse_since(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("post timestamp must be timezone-aware ISO-8601") from exc


def _is_shopee_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and bool(host) and any(
        host == allowed or host.endswith("." + allowed) for allowed in SHOPEE_HOSTS
    )


def validate_product(product: Mapping[str, Any]) -> dict[str, str]:
    product_input = product
    name, url = str(product.get("name", "")).strip(), str(product.get("url", "")).strip()
    if not name or not _is_shopee_url(url):
        raise ValueError("product requires a name and Shopee HTTPS URL")
    product = {"name": name, "url": url}
    if "comment" in product_input:
        comment = str(product_input["comment"]).strip()
        links = URL_RE.findall(comment)
        if links != [url] or DISCLOSURE not in comment:
            raise ValueError("reviewed comment must contain its one product URL and disclosure")
        product["comment"] = comment
    return product


@dataclass(frozen=True)
class Selection:
    product: dict[str, str]
    reason: str


def _resolve_product(value: Any, config: Mapping[str, Any]) -> dict[str, str]:
    if isinstance(value, str):
        for item in config.get("catalog", []):
            if item.get("id") == value:
                return validate_product(item)
        raise ValueError(f"unknown catalog product id: {value}")
    if not isinstance(value, Mapping):
        raise ValueError("product mapping must be an object or catalog id")
    return validate_product(value)


def _post_keys(post: Mapping[str, Any]) -> list[str]:
    """Every id a publisher may have recorded for this post.

    Facebook returns ``PAGE_POST`` from the feed but a bare photo id when a
    photo is scheduled, and the page id prefix can differ between tokens.
    """
    keys: list[str] = []
    for value in [post.get("id"), *post.get("aliases", [])]:
        text = str(value or "").strip()
        for key in (text, text.rsplit("_", 1)[-1]):
            if key and key not in keys:
                keys.append(key)
    return keys


def select_product(post: Mapping[str, Any], config: Mapping[str, Any]) -> Selection:
    mapping = {str(k).rsplit("_", 1)[-1]: v for k, v in config.get("post_products", {}).items()}
    mapping.update(config.get("post_products", {}))
    for key in _post_keys(post):
        if mapping.get(key) is not None:
            return Selection(_resolve_product(mapping[key], config), "explicit")

    text = str(post.get("text", "")).casefold()
    candidates: list[tuple[int, dict[str, str]]] = []
    for raw in config.get("catalog", []):
        keywords = {str(k).strip().casefold() for k in raw.get("keywords", []) if str(k).strip()}
        excluded = {str(k).strip().casefold() for k in raw.get("exclude_keywords", []) if str(k).strip()}
        if excluded.intersection(term for term in excluded if term in text):
            continue
        hits = {term for term in keywords if term in text}
        if hits:
            candidates.append((sum(len(term) for term in hits), validate_product(raw)))
    if candidates:
        top_score = max(score for score, _ in candidates)
        winners = [product for score, product in candidates if score == top_score]
        if len(winners) == 1:
            return Selection(winners[0], "keyword")
    return Selection(validate_product(config.get("approved_fallback", {})), "fallback")


def build_comment(selection: Selection) -> str:
    product = selection.product
    if product.get("comment"):
        return product["comment"]
    if selection.reason == "fallback":
        lead = f"พิกัดสินค้าสำหรับผู้ติดตาม: {product['name']} — {product['url']}"
    else:
        lead = f"พิกัด {product['name']}: {product['url']}"
    return f"{lead}\n\n{DISCLOSURE}"


class StateStore:
    def __init__(self, path: os.PathLike[str] | str, sync: Callable[[Path], None] | None = None):
        self.path = Path(path)
        self.sync = sync
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid state file: {self.path}") from exc
        if not isinstance(loaded, dict):
            raise ValueError("state root must be an object")
        return loaded

    def get(self, platform: str, account: str, post_id: str) -> Mapping[str, Any] | None:
        return self.data.get(platform, {}).get(account, {}).get(post_id)

    def set(self, platform: str, account: str, post_id: str, status: str, **fields: Any) -> None:
        record = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
        self.data.setdefault(platform, {}).setdefault(account, {})[post_id] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        if self.sync:
            self.sync(self.path)


class GitStateSync:
    """Commit and push only the state file after each durable transition."""

    def __init__(self, branch: str | None = None):
        self.branch = branch or os.getenv("AFFILIATE_STATE_BRANCH")
        if not self.branch:
            raise StateSyncError("AFFILIATE_STATE_BRANCH is required for git state sync")

    @staticmethod
    def _run(args: list[str], cwd: Path) -> str:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise StateSyncError(f"git state sync failed at {args[1]}")
        return result.stdout.strip()

    def __call__(self, state_path: Path) -> None:
        repo_text = self._run(["git", "rev-parse", "--show-toplevel"], state_path.parent)
        repo = Path(repo_text).resolve()
        state = state_path.resolve()
        try:
            relative = state.relative_to(repo)
        except ValueError as exc:
            raise StateSyncError("state path is outside the git repository") from exc
        self._run(["git", "add", "--", str(relative)], repo)
        self._run(["git", "commit", "--only", "-m", "chore: reserve affiliate reply state [skip ci]", "--", str(relative)], repo)
        # Other bots push queue/log commits to the same branch; rebase onto them
        # instead of failing the reservation.  Only this job writes the state file.
        for attempt in range(3):
            try:
                self._run(["git", "push", "origin", f"HEAD:{self.branch}"], repo)
                return
            except StateSyncError:
                if attempt == 2:
                    raise
                self._run(["git", "pull", "--rebase", "--autostash", "origin", self.branch], repo)


def _error_code(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error", payload)
    if isinstance(error, Mapping):
        return error.get("code") or error.get("type") or error.get("title")
    return None


def _request_json(session: Any, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = session.request(method, url, timeout=30, **kwargs)
    except requests.RequestException as exc:
        raise ApiError(method, 0) from exc
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ApiError(method, response.status_code) from exc
    if not response.ok or (isinstance(payload, Mapping) and payload.get("error")):
        raise ApiError(method, response.status_code, code=_error_code(payload))
    if not isinstance(payload, dict) or not payload:
        raise ApiError(method, response.status_code, code="empty_response")
    return payload


def _pages(session: Any, url: str, *, headers: Mapping[str, str], params: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    next_url, next_params = url, dict(params)
    while next_url:
        payload = _request_json(session, "GET", next_url, headers=headers, params=next_params)
        yield payload
        paging = payload.get("paging", {})
        next_url = paging.get("next")
        next_params = {}


class FacebookApi:
    def __init__(self, config: Mapping[str, Any], session: Any | None = None):
        self.config, self.session = config, session or requests.Session()
        token = os.environ[config.get("token_env", "FACEBOOK_PAGE_ACCESS_TOKEN")]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.base = f"https://graph.facebook.com/{GRAPH_VERSION}"

    def get_identity(self) -> dict[str, Any]:
        data = _request_json(self.session, "GET", f"{self.base}/me", headers=self.headers, params={"fields": "id,name,username"})
        return {"id": str(data["id"]), "username": data.get("username") or data.get("name", ""), "aliases": self.config.get("account_alias_ids", [])}

    def iter_posts(self, since: datetime) -> Iterator[dict[str, Any]]:
        seen: set[str] = set()
        sources = ((f"{self.base}/{self.config['account_id']}/published_posts", {"fields": "id,message,created_time,is_published,status_type,attachments{target{id}}", "limit": 50}),)
        for url, params in sources:
            for page in _pages(self.session, url, headers=self.headers, params=params):
                stop = False
                for item in page.get("data", []):
                    post_id = str(item.get("id", ""))
                    if not post_id or post_id in seen:
                        continue
                    seen.add(post_id)
                    created = item.get("created_time") or item.get("scheduled_publish_time")
                    if created and parse_timestamp(created) < since:
                        stop = True
                    targets = [str((a.get("target") or {}).get("id", "")) for a in (item.get("attachments") or {}).get("data", [])]
                    yield {"id": post_id, "aliases": [t for t in targets if t], "text": item.get("message", ""), "created_at": created, "original": True, "published": item.get("is_published", True)}
                if stop:
                    break

    def iter_existing_replies(self, post_id: str) -> Iterator[dict[str, Any]]:
        url = f"{self.base}/{post_id}/comments"
        params = {"fields": "id,message,from{id,name}", "limit": 100}
        for page in _pages(self.session, url, headers=self.headers, params=params):
            for item in page.get("data", []):
                author = item.get("from") or {}
                yield {"id": item.get("id"), "author_id": str(author.get("id", "")), "author_username": author.get("name", ""), "text": item.get("message", "")}

    def publish_reply(self, post_id: str, text: str) -> str:
        result = _request_json(self.session, "POST", f"{self.base}/{post_id}/comments", headers=self.headers, data={"message": text})
        if not result.get("id"):
            raise ApiError("POST", 200, code="missing_id")
        return str(result["id"])

    def verify_reply(self, post_id: str, reply_id: str) -> bool:
        result = _request_json(self.session, "GET", f"{self.base}/{reply_id}", headers=self.headers, params={"fields": "id,message,from{id}"})
        return str(result.get("id", "")) == reply_id


class ThreadsApi:
    def __init__(self, config: Mapping[str, Any], session: Any | None = None, sleep: Callable[[float], None] = time.sleep):
        self.config, self.session, self.sleep = config, session or requests.Session(), sleep
        token = os.environ[config.get("token_env", "THREADS_ACCESS_TOKEN")]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.base = f"https://graph.threads.net/{THREADS_VERSION}"

    def get_identity(self) -> dict[str, Any]:
        data = _request_json(self.session, "GET", f"{self.base}/me", headers=self.headers, params={"fields": "id,username"})
        return {"id": str(data["id"]), "username": data.get("username", ""), "aliases": []}

    def iter_posts(self, since: datetime) -> Iterator[dict[str, Any]]:
        url = f"{self.base}/{self.config['account_id']}/threads"
        params = {"fields": "id,text,timestamp,username,is_quote_post,reposted_post,replied_to", "limit": 50}
        for page in _pages(self.session, url, headers=self.headers, params=params):
            stop = False
            for item in page.get("data", []):
                created = item.get("timestamp")
                if created and parse_timestamp(created) < since:
                    stop = True
                yield {"id": str(item["id"]), "text": item.get("text", ""), "created_at": created, "original": not bool(item.get("replied_to")), "is_reply": bool(item.get("replied_to")), "is_repost": bool(item.get("reposted_post")), "published": True}
            if stop:
                break

    def iter_existing_replies(self, post_id: str) -> Iterator[dict[str, Any]]:
        url = f"{self.base}/{post_id}/replies"
        params = {"fields": "id,text,username,timestamp", "limit": 100}
        for page in _pages(self.session, url, headers=self.headers, params=params):
            for item in page.get("data", []):
                yield {"id": item.get("id"), "author_id": "", "author_username": item.get("username", ""), "text": item.get("text", "")}

    def publish_reply(self, post_id: str, text: str) -> str:
        created = _request_json(self.session, "POST", f"{self.base}/{self.config['account_id']}/threads", headers=self.headers, data={"media_type": "TEXT", "text": text, "reply_to_id": post_id})
        container = str(created.get("id", ""))
        if not container:
            raise ApiError("POST", 200, code="missing_container_id")
        for _ in range(10):
            status = _request_json(self.session, "GET", f"{self.base}/{container}", headers=self.headers, params={"fields": "status"}).get("status")
            if status == "FINISHED":
                break
            if status in {"ERROR", "EXPIRED"}:
                raise ApiError("GET", 200, code=status)
            self.sleep(2)
        else:
            raise ApiError("GET", 408, code="container_not_ready")
        result = _request_json(self.session, "POST", f"{self.base}/{self.config['account_id']}/threads_publish", headers=self.headers, data={"creation_id": container})
        if not result.get("id"):
            raise ApiError("POST", 200, code="missing_id")
        return str(result["id"])

    def verify_reply(self, post_id: str, reply_id: str) -> bool:
        result = _request_json(self.session, "GET", f"{self.base}/{reply_id}", headers=self.headers, params={"fields": "id,replied_to"})
        parent = result.get("replied_to") or {}
        parent_id = parent.get("id") if isinstance(parent, Mapping) else parent
        return str(result.get("id", "")) == reply_id and str(parent_id or "") == post_id


class XApi:
    def __init__(self, config: Mapping[str, Any], session: Any | None = None):
        self.config = config
        if session is None:
            try:
                from requests_oauthlib import OAuth1Session
            except ImportError as exc:
                raise RuntimeError("requests-oauthlib is required for X OAuth 1.0a") from exc
            names = config.get("oauth_env", {})
            session = OAuth1Session(
                os.environ[names.get("consumer_key", "X_CONSUMER_KEY")],
                client_secret=os.environ[names.get("consumer_secret", "X_CONSUMER_SECRET")],
                resource_owner_key=os.environ[names.get("access_token", "X_ACCESS_TOKEN")],
                resource_owner_secret=os.environ[names.get("access_token_secret", "X_ACCESS_TOKEN_SECRET")],
            )
        self.session, self.base, self._replies = session, "https://api.x.com/2", {}
        self.account_id = str(config.get("account_id", ""))

    def get_identity(self) -> dict[str, Any]:
        result = _request_json(self.session, "GET", f"{self.base}/users/me", params={"user.fields": "username"})["data"]
        self.account_id = str(result["id"])
        return {"id": self.account_id, "username": result.get("username", ""), "aliases": []}

    def iter_posts(self, since: datetime) -> Iterator[dict[str, Any]]:
        token = None
        originals: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"max_results": 100, "tweet.fields": "created_at,referenced_tweets,author_id,entities", "start_time": since.isoformat().replace("+00:00", "Z")}
            if token:
                params["pagination_token"] = token
            payload = _request_json(self.session, "GET", f"{self.base}/users/{self.account_id}/tweets", params=params)
            for item in payload.get("data", []):
                refs = item.get("referenced_tweets") or []
                reply_ref = next((r for r in refs if r.get("type") == "replied_to"), None)
                if reply_ref:
                    urls = item.get("entities", {}).get("urls", [])
                    expanded = [str(url.get("expanded_url") or url.get("unwound_url") or "") for url in urls]
                    self._replies.setdefault(str(reply_ref["id"]), []).append({"id": str(item["id"]), "author_id": str(item.get("author_id", self.account_id)), "author_username": self.config.get("expected_username", ""), "text": item.get("text", ""), "platform_link": any(_is_shopee_url(url) for url in expanded)})
                elif not any(r.get("type") == "retweeted" for r in refs):
                    originals.append({"id": str(item["id"]), "text": item.get("text", ""), "created_at": item.get("created_at"), "original": True, "published": True})
            token = payload.get("meta", {}).get("next_token")
            if not token:
                break
        yield from originals

    def iter_existing_replies(self, post_id: str) -> Iterator[dict[str, Any]]:
        yield from self._replies.get(post_id, [])

    def publish_reply(self, post_id: str, text: str) -> str:
        result = _request_json(self.session, "POST", f"{self.base}/tweets", json={"text": text, "reply": {"in_reply_to_tweet_id": post_id}})
        reply_id = str(result.get("data", {}).get("id", ""))
        if not reply_id:
            raise ApiError("POST", 200, code="missing_id")
        return reply_id

    def verify_reply(self, post_id: str, reply_id: str) -> bool:
        result = _request_json(self.session, "GET", f"{self.base}/tweets/{reply_id}", params={"tweet.fields": "referenced_tweets"})
        data = result.get("data", {})
        return str(data.get("id", "")) == reply_id and any(str(ref.get("id")) == post_id and ref.get("type") == "replied_to" for ref in data.get("referenced_tweets", []))


class AffiliateReconciler:
    def __init__(self, platform: str, config: Mapping[str, Any], state: StateStore, api: Any, *, publish: bool = False, since: str | datetime | None = None, now: datetime | None = None):
        self.platform, self.config, self.state, self.api, self.publish = platform, config, state, api, publish
        rollout = parse_since(str(config["rollout_since"]))
        requested = parse_since(since) if isinstance(since, str) else since
        self.since = max(rollout, requested) if requested else rollout
        lookback = config.get("lookback_hours")
        if lookback:
            # Bound API reads (X bills per read); completed posts are in state anyway.
            window = (now or datetime.now(timezone.utc)) - timedelta(hours=float(lookback))
            self.since = max(self.since, window)

    def _identity(self) -> tuple[str, set[str], str]:
        identity = self.api.get_identity()
        actual_id, actual_username = str(identity["id"]), str(identity.get("username", ""))
        expected_id, expected_username = str(self.config["account_id"]), str(self.config.get("expected_username", ""))
        aliases = {str(value) for value in identity.get("aliases", [])} | {str(value) for value in self.config.get("account_alias_ids", [])}
        if expected_id and actual_id != expected_id and expected_id not in aliases:
            raise ValueError("authenticated account id does not match config")
        if expected_username and actual_username and expected_username.casefold() != actual_username.casefold():
            raise ValueError("authenticated username does not match config")
        return actual_id, aliases | {actual_id, expected_id}, expected_username or actual_username

    @staticmethod
    def _eligible(post: Mapping[str, Any], since: datetime) -> str | None:
        if post.get("is_reply") or not post.get("original", True):
            return "reply"
        if post.get("is_repost"):
            return "repost"
        if not post.get("published", True):
            return "unpublished"
        if not post.get("created_at") or parse_timestamp(str(post["created_at"])) < since:
            return "before_since"
        return None

    @staticmethod
    def _has_existing(replies: Iterable[Mapping[str, Any]], own_ids: set[str], username: str) -> bool:
        expected = username.casefold()
        for reply in replies:
            author_id = str(reply.get("author_id", ""))
            author_name = str(reply.get("author_username", "")).casefold()
            own = author_id in own_ids or bool(expected and author_name == expected)
            text = str(reply.get("text", ""))
            link = any(_is_shopee_url(url.rstrip(".,);]")) for url in URL_RE.findall(text))
            if own and (link or reply.get("platform_link")):
                return True
        return False

    def _verified(self, post_id: str, reply_id: str) -> bool:
        if not reply_id:
            return False
        try:
            return bool(self.api.verify_reply(post_id, reply_id))
        except ApiError:
            return False  # deleted or unreadable: fall back to scanning real replies

    def run(self) -> dict[str, Any]:
        account, own_ids, username = self._identity()
        counts: Counter[str] = Counter()
        skipped: Counter[str] = Counter()
        held: list[str] = []
        planned: list[dict[str, str]] = []
        for post in self.api.iter_posts(self.since):
            counts["scanned"] += 1
            reason = self._eligible(post, self.since)
            if reason:
                skipped[reason] += 1
                continue
            post_id = str(post["id"])
            prior = self.state.get(self.platform, account, post_id)
            if prior:
                status = str(prior.get("status", "unknown"))
                if status in {"published", "existing"}:
                    skipped["state_" + status] += 1
                    continue
                if status != "failed":
                    # A write may have reached the platform: never publish again automatically.
                    reply_id = str(prior.get("reply_id", ""))
                    if self._verified(post_id, reply_id):
                        if self.publish:
                            self.state.set(self.platform, account, post_id, "published", reply_id=reply_id, recovered=True)
                        counts["recovered"] += 1
                        continue
                    if self._has_existing(self.api.iter_existing_replies(post_id), own_ids, username):
                        if self.publish:
                            self.state.set(self.platform, account, post_id, "existing", recovered=True)
                        counts["recovered"] += 1
                        continue
                    counts["held"] += 1
                    held.append(post_id)
                    continue  # keep serving newer posts; alert at the end
                # "failed" means the platform refused the write, so a retry is safe.
            counts["eligible"] += 1
            if self._has_existing(self.api.iter_existing_replies(post_id), own_ids, username):
                counts["existing"] += 1
                if self.publish:
                    self.state.set(self.platform, account, post_id, "existing")
                continue
            selection = select_product(post, self.config)
            if not self.publish:
                counts["dry_run"] += 1
                planned.append({"post_id": post_id, "selection": selection.reason, "product": selection.product["name"]})
                continue
            self.state.set(self.platform, account, post_id, "publishing", selection=selection.reason)
            reply_id = ""
            try:
                reply_id = self.api.publish_reply(post_id, build_comment(selection))
                self.state.set(self.platform, account, post_id, "publishing", reply_id=reply_id, selection=selection.reason)
                if not reply_id or not self.api.verify_reply(post_id, reply_id):
                    raise ApiError("GET", 200, code="verification_failed")
            except Exception as exc:
                fields = {"selection": selection.reason}
                if reply_id:
                    fields["reply_id"] = reply_id
                rejected = isinstance(exc, ApiError) and exc.rejected and not reply_id
                self.state.set(self.platform, account, post_id, "failed" if rejected else "unknown", **fields)
                raise
            self.state.set(self.platform, account, post_id, "published", reply_id=reply_id, selection=selection.reason)
            counts["published"] += 1
        result: dict[str, Any] = {**counts, "skipped": dict(skipped)}
        if planned:
            result["planned"] = planned
        if held:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            raise ReconciliationRequired(f"{len(held)} post(s) have ambiguous prior state and need manual reconciliation: {', '.join(held)}")
        return result


def load_platform_config(path: os.PathLike[str] | str, platform: str) -> dict[str, Any]:
    config_path = Path(path)
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    config = loaded.get(platform)
    if not isinstance(config, dict):
        raise ValueError(f"config has no {platform!r} object")
    for field in ("account_id", "rollout_since", "approved_fallback"):
        if field not in config:
            raise ValueError(f"missing config field: {field}")
    parse_since(str(config["rollout_since"]))
    validate_product(config["approved_fallback"])
    registry_name = config.get("post_products_file")
    if registry_name:
        registry_path = Path(registry_name)
        if not registry_path.is_absolute():
            registry_path = config_path.parent / registry_path
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        external = registry.get(platform, {})
        if not isinstance(external, dict):
            raise ValueError("post product registry platform entry must be an object")
        config["post_products"] = {**external, **config.get("post_products", {})}
    return config


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").casefold() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=("facebook", "threads", "x"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--since", help="timezone-aware ISO cutoff; defaults to config rollout_since")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read-only preview (default)")
    mode.add_argument("--publish", action="store_true", help="publish and persist replies")
    parser.add_argument("--git-state", action="store_true", help="push each state transition before continuing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_platform_config(args.config, args.platform)
        sync = GitStateSync() if args.git_state or _env_flag("AFFILIATE_GIT_STATE") else None
        state = StateStore(args.state, sync=sync)
        api_class = {"facebook": FacebookApi, "threads": ThreadsApi, "x": XApi}[args.platform]
        result = AffiliateReconciler(args.platform, config, state, api_class(config), publish=args.publish, since=args.since).run()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ApiError, StateSyncError, ReconciliationRequired, ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"auto-affiliate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
