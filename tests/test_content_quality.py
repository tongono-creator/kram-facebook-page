"""Content rules: bad patterns seen in live posts must fail, good posts must pass."""
import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")

import content_quality as cq

LIVE_BAD_STORIES = [
    "ผมไปไถ Reddit เจอเรื่องสารภาพบาปสุดเดือดของหนุ่มวัย 27 ปีคนหนึ่ง ที่ทนเห็นกงสีบ้านแฟนกดขี่คนไม่ไหว",
    "มีทาสหมาคนหนึ่ง เลื่อนเจอยาหยอดเห็บโนเนม ปรากฏว่าน้องหมาน้ำลายฟูมปาก ชักเกร็ง เกือบได้ไปคุยกับรากมะม่วง",
    "หัวจะปวดมากค่ะ! กระทะเคลือบร่อน ลูกค้ากินเข้าไปจนอาเจียน ท้องร่วงหนัก",
]
LIVE_BAD_REVIEWS = [
    "กำลังหาของแบบนี้อยู่พอดี ส่วนตัวลองใช้แล้วประทับใจมาก ลองซื้อ สินค้า ตัวนี้มาใช้ได้สักพักแล้วค่ะ ราคาแค่ 270 บาท",
    "การเลือกซื้อ iPhone 15 ผ่านร้านค้าทางการ Shopee Mall ถือว่าไว้ใจได้ 100% เพราะได้เครื่องศูนย์ไทยแท้ มีประกันศูนย์ 1 ปีเต็ม",
    "จนเราได้สมาร์ทโฟนเข้ามาช่วยชีวิต",
]
GOOD_REVIEWS = [
    "เสื้อที่ใส่นาน ๆ ครั้ง พอหยิบมาอีกทีมีฝุ่นเกาะตรงไหล่ ใครเจอบ้างครับ\n\nถุงคลุมเสื้อผ้า Deli แบบซิปด้านหน้าในภาพเป็นตัวเลือกสำหรับแยกชุดที่ยังไม่ได้ใช้ จุดที่ควรเช็กก่อนสั่งคือความยาวถุงกับตัวเสื้อ",
    "เลือกแผ่นรองฉี่ให้น้องหมา ลองวัดพื้นที่วางก่อนกดซื้อครับ\n\nแผ่นรองฉี่ Petcho ในภาพมีไว้รองบริเวณขับถ่าย ก่อนสั่งให้เช็กขนาดแผ่นและจำนวนชิ้นในแพ็ก",
]


@pytest.mark.parametrize("text", LIVE_BAD_STORIES)
def test_live_bad_story_patterns_are_rejected(text):
    assert cq.find_issues(text, "story")


@pytest.mark.parametrize("text", LIVE_BAD_REVIEWS)
def test_live_bad_review_patterns_are_rejected(text):
    assert cq.find_issues(text, "review")


@pytest.mark.parametrize("text", GOOD_REVIEWS)
def test_honest_reviews_pass(text):
    assert cq.find_issues(text, "review") == []


@pytest.mark.parametrize("page,detail,expected", [
    ("somtam", "Apple iPhone 17 Pro 256GB", False),
    ("chowchow", "iPhone 16 Plus เครื่องศูนย์", False),
    ("kram", "iPhone 16 Plus เครื่องศูนย์", True),
    ("x", "iPhone 16 Plus เครื่องศูนย์", True),
    ("chowchow", "อาหารสุนัข สมาร์ทฮาร์ท โกลด์ 20 กก.", True),
    ("chowchow", "ทรายแมว เต้าหู้ 6 ลิตร", False),
    ("somtam", "น้ำมันมะกอก Bertolli Extra Virgin 500 มล.", True),
    ("somtam", "เสื้อผ้าเด็ก cotton", False),
])
def test_product_topic_gate(page, detail, expected):
    assert cq.is_on_topic(detail, page) is expected


@pytest.mark.parametrize("page", ["kram", "somtam", "chowchow", "x"])
def test_review_fallback_follows_the_rules(page):
    text = cq.review_fallback("หมอน TOTORI Cloud (ราคา 590 บาท)", "เครื่องนอน", page, "ลิงก์ร้านอยู่ในคอมเมนต์ 👇")
    assert "590" not in text
    assert cq.find_issues(text, "review", 400) == []


def test_page_detection():
    assert cq.page_from_path("/x/somtam-facebook-page/review.py") == "somtam"
    assert cq.page_from_path("C:\\a\\x-bot\\review.py") == "x"
    assert cq.page_from_path("/w/chowchow-facebook-page/dilemma.py") == "chowchow"


class _Resp:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, outputs):
        self.outputs, self.prompts = list(outputs), []

    def generate_content(self, model, contents):
        self.prompts.append(contents)
        return _Resp(self.outputs.pop(0))


class _Client:
    def __init__(self, outputs):
        self.models = _Models(outputs)


_KEEP_ALIVE = []


def _review_module(monkeypatch):
    if not (ROOT / "review.py").exists():
        pytest.skip("no review.py in this repo")
    if "review" in sys.modules:
        return sys.modules["review"]
    import io
    # review.py rewraps sys.stdout at import; give it a throwaway stream, then restore.
    original = sys.stdout
    dummy = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    _KEEP_ALIVE.append(dummy)
    sys.stdout = dummy
    try:
        module = importlib.import_module("review")
    except Exception as exc:  # optional runtime deps missing locally
        pytest.skip(f"review.py not importable here: {exc}")
    finally:
        _KEEP_ALIVE.append(sys.stdout)
        sys.stdout = original
    return module


def test_review_caption_retries_bad_draft_then_accepts_honest_one(monkeypatch):
    review = _review_module(monkeypatch)
    good = "ของที่หน้าตาคล้ายกันมักต่างกันที่ขนาด\n\nหมอนในภาพเป็นหมอนหนุน ก่อนสั่งให้เช็กขนาดและความสูงของหมอน"
    client = _Client(["ส่วนตัวลองใช้แล้วประทับใจมาก ราคา 590 บาท ของแท้ 100%", good])
    monkeypatch.setattr(review, "client", client, raising=False)
    monkeypatch.setattr(review, "API_ENABLED", True)
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    caption = review.generate_caption({"ประเภท": "เครื่องนอน", "ราคา": "590", "ชื่อสินค้า": "หมอน"}, None, None, None, "", "", "", None)
    assert caption.startswith(good[:20])
    assert "ร่างก่อนหน้าผิดกฎ" in client.models.prompts[1]
    assert "590" not in client.models.prompts[0]  # stale Excel price never reaches the model


def test_review_caption_falls_back_when_model_keeps_breaking_rules(monkeypatch):
    review = _review_module(monkeypatch)
    client = _Client(["ไว้ใจได้ 100% ของแท้"] * 3)
    monkeypatch.setattr(review, "client", client, raising=False)
    monkeypatch.setattr(review, "API_ENABLED", True)
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    caption = review.generate_caption({"ประเภท": "เครื่องนอน", "ชื่อสินค้า": "หมอน TOTORI"}, None, None, None, "", "", "", None)
    assert "หมอน TOTORI" in caption
    assert not [i for i in cq.find_issues(caption, "review", 400)]


def _story_generator():
    for mod, fn in (("dilemma", "generate_dog_dilemma"), ("dilemma", "generate_food_dilemma"), ("story", "translate_story")):
        if (ROOT / f"{mod}.py").exists():
            try:
                module = importlib.import_module(mod)
            except Exception as exc:
                pytest.skip(f"{mod}.py not importable here: {exc}")
            if hasattr(module, fn):
                return module, getattr(module, fn)
    pytest.skip("no story generator in this repo")


def _call(fn):
    if fn.__name__ == "translate_story":
        return fn("AITA", "title", "body")
    return fn(title="title", body="body")


def test_story_generator_rejects_slang_draft_and_retries(monkeypatch):
    module, fn = _story_generator()
    bad = '{"image_line1": "หมาแย่งเตียง", "image_line2": "ยอมไหม?", "caption": "ผมไปไถ Reddit เจอเรื่องตัวตึง 1/2", "seed_comment": "หัวจะปวด 2/2"}'
    good = ('{"image_line1": "หมาแย่งเตียงเจ้าของ", "image_line2": "ให้นอนด้วยไหม?", '
            '"caption": "เจ้าของคนหนึ่งซื้อเตียงใหม่ แต่น้องนอนกลางเตียงทุกคืน\\n\\nเขาต้องเลือกว่าจะฝึกให้น้องนอนที่ของตัวเองหรือแบ่งเตียง\\n\\nถ้าเป็นคุณจะเลือกแบบไหน? 1/2", '
            '"seed_comment": "ฝึกให้มีที่นอนของตัวเองดีกว่า วางเบาะข้างเตียงแล้วให้ขนมตอนไปนอนตรงนั้น 2/2"}')
    outputs, prompts = [bad, good], []
    monkeypatch.setattr(module, "gemini_text", lambda p: (prompts.append(p), outputs.pop(0))[1])
    result = _call(fn)
    caption = result[2] if len(result) == 4 and fn.__name__ != "translate_story" else result[1]
    assert caption.startswith("เจ้าของคนหนึ่ง")
    assert len(prompts) == 2 and "ร่างก่อนหน้าผิดกฎ" in prompts[1]


def test_story_fallbacks_follow_the_rules(monkeypatch):
    module, fn = _story_generator()
    monkeypatch.setattr(module, "gemini_text", lambda p: "")
    for _ in range(12):
        result = _call(fn)
        caption, seed = (result[1], result[2]) if fn.__name__ == "translate_story" else (result[2], result[3])
        assert cq.find_issues(caption, "story", 720) == []
        assert [i for i in cq.find_issues(seed, "story", 400) if not i.startswith("stale_opener")] == []


def test_no_source_never_asks_the_model_to_invent_a_story(monkeypatch):
    module, fn = _story_generator()
    calls = []
    monkeypatch.setattr(module, "gemini_text", lambda p: calls.append(p) or "")
    result = fn("AITA", "", "") if fn.__name__ == "translate_story" else fn(title="", body="")
    assert calls == []
    caption = result[1] if fn.__name__ == "translate_story" else result[2]
    assert "Reddit" not in caption
