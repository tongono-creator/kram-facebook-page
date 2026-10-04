"""Regression tests for the editorial gate; all publication APIs stay unused.

Run from the studio directory with:
    python -m unittest discover -s tests -v

Fixtures are synthetic local packages, not an assertion of live source checks.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import (  # noqa: E402
    GateError,
    approve_package,
    build_plan,
    digest_package,
    validate_package,
    verify_approval,
)


NOW = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)
BANGKOK = timezone(timedelta(hours=7))
CHECKS = {
    "full_image_seen": True,
    "mobile_seen": True,
    "thai_readable": True,
    "subject_correct": True,
    "source_checked": True,
    "affiliate_checked": True,
}


def png(width=1080, height=1350):
    """Make a valid RGB PNG fixture without installing image libraries."""
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = (b"\x00" + b"\xff\xff\xff" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class EditorialGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="studio-gate-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.channel = {
            "channel_key": "kram_fb",
            "platform": "facebook",
            "page_id": "116701184708556",
            "timezone": "Asia/Bangkok",
            "allowed_categories": ["home", "organization", "tools"],
        }
        self.package = self.make_package("first")

    def read(self, package, filename):
        return json.loads((package / filename).read_text(encoding="utf-8"))

    def write(self, package, filename, value):
        (package / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def patch(self, filename, **changes):
        value = self.read(self.package, filename)
        value.update(changes)
        self.write(self.package, filename, value)

    def make_package(self, name, *, slot=None, product_id="storage-test-01"):
        package = self.root / name
        package.mkdir()
        manifest = {
            "id": f"test-{name}",
            "channel_key": "kram_fb",
            "page_id": "116701184708556",
            "scheduled_at": (
                slot or NOW.astimezone(BANGKOK) + timedelta(hours=3)
            ).isoformat(),
            "visual_type": "ai_editorial",
            "product_id": product_id,
            "status": "draft",
        }
        disclosure = "ลิงก์ Affiliate — เพจอาจได้รับค่าคอมมิชชันจากการซื้อผ่านลิงก์นี้"
        product_url = (
            "https://s.shopee.co.th/1gGwo5adCO"
            if product_id == "storage-test-01"
            else "https://s.shopee.co.th/9030hGnxIf"
        )
        product = {
            "product_id": product_id,
            "name": "กล่องจัดระเบียบตัวอย่างสำหรับทดสอบ",
            "url": product_url,
            "category": "home",
            "verified_at": "2026-10-03T14:00:00+07:00",
            "disclosure": disclosure,
            "comment": (
                "มุมจัดระเบียบบ้าน ก่อนซื้อเช็กขนาดกล่องให้เข้ากับชั้นวางครับ\n"
                + disclosure + "\n" + product_url
            ),
            "eligible_channels": ["kram_fb"],
        }
        evidence = {
            "entries": [{
                "url": "https://www.miele.com/en/com/index.htm",
                "claim": "เก็บชื่อผู้เผยแพร่และแหล่งข้อมูลต้นทางไว้ตรวจย้อนกลับ",
                "checked_at": "2026-10-03T14:00:00+07:00",
            }]
        }
        self.write(package, "manifest.json", manifest)
        self.write(package, "affiliate.json", product)
        self.write(package, "evidence.json", evidence)
        (package / "caption.txt").write_text(
            "เก็บของให้หาเจอ เริ่มจากแบ่งตามงานที่ต้องใช้\n"
            "ภาพประกอบสร้างด้วย AI ไม่ใช่ภาพเหตุการณ์จริง\n#กรามค้าง",
            encoding="utf-8",
        )
        (package / "card.png").write_bytes(png())
        return package

    def approve(self, package=None):
        return approve_package(
            package or self.package,
            reviewer="root-editor",
            notes="ตรวจภาพเต็มและมือถือ พร้อมเทียบหลักฐานและสินค้าแล้ว",
            checks=dict(CHECKS),
        )

    def assert_gate_rejects(self):
        with self.assertRaises(GateError):
            validate_package(self.package, self.channel, now=NOW)

    def test_valid_package_is_returned_with_identity_intact(self):
        result = validate_package(self.package, self.channel, now=NOW)
        self.assertEqual(result["id"], "test-first")
        self.assertEqual(result["page_id"], self.channel["page_id"])

    def test_required_files_cannot_disappear(self):
        for filename in (
            "manifest.json", "caption.txt", "card.png", "affiliate.json", "evidence.json"
        ):
            with self.subTest(filename=filename):
                package = self.make_package("missing-" + filename.replace(".", "-"))
                (package / filename).unlink()
                with self.assertRaises(GateError):
                    validate_package(package, self.channel, now=NOW)

    def test_wrong_page_cannot_use_another_pages_config(self):
        self.patch("manifest.json", page_id="102319399434080")
        self.assert_gate_rejects()

    def test_wrong_channel_cannot_use_another_pages_config(self):
        self.patch("manifest.json", channel_key="chowchow_fb")
        self.assert_gate_rejects()

    def test_naive_schedule_timestamp_is_rejected(self):
        self.patch("manifest.json", scheduled_at="2026-10-04T10:00:00")
        self.assert_gate_rejects()

    def test_schedule_with_under_fifteen_minutes_lead_is_rejected(self):
        slot = NOW.astimezone(BANGKOK) + timedelta(minutes=14, seconds=59)
        self.patch("manifest.json", scheduled_at=slot.isoformat())
        self.assert_gate_rejects()

    def test_schedule_beyond_seventy_five_days_is_rejected(self):
        slot = NOW.astimezone(BANGKOK) + timedelta(days=75, seconds=1)
        self.patch("manifest.json", scheduled_at=slot.isoformat())
        self.assert_gate_rejects()

    def test_expired_scheduled_package_is_not_released(self):
        self.approve()
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW + timedelta(days=1))

    def test_real_png_with_wrong_dimensions_is_rejected(self):
        (self.package / "card.png").write_bytes(png(1080, 1080))
        self.assert_gate_rejects()

    def test_non_image_named_png_is_rejected(self):
        (self.package / "card.png").write_bytes(b"not an image")
        self.assert_gate_rejects()

    def test_product_identity_must_match_manifest(self):
        self.patch("affiliate.json", product_id="different-product")
        self.assert_gate_rejects()

    def test_product_requires_this_channel_in_eligible_channels(self):
        self.patch("affiliate.json", eligible_channels=["rocket_fb"])
        self.assert_gate_rejects()

    def test_shopee_lookalike_hostname_is_rejected(self):
        affiliate = self.read(self.package, "affiliate.json")
        original = affiliate["url"]
        malicious = "https://s.shopee.co.th.attacker.example/offer"
        affiliate["url"] = malicious
        affiliate["comment"] = affiliate["comment"].replace(original, malicious)
        self.write(self.package, "affiliate.json", affiliate)
        self.assert_gate_rejects()

    def test_non_shopee_url_is_rejected(self):
        self.patch("affiliate.json", url="https://www.facebook.com/product")
        self.assert_gate_rejects()

    def test_comment_cannot_add_second_sales_link(self):
        affiliate = self.read(self.package, "affiliate.json")
        affiliate["comment"] += "\nhttps://s.shopee.co.th/9030hGnxIf"
        self.write(self.package, "affiliate.json", affiliate)
        self.assert_gate_rejects()

    def test_disclosure_field_does_not_replace_visible_disclosure(self):
        affiliate = self.read(self.package, "affiliate.json")
        affiliate["comment"] = "พิกัดสินค้า\n" + affiliate["url"]
        self.write(self.package, "affiliate.json", affiliate)
        self.assert_gate_rejects()

    def test_link_in_comment_must_be_the_approved_product_link(self):
        affiliate = self.read(self.package, "affiliate.json")
        affiliate["comment"] = affiliate["comment"].replace(
            affiliate["url"], "https://s.shopee.co.th/9030hGnxIf"
        )
        self.write(self.package, "affiliate.json", affiliate)
        self.assert_gate_rejects()

    def test_chowchow_cannot_sell_cat_product_even_if_allowlist_is_wrong(self):
        chow_channel = {
            **self.channel,
            "channel_key": "chowchow_fb",
            "page_id": "102319399434080",
            "allowed_categories": ["dog", "cat", "pet"],
        }
        self.patch(
            "manifest.json", channel_key="chowchow_fb", page_id=chow_channel["page_id"]
        )
        self.patch(
            "affiliate.json", name="อาหารแมว", category="cat",
            eligible_channels=["chowchow_fb"]
        )
        with self.assertRaises(GateError):
            validate_package(self.package, chow_channel, now=NOW)

    def test_empty_evidence_does_not_count_as_checked_source(self):
        self.write(self.package, "evidence.json", {"entries": []})
        self.assert_gate_rejects()

    def test_blank_evidence_claim_is_rejected(self):
        evidence = self.read(self.package, "evidence.json")
        evidence["entries"][0]["claim"] = ""
        self.write(self.package, "evidence.json", evidence)
        self.assert_gate_rejects()

    def test_placeholder_source_url_does_not_count_as_evidence(self):
        evidence = self.read(self.package, "evidence.json")
        evidence["entries"][0]["url"] = "https://example.com/replace-with-real-source"
        self.write(self.package, "evidence.json", evidence)
        self.assert_gate_rejects()

    def test_no_review_means_no_release(self):
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW)

    def test_producer_cannot_approve_its_own_work(self):
        with self.assertRaises(GateError):
            approve_package(
                self.package, reviewer="content-producer", notes="self review", checks=CHECKS
            )

    def test_each_actual_visual_review_check_is_required(self):
        for name in CHECKS:
            with self.subTest(check=name):
                checks = {**CHECKS, name: False}
                with self.assertRaises(GateError):
                    approve_package(
                        self.package, reviewer="root-editor", notes="unchecked", checks=checks
                    )

    def test_missing_checklist_is_not_an_approval(self):
        with self.assertRaises(GateError):
            approve_package(self.package, reviewer="root-editor", notes="missing", checks={})

    def test_truthy_text_is_not_a_visual_review_boolean(self):
        checks = {**CHECKS, "full_image_seen": "true"}
        with self.assertRaises(GateError):
            approve_package(
                self.package, reviewer="root-editor", notes="invalid flag", checks=checks
            )

    def test_approved_complete_package_can_be_verified(self):
        self.approve()
        self.assertTrue((self.package / "review.json").is_file())
        result = verify_approval(self.package, self.channel, now=NOW)
        self.assertEqual(result["id"], "test-first")

    def test_digest_covers_every_reviewed_file(self):
        for filename in (
            "manifest.json", "caption.txt", "card.png", "affiliate.json", "evidence.json"
        ):
            with self.subTest(filename=filename):
                package = self.make_package("digest-" + filename.replace(".", "-"))
                before = digest_package(package)
                with (package / filename).open("ab") as stream:
                    stream.write(b"\n")
                self.assertNotEqual(before, digest_package(package))

    def test_caption_changed_after_review_cannot_be_scheduled(self):
        self.approve()
        with (self.package / "caption.txt").open("a", encoding="utf-8") as stream:
            stream.write("\nเพิ่มข้อความหลังตรวจ")
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW)

    def test_image_changed_after_review_cannot_be_scheduled(self):
        self.approve()
        # Re-encode a valid image with a harmless extra comment: same dimensions,
        # different bytes, hence a new image requiring editorial inspection.
        original = (self.package / "card.png").read_bytes()
        extra = b"Comment\x00new render"
        text_chunk = (
            struct.pack(">I", len(extra)) + b"tEXt" + extra
            + struct.pack(">I", zlib.crc32(b"tEXt" + extra) & 0xFFFFFFFF)
        )
        (self.package / "card.png").write_bytes(original[:-12] + text_chunk + original[-12:])
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW)

    def test_affiliate_changed_after_review_cannot_be_scheduled(self):
        self.approve()
        affiliate = self.read(self.package, "affiliate.json")
        affiliate["name"] += " เปลี่ยนรุ่น"
        self.write(self.package, "affiliate.json", affiliate)
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW)

    def test_evidence_changed_after_review_cannot_be_scheduled(self):
        self.approve()
        evidence = self.read(self.package, "evidence.json")
        evidence["entries"][0]["claim"] = "แก้ข้อเท็จจริงหลังตรวจ"
        self.write(self.package, "evidence.json", evidence)
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW)

    def test_slot_changed_after_review_cannot_be_scheduled(self):
        self.approve()
        self.patch("manifest.json", scheduled_at="2026-10-05T10:00:00+07:00")
        with self.assertRaises(GateError):
            verify_approval(self.package, self.channel, now=NOW)

    def test_different_slots_can_form_a_plan(self):
        second = self.make_package(
            "second", slot=NOW.astimezone(BANGKOK) + timedelta(hours=4),
            product_id="storage-test-02",
        )
        self.approve()
        self.approve(second)
        plan = build_plan(
            [self.package, second], {"kram_fb": self.channel}, now=NOW
        )
        self.assertEqual(len(plan), 2)

    def test_same_product_within_seven_days_is_blocked(self):
        second = self.make_package(
            "cooldown", slot=NOW.astimezone(BANGKOK) + timedelta(days=6, hours=3)
        )
        self.approve()
        self.approve(second)
        with self.assertRaises(GateError):
            build_plan([self.package, second], {"kram_fb": self.channel}, now=NOW)

    def test_same_product_at_seven_days_can_be_planned(self):
        second = self.make_package(
            "cooldown-over", slot=NOW.astimezone(BANGKOK) + timedelta(days=7, hours=3)
        )
        self.approve()
        self.approve(second)
        plan = build_plan([self.package, second], {"kram_fb": self.channel}, now=NOW)
        self.assertEqual(len(plan), 2)

    def test_same_page_same_slot_is_a_conflict(self):
        second = self.make_package("same-slot")
        self.approve()
        self.approve(second)
        with self.assertRaises(GateError):
            build_plan([self.package, second], {"kram_fb": self.channel}, now=NOW)

    def test_same_package_repeated_in_plan_is_a_conflict(self):
        self.approve()
        with self.assertRaises(GateError):
            build_plan([self.package, self.package], {"kram_fb": self.channel}, now=NOW)

    def test_unreviewed_package_cannot_hide_inside_an_approved_batch(self):
        second = self.make_package(
            "not-approved", slot=NOW.astimezone(BANGKOK) + timedelta(hours=4)
        )
        self.approve()
        with self.assertRaises(GateError):
            build_plan([self.package, second], {"kram_fb": self.channel}, now=NOW)

    def test_duplicate_remote_post_id_is_a_conflict_even_with_different_slots(self):
        second = self.make_package(
            "duplicate-remote", slot=NOW.astimezone(BANGKOK) + timedelta(hours=4)
        )
        post_id = "116701184708556_123456789"
        self.patch("manifest.json", post_id=post_id)
        second_manifest = self.read(second, "manifest.json")
        second_manifest["post_id"] = post_id
        self.write(second, "manifest.json", second_manifest)
        self.approve()
        self.approve(second)
        with self.assertRaises(GateError):
            build_plan([self.package, second], {"kram_fb": self.channel}, now=NOW)


if __name__ == "__main__":
    unittest.main()
