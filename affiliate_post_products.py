"""Remember the product attached to a post for the central reconciler.

Called right after a post is published or scheduled, so it must never raise:
a failure here would abort the bot before it records the queue row as done.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

STATE_FILE = Path(__file__).with_name("affiliate_post_products.json")
DEFAULT_NAME = "สินค้าที่แนะนำในโพสต์"
SHOPEE_HOSTS = ("shopee.co.th", "shopee.com", "shope.ee")


def _is_shopee_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in SHOPEE_HOSTS)


def remember_product(platform, post_id, shopee, name=DEFAULT_NAME):
    post_key = str(post_id or "").strip()
    url = str(shopee or "").strip()
    if platform not in {"facebook", "threads", "x"} or post_key.lower() in {"", "none", "null", "mock_tweet_id"}:
        return False
    if not _is_shopee_url(url):
        return False
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
        if not isinstance(data, dict):
            raise ValueError("registry root must be an object")
        data.setdefault(str(platform), {})[post_key] = {"name": str(name or "").strip() or DEFAULT_NAME, "url": url}
        fd, temp = tempfile.mkstemp(prefix=STATE_FILE.name + ".", dir=STATE_FILE.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp, STATE_FILE)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    except (OSError, ValueError) as exc:
        # Keep the existing registry untouched; the reconciler falls back to keywords.
        print(f"[affiliate] product registry not updated: {type(exc).__name__}")
        return False
    return True
