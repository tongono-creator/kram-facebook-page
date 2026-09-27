import json
from datetime import datetime, timezone

import pytest

import auto_affiliate as aa


DISCLOSURE = "ลิงก์ Affiliate — เพจอาจได้รับค่าคอมมิชชันจากการซื้อผ่านลิงก์นี้"


def config():
    return {
        "account_id": "acct-1",
        "expected_username": "rocket21",
        "rollout_since": "2026-09-20T00:00:00Z",
        "approved_fallback": {
            "name": "ของใช้ประจำวันคัดโดย Rocket21",
            "url": "https://s.shopee.co.th/fallback",
        },
        "post_products": {
            "exact": {"name": "แก้วเก็บความเย็น", "url": "https://shopee.co.th/exact"}
        },
        "catalog": [
            {
                "name": "อาหารแมว",
                "url": "https://shopee.co.th/cat",
                "keywords": ["อาหารแมว", "แมว"],
                "exclude_keywords": ["สุนัข"],
            },
            {
                "name": "หม้อทอดไร้น้ำมัน",
                "url": "https://shopee.co.th/fryer",
                "keywords": ["หม้อทอดไร้น้ำมัน"],
            },
        ],
    }


class FakeApi:
    def __init__(self, posts=(), existing=None, fail=None):
        self.posts = list(posts)
        self.existing = existing or {}
        self.fail = fail
        self.published = []

    def get_identity(self):
        return {"id": "acct-1", "username": "rocket21", "aliases": ["profile-1"]}

    def iter_posts(self, since):
        yield from self.posts

    def iter_existing_replies(self, post_id):
        yield from self.existing.get(post_id, [])

    def publish_reply(self, post_id, text):
        self.published.append((post_id, text))
        if self.fail == "publish":
            raise aa.ApiError("POST", 504, "timeout")
        return "reply-1"

    def verify_reply(self, post_id, reply_id):
        if self.fail == "verify":
            raise aa.ApiError("GET", 503, "unavailable")
        return self.fail != "missing"


def post(post_id="p1", text="เรื่องทั่วไป", created="2026-09-21T01:00:00Z", **extra):
    return {"id": post_id, "text": text, "created_at": created, "original": True, "published": True, **extra}


def runner(tmp_path, api, *, publish=True, platform="facebook", sync=None):
    state = aa.StateStore(tmp_path / "state.json", sync=sync)
    return aa.AffiliateReconciler(platform, config(), state, api, publish=publish)


def test_exact_then_keyword_then_transparent_fallback_selection():
    cfg = config()
    exact = aa.select_product(post("exact", "ไม่เกี่ยวกับชื่อสินค้า"), cfg)
    matched = aa.select_product(post("p2", "รีวิวหม้อทอดไร้น้ำมัน"), cfg)
    fallback = aa.select_product(post("p3", "ข่าวทั่วไป"), cfg)

    assert (exact.product["name"], exact.reason) == ("แก้วเก็บความเย็น", "explicit")
    assert (matched.product["name"], matched.reason) == ("หม้อทอดไร้น้ำมัน", "keyword")
    assert fallback.reason == "fallback"
    assert aa.build_comment(fallback).startswith("พิกัดสินค้าสำหรับผู้ติดตาม")
    assert DISCLOSURE in aa.build_comment(fallback)
    assert "สินค้าชิ้นนี้" not in aa.build_comment(fallback)


@pytest.mark.parametrize(
    "url",
    ["http://shopee.co.th/x", "https://evil.example/x", "https://shopee.co.th.evil.example/x", "not a url"],
)
def test_malformed_or_non_shopee_link_is_rejected(url):
    with pytest.raises(ValueError, match="Shopee HTTPS"):
        aa.validate_product({"name": "x", "url": url})


def test_existing_own_affiliate_reply_prevents_duplicate(tmp_path):
    api = FakeApi(
        [post()],
        {"p1": [{"id": "c1", "author_id": "profile-1", "author_username": "rocket21", "text": "ซื้อ https://shopee.co.th/a"}]},
    )
    result = runner(tmp_path, api).run()

    assert result["existing"] == 1
    assert api.published == []
    assert json.loads((tmp_path / "state.json").read_text("utf-8"))["facebook"]["acct-1"]["p1"]["status"] == "existing"


def test_existing_other_users_link_does_not_block_publish(tmp_path):
    api = FakeApi([post()], {"p1": [{"author_id": "stranger", "text": "https://shopee.co.th/a"}]})
    result = runner(tmp_path, api).run()
    assert result["published"] == 1
    assert len(api.published) == 1


@pytest.mark.parametrize("reserved", ["published", "existing"])
def test_completed_states_are_never_retried(tmp_path, reserved):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"facebook": {"acct-1": {"p1": {"status": reserved}}}}), "utf-8")
    api = FakeApi([post()])
    result = runner(tmp_path, api).run()
    assert result["skipped"]["state_" + reserved] == 1
    assert api.published == []


@pytest.mark.parametrize("reserved", ["publishing", "unknown"])
def test_ambiguous_reservation_blocks_with_nonzero_alert(tmp_path, reserved):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"facebook": {"acct-1": {"p1": {"status": reserved}}}}), "utf-8")
    api = FakeApi([post()])
    with pytest.raises(aa.ReconciliationRequired):
        runner(tmp_path, api).run()
    assert api.published == []


def test_partial_publish_failure_leaves_unknown_reservation(tmp_path):
    api = FakeApi([post()], fail="publish")
    with pytest.raises(aa.ApiError):
        runner(tmp_path, api).run()
    saved = json.loads((tmp_path / "state.json").read_text("utf-8"))
    assert saved["facebook"]["acct-1"]["p1"]["status"] == "unknown"


def test_verification_failure_is_not_treated_as_success(tmp_path):
    api = FakeApi([post()], fail="missing")
    with pytest.raises(aa.ApiError, match="verification"):
        runner(tmp_path, api).run()
    saved = json.loads((tmp_path / "state.json").read_text("utf-8"))
    assert saved["facebook"]["acct-1"]["p1"]["status"] == "unknown"
    assert saved["facebook"]["acct-1"]["p1"]["reply_id"] == "reply-1"


def test_partial_reply_id_is_verified_and_recovered_without_reposting(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"facebook": {"acct-1": {"p1": {"status": "unknown", "reply_id": "reply-1"}}}}), "utf-8")
    api = FakeApi([post()])
    result = runner(tmp_path, api).run()
    assert result["recovered"] == 1
    assert api.published == []
    assert json.loads(state_file.read_text("utf-8"))["facebook"]["acct-1"]["p1"]["status"] == "published"


def test_reservation_is_synced_before_external_write_and_sync_failure_aborts(tmp_path):
    calls = []
    api = FakeApi([post()])

    def sync(path):
        calls.append(json.loads(path.read_text("utf-8"))["facebook"]["acct-1"]["p1"]["status"])
        if len(calls) == 1:
            raise aa.StateSyncError("push failed")

    with pytest.raises(aa.StateSyncError):
        runner(tmp_path, api, sync=sync).run()
    assert calls == ["publishing"]
    assert api.published == []


def test_dry_run_is_read_only(tmp_path):
    api = FakeApi([post()])
    result = runner(tmp_path, api, publish=False).run()
    assert result["dry_run"] == 1
    assert not (tmp_path / "state.json").exists()
    assert api.published == []


def test_own_reply_repost_unpublished_and_before_since_are_excluded(tmp_path):
    api = FakeApi(
        [
            post("reply", is_reply=True),
            post("repost", is_repost=True),
            post("draft", published=False),
            post("old", created="2026-09-19T23:59:59Z"),
            post("new"),
        ]
    )
    result = runner(tmp_path, api, publish=False, platform="threads").run()
    assert result["dry_run"] == 1
    assert result["skipped"] == {"reply": 1, "repost": 1, "unpublished": 1, "before_since": 1}


def test_ambiguous_keyword_match_uses_safe_fallback():
    cfg = config()
    cfg["catalog"] = [
        {"name": "แมว A", "url": "https://shopee.co.th/a", "keywords": ["แมว"]},
        {"name": "แมว B", "url": "https://shopee.co.th/b", "keywords": ["แมว"]},
    ]
    assert aa.select_product(post(text="เรื่องแมว"), cfg).reason == "fallback"


def test_parse_since_requires_timezone():
    assert aa.parse_since("2026-09-20T00:00:00Z") == datetime(2026, 9, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone"):
        aa.parse_since("2026-09-20T00:00:00")


def test_api_error_redacts_body_and_tokens():
    error = aa.ApiError("POST", 401, "secret-token", code="OAuthException")
    assert str(error) == "POST failed (HTTP 401, code OAuthException)"
    assert "secret" not in repr(error)


def test_tco_without_expanded_shopee_url_is_not_an_affiliate_reply():
    reply = {"author_id": "acct-1", "text": "อ่านต่อ https://t.co/abc", "platform_link": False}
    assert not aa.AffiliateReconciler._has_existing([reply], {"acct-1"}, "rocket21")


def test_cli_since_cannot_move_before_rollout(tmp_path):
    reconciler = aa.AffiliateReconciler(
        "facebook", config(), aa.StateStore(tmp_path / "s.json"), FakeApi(),
        since="2020-01-01T00:00:00Z",
    )
    assert reconciler.since == aa.parse_since(config()["rollout_since"])


def test_scheduled_photo_id_and_page_prefix_still_match_mapping():
    cfg = config()
    cfg["post_products"] = {
        "photo-9": {"name": "จากรูปตั้งเวลา", "url": "https://shopee.co.th/photo"},
        "other-page_777": {"name": "จาก prefix อื่น", "url": "https://shopee.co.th/prefix"},
    }
    by_photo = aa.select_product(post("page_555", aliases=["photo-9"]), cfg)
    by_suffix = aa.select_product(post("acct-1_777"), cfg)
    assert (by_photo.product["name"], by_photo.reason) == ("จากรูปตั้งเวลา", "explicit")
    assert (by_suffix.product["name"], by_suffix.reason) == ("จาก prefix อื่น", "explicit")


def _seed(tmp_path, records):
    (tmp_path / "state.json").write_text(json.dumps({"facebook": {"acct-1": records}}), "utf-8")


def _saved(tmp_path):
    return json.loads((tmp_path / "state.json").read_text("utf-8"))["facebook"]["acct-1"]


def test_ambiguous_post_does_not_block_newer_posts(tmp_path):
    _seed(tmp_path, {"old": {"status": "unknown"}})
    api = FakeApi([post("old"), post("new")])
    with pytest.raises(aa.ReconciliationRequired, match="old"):
        runner(tmp_path, api).run()
    assert [p for p, _ in api.published] == ["new"]
    assert _saved(tmp_path)["new"]["status"] == "published"
    assert _saved(tmp_path)["old"]["status"] == "unknown"


def test_ambiguous_state_resolved_by_real_reply_is_not_an_alert(tmp_path):
    _seed(tmp_path, {"p1": {"status": "publishing"}})
    mine = {"p1": [{"author_id": "acct-1", "text": "พิกัด https://s.shopee.co.th/x"}]}
    api = FakeApi([post()], mine)
    assert runner(tmp_path, api).run()["recovered"] == 1
    assert api.published == []
    assert _saved(tmp_path)["p1"]["status"] == "existing"


def test_success_then_state_write_failure_never_duplicates_on_rerun(tmp_path):
    api = FakeApi([post()])
    writes = []

    def sync(path):
        writes.append(json.loads(path.read_text("utf-8"))["facebook"]["acct-1"]["p1"]["status"])
        if len(writes) >= 2:  # reservation pushed, everything after it fails
            raise aa.StateSyncError("push failed")

    with pytest.raises(aa.StateSyncError):
        runner(tmp_path, api, sync=sync).run()
    assert len(api.published) == 1
    # Fresh checkout only has the pushed reservation; the live reply is visible.
    _seed(tmp_path, {"p1": {"status": "publishing"}})
    api.existing = {"p1": [{"author_id": "acct-1", "text": api.published[0][1]}]}
    assert runner(tmp_path, api).run()["recovered"] == 1
    assert len(api.published) == 1


def test_timeout_is_held_and_rerun_does_not_publish(tmp_path):
    class Timeout(FakeApi):
        def publish_reply(self, post_id, text):
            self.published.append((post_id, text))
            raise aa.ApiError("POST", 0)

    api = Timeout([post()])
    with pytest.raises(aa.ApiError):
        runner(tmp_path, api).run()
    assert _saved(tmp_path)["p1"]["status"] == "unknown"
    with pytest.raises(aa.ReconciliationRequired):
        runner(tmp_path, api).run()
    assert len(api.published) == 1


def test_rejected_token_is_retried_after_fix_without_duplicate(tmp_path):
    class BadToken(FakeApi):
        def publish_reply(self, post_id, text):
            self.published.append((post_id, text))
            raise aa.ApiError("POST", 400, code=190)

    with pytest.raises(aa.ApiError):
        runner(tmp_path, BadToken([post()])).run()
    assert _saved(tmp_path)["p1"]["status"] == "failed"
    fixed = FakeApi([post()])
    assert runner(tmp_path, fixed).run()["published"] == 1
    assert runner(tmp_path, fixed).run()["skipped"] == {"state_published": 1}
    assert len(fixed.published) == 1


def test_identity_failure_writes_nothing(tmp_path):
    class Expired(FakeApi):
        def get_identity(self):
            raise aa.ApiError("GET", 400, code=190)

    api = Expired([post()])
    with pytest.raises(aa.ApiError):
        runner(tmp_path, api).run()
    assert api.published == []
    assert not (tmp_path / "state.json").exists()


def test_deleted_prior_reply_falls_back_to_reply_scan(tmp_path):
    _seed(tmp_path, {"p1": {"status": "unknown", "reply_id": "gone"}})
    api = FakeApi([post()], fail="verify")
    with pytest.raises(aa.ReconciliationRequired):
        runner(tmp_path, api).run()
    assert api.published == []


def test_lookback_limits_scan_window(tmp_path):
    cfg = config()
    cfg["lookback_hours"] = 48
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    r = aa.AffiliateReconciler("facebook", cfg, aa.StateStore(tmp_path / "s.json"), FakeApi(), now=now)
    assert r.since == datetime(2026, 9, 25, tzinfo=timezone.utc)


def test_dry_run_reports_planned_product(tmp_path):
    result = runner(tmp_path, FakeApi([post("exact")]), publish=False).run()
    assert result["planned"] == [{"post_id": "exact", "selection": "explicit", "product": "แก้วเก็บความเย็น"}]


def test_git_sync_rebases_when_branch_moved(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, cwd):
        calls.append(args[1])
        if args[1] == "rev-parse":
            return str(tmp_path)
        if args[1] == "push" and calls.count("push") == 1:
            raise aa.StateSyncError("git state sync failed at push")
        return ""

    monkeypatch.setattr(aa.GitStateSync, "_run", staticmethod(fake_run))
    aa.GitStateSync("main")(tmp_path / "state.json")
    assert calls == ["rev-parse", "add", "commit", "push", "pull", "push"]


def test_remember_product_never_raises_or_overwrites_corrupt_registry(tmp_path, monkeypatch):
    import affiliate_post_products as app

    registry = tmp_path / "affiliate_post_products.json"
    monkeypatch.setattr(app, "STATE_FILE", registry)
    registry.write_text("{broken", "utf-8")
    assert app.remember_product("facebook", "1_2", "https://s.shopee.co.th/a") is False
    assert registry.read_text("utf-8") == "{broken"
    registry.unlink()
    assert app.remember_product("x", "9", "https://shope.ee/a", "ชื่อ") is True
    assert app.remember_product("x", "10", "https://shopee.ee/a") is False
    assert json.loads(registry.read_text("utf-8")) == {"x": {"9": {"name": "ชื่อ", "url": "https://shope.ee/a"}}}


def test_external_post_product_registry_is_merged(tmp_path):
    registry = tmp_path / "affiliate_post_products.json"
    registry.write_text(json.dumps({"facebook": {"external": {"name": "ของตรงโพสต์", "url": "https://shopee.co.th/ext"}}}), "utf-8")
    cfg_file = tmp_path / "config.json"
    raw = config()
    raw["post_products_file"] = registry.name
    cfg_file.write_text(json.dumps({"facebook": raw}), "utf-8")
    loaded = aa.load_platform_config(cfg_file, "facebook")
    assert aa.select_product(post("external"), loaded).product["name"] == "ของตรงโพสต์"
