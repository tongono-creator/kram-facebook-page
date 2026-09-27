"""Shared writing rules and checks for the page bots.

Goal: posts a reader understands in one pass - plain Thai, faithful to the
source, no invented experience or unverified claims, no scare tactics.
The same file is copied into every page repo; keep it dependency-free.
"""
from __future__ import annotations

import re

# Slang and hype that made posts sound alike and harsh (seen in live posts).
BANNED_SLANG = (
    "รากมะม่วง", "ตัวตึง", "หัวจะปวด", "สับสุด", "ชีเสิร์ฟ", "ประสาทแดก",
    "ขนลุกคักปู่เอ้ย", "โฮ่งมาก", "ปังปุริเย่", "มหากาพย์", "ยับเยิน",
    "เลือดซิบ", "ตาแตก", "โคตร", "วีนฉ่ำ", "เดือดจัด",
)
# Source-first openers repeated in almost every story post.
STALE_OPENERS = (
    "ไปไถ", "ผมไปไถ", "แอดมินไปไถ", "เพิ่งไปไถ", "วันก่อนผมไถ", "ไปเจอเคส",
    "ไปอ่านเจอ", "เพิ่งไปอ่าน", "ผมเพิ่งไปอ่าน", "ไปเจอเรื่อง", "ไปเจอประเด็น",
    "ไปเจอโพสต์", "ไปเจอกระทู้", "ไปส่อง", "มีทาสหมาคนหนึ่ง",
)
FAKE_EXPERIENCE = (
    "ลองใช้", "ใช้จริง", "ซื้อมา", "กดสั่ง", "จัดมา", "ใช้มาแล้ว", "ใช้ได้สักพัก",
    "ส่วนตัวประทับใจ", "โดนป้ายยา", "เกินคาดจริง", "ไม่ได้จะซื้อ", "เห็นคนพูดถึงเยอะเลยลอง",
    "ช่วยชีวิต", "ลองแล้ว", "ประทับใจมาก",
)
UNVERIFIED_CLAIMS = (
    "100%", "ของแท้", "ประกันศูนย์", "รับประกัน", "ส่งฟรี", "ไม่ต้องเสี่ยง",
    "ย้อมแมว", "ถูกที่สุด", "ขายดีที่สุด", "ล็อตสุดท้าย", "ใกล้หมด", "ไว้ใจได้",
)
PLACEHOLDERS = ("สินค้า ตัวนี้", "ลองซื้อ สินค้า", "ของ สินค้า", "{", "}")
# Graphic harm details that turned food/pet stories into scare posts.
SCARE_WORDS = (
    "น้ำลายฟูมปาก", "ชักเกร็ง", "ท้องร่วงหนัก", "อาเจียน", "ฟอกไต", "ไตพัง",
    "เกือบตาย", "เกือบเสียชีวิต", "ช็อกยา", "ระบบหายใจ",
)

STORY_MAX_CHARS = 700
REVIEW_MAX_CHARS = 420

PAGES = {
    "kram": {"ending": "ครับ", "pronoun": "ผม", "audience": "คนทำงานและคนทั่วไปที่ชอบเรื่องชีวิตจริงชวนคิด"},
    "somtam": {"ending": "ค่ะ", "pronoun": "เรา", "audience": "คนชอบทำอาหารและของกิน"},
    "chowchow": {"ending": "ฮะ", "pronoun": "ผม", "audience": "คนเลี้ยงหมา"},
    "x": {"ending": "ครับ", "pronoun": "ผม", "audience": "คนไทยบน X ที่ชอบเรื่องสั้นอ่านจบไว"},
}


def page_from_path(path: str) -> str:
    norm = str(path).replace("\\", "/").lower()
    for key in ("somtam", "chowchow", "x-bot", "kram"):
        if key in norm:
            return "x" if key == "x-bot" else key
    return "kram"


def _hits(text: str, words) -> list[str]:
    return [w for w in words if w in text]


def find_issues(text: str, kind: str, max_chars: int | None = None) -> list[str]:
    """Return human-readable problems; empty list means the text passes."""
    text = str(text or "").strip()
    if not text:
        return ["empty"]
    issues = [f"slang:{w}" for w in _hits(text, BANNED_SLANG)]
    if "**" in text or re.search(r"^\s*[-•▪️*]\s", text, re.MULTILINE):
        issues.append("markdown")
    if kind == "story":
        head = text[:60]
        issues += [f"stale_opener:{w}" for w in _hits(head, STALE_OPENERS)]
        issues += [f"scare:{w}" for w in _hits(text, SCARE_WORDS)]
        limit = max_chars or STORY_MAX_CHARS
    else:
        issues += [f"fake_experience:{w}" for w in _hits(text, FAKE_EXPERIENCE)]
        issues += [f"claim:{w}" for w in _hits(text, UNVERIFIED_CLAIMS)]
        issues += [f"placeholder:{w}" for w in _hits(text, PLACEHOLDERS)]
        if re.search(r"\d[\d,]*\s*(?:บาท|฿)|฿\s*\d", text):
            issues.append("price")
        limit = max_chars or REVIEW_MAX_CHARS
    if len(text) > limit:
        issues.append(f"too_long:{len(text)}>{limit}")
    return issues


def story_rules(page: str, max_chars: int = STORY_MAX_CHARS) -> str:
    p = PAGES.get(page, PAGES["kram"])
    return (
        "กฎการเขียนให้อ่านรอบเดียวเข้าใจ (สำคัญกว่าความหวือหวา):\n"
        f"1. ผู้อ่านคือ{p['audience']} ใช้คำลงท้าย '{p['ending']}' ภาษาพูดสุภาพ ประโยคสั้น คำง่าย\n"
        "2. ประโยคแรกบอกแก่นของเรื่องทันที ว่าใครเจอสถานการณ์อะไร ห้ามเปิดด้วยที่มา "
        "(ห้ามขึ้นต้นว่า ไปไถ / ไปเจอ / ไปอ่านเจอ / เพิ่งไปอ่าน / มีทาสหมาคนหนึ่ง)\n"
        "3. เล่าเฉพาะสิ่งที่มีในต้นฉบับ ห้ามเติมเหตุการณ์ ตัวเลข ราคา ยี่ห้อ อาการป่วย หรือคำพูดที่ต้นฉบับไม่มี "
        "ถ้าต้นฉบับสั้นก็เล่าสั้น\n"
        "4. แบ่ง 3 ย่อหน้าสั้น: เกิดอะไรขึ้น -> จุดที่ต้องเลือกหรือขัดแย้ง -> ข้อคิดที่ใช้ได้จริง 1 ประโยค (ถ้ามี)\n"
        "5. ปิดด้วยคำถามเจาะจงเรื่องนี้ 1 ข้อที่ตอบง่าย เช่นให้เลือกระหว่าง 2 ทาง\n"
        "6. เรื่องสุขภาพคนหรือสัตว์: เล่าเรียบๆ ไม่บรรยายอาการน่ากลัว ไม่ใช้ความตายเป็นมุก ไม่แนะนำยาหรือวิธีรักษา "
        "ถ้ามีอาการป่วยให้ปิดว่าควรปรึกษาแพทย์หรือสัตวแพทย์\n"
        f"7. ห้ามสแลงแรงหรือคำเกินจริง: {', '.join(BANNED_SLANG)}\n"
        f"8. ความยาวรวมไม่เกิน {max_chars} ตัวอักษร ไม่มี markdown ไม่มีบูลเล็ต อีโมจิไม่เกิน 1 ตัว\n"
    )


def review_rules(page: str) -> str:
    p = PAGES.get(page, PAGES["kram"])
    return (
        "กฎโพสต์แนะนำสินค้า (แอดมินยังไม่ได้ซื้อหรือใช้สินค้า):\n"
        "1. ประโยคแรกเป็นปัญหาหรือสถานการณ์ใช้งานที่คนทั่วไปเจอจริง ไม่ใช่เรื่องของแอดมิน\n"
        "2. บอกว่าสินค้าในภาพคืออะไรตามข้อมูล แล้วบอก 1-2 จุดที่ควรเช็กก่อนสั่ง เช่น รุ่น ขนาด ตัวเลือก จำนวนในแพ็ก วันหมดอายุ\n"
        "3. ห้ามเขียนว่าแอดมินซื้อ ลอง ใช้ หรือประทับใจ ห้ามแต่งเหตุการณ์สมมติ\n"
        "4. ห้ามใส่ราคา (ราคาเปลี่ยนบ่อย) ห้ามเคลม ของแท้ 100% ประกัน ส่งฟรี ถูกที่สุด ขายดี ของใกล้หมด ห้ามเคลมสรรพคุณสุขภาพ\n"
        "5. ห้ามขึ้นต้นด้วยชื่อแบรนด์ ห้ามคำโฆษณา เช่น คุ้ม ห้ามพลาด ดีงาม ของดี แนะนำเลย\n"
        f"6. ใช้คำลงท้าย '{p['ending']}' 2-3 ประโยค รวมไม่เกิน 300 ตัวอักษร ไม่มี markdown\n"
    )


REVIEW_ANGLES = (
    "เริ่มจากปัญหาที่เจอบ่อยในชีวิตประจำวันที่สินค้านี้เกี่ยวข้อง",
    "เริ่มจากจุดที่คนมักเลือกผิดหรือสั่งผิดสำหรับสินค้าประเภทนี้",
    "เริ่มจากสถานการณ์ใช้งานที่เห็นภาพชัด",
    "เริ่มจากคำถามที่คนมักสงสัยก่อนซื้อสินค้าประเภทนี้",
)

_DOG_TERMS = (
    "หมา", "สุนัข", "dog", "puppy", "ลูกสุนัข", "สายจูง", "ปลอกคอ", "แผ่นรองฉี่",
    "ขนสุนัข", "ชิวาวา", "ชิสุ", "ปอม", "คอร์กี้", "โกลเด้น", "ลาบราดอร์",
    "สัตว์เลี้ยง", "pet", "เครื่องเป่าขน",
)
_FOOD_TERMS = (
    "อาหาร", "ขนม", "เครื่องดื่ม", "กาแฟ", "ชา", "นม", "กุ้ง", "ปลา", "หมู", "ไก่",
    "เนื้อ", "ข้าว", "เส้น", "บะหมี่", "ซอส", "น้ำปลา", "พริก", "ผลไม้", "ผัก",
    "ครัว", "กระทะ", "หม้อ", "มีด", "จาน", "ชาม", "เตา", "อบ", "ทอด", "น้ำมัน",
    "เครื่องปรุง", "มัทฉะ", "ขนมปัง", "หอยจ๊อ",
)
_PHONE_TERMS = ("iphone", "apple", "สมาร์ทโฟน", "สมาร์ตโฟน", "มือถือ", "โทรศัพท์")


def is_on_topic(detail: str, page: str) -> bool:
    """Hard product filter so each page only sells what its audience follows it for."""
    text = str(detail or "").lower()
    if page == "chowchow":
        blocked = ("แมว", "cat", "kitten") + _PHONE_TERMS
        return not any(w in text for w in blocked) and any(w in text for w in _DOG_TERMS)
    if page == "somtam":
        blocked = ("อาหารแมว", "อาหารหมา", "อาหารสุนัข", "สุนัข", "เครื่องสำอาง", "เสื้อผ้า", "รองเท้า") + _PHONE_TERMS
        return not any(w in text for w in blocked) and any(w in text for w in _FOOD_TERMS)
    return True  # kram and X are general-interest pages (iPhone allowed)


def short_name(detail: str, limit: int = 40) -> str:
    first = str(detail or "").strip().splitlines()[0] if str(detail or "").strip() else ""
    first = re.sub(r"[\[\]【】()（）]", " ", first)
    first = re.sub(r"(?:ราคา|฿)\s*[\d,]+(?:\.\d+)?\s*(?:บาท)?", "", first)
    first = re.sub(r"\s+", " ", first).strip(" -|,")
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(" ", 1)[0]
    return cut or first[:limit]


_OPENERS = {
    "somtam": "ของเข้าครัวหลายอย่างหน้าตาคล้ายกัน อ่านรายละเอียดก่อนหยิบใส่ตะกร้าช่วยได้เยอะ",
    "chowchow": "ของใช้น้องหมาแต่ละแบบเหมาะกับขนาดตัวและนิสัยไม่เหมือนกัน",
    "x": "ก่อนสั่งของออนไลน์ เช็กตัวเลือกให้ตรงก่อนช่วยได้เยอะ",
    "kram": "ของที่หน้าตาคล้ายกันในร้านออนไลน์ มักต่างกันที่รุ่นและตัวเลือก",
}


def review_fallback(detail: str, product_type: str, page: str, closing: str = "") -> str:
    """Honest template used when the model is unavailable or keeps breaking the rules."""
    p = PAGES.get(page, PAGES["kram"])
    name = short_name(detail) or "สินค้าในภาพ"
    kind = str(product_type or "").strip()
    kind_part = f" เป็น{kind}" if kind and kind not in ("สินค้า", "ของกินของใช้") else ""
    body = (
        f"{_OPENERS.get(page, _OPENERS['kram'])}{p['ending']}\n\n"
        f"{name} ในภาพ{kind_part} ก่อนสั่งให้เช็กรุ่น ขนาด และตัวเลือกในร้านให้ตรงกับที่ต้องการ{p['ending']}"
    )
    if page == "x":
        return body.replace("\n\n", " ")[:200]
    return f"{body}\n\n{closing}".strip()
