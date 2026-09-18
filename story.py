# -*- coding: utf-8 -*-
"""story.py — ดึงเรื่องเล่าจาก Reddit แปลไทย โพส Facebook เพจกรามค้าง"""

import os, time, re, sys, io, json, random, time, requests, hashlib
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timezone, timedelta
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

# ── Config ──────────────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ.get("KRAM_PAGE_ACCESS_TOKEN", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "") or "DUMMY_KEY"

client      = genai.Client(api_key=GEMINI_API_KEY, http_options=HttpOptions(timeout=300000))
TEXT_MODELS       = ["gemini-flash-latest", "gemini-flash-latest"]
OUTPUT_DIR  = "output"
FONT_PATH   = os.path.join(os.path.dirname(__file__), "fonts", "Sarabun-ExtraBold.ttf")
HISTORY_FILE = "story_history.txt"
HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; KramBot/1.0; +github)"}

os.makedirs(OUTPUT_DIR, exist_ok=True)

if not PAGE_ACCESS_TOKEN:
    try:
        from config import PAGE_ACCESS_TOKEN as _tok, GEMINI_API_KEY as _key
        PAGE_ACCESS_TOKEN = _tok
        GEMINI_API_KEY    = _key
    except ImportError:
        pass

# ── Subreddits ──────────────────────────────────────────────────────────────
STORY_SUBREDDITS = [
    "AITA",
    "confessions",
    "tifu",
    "TrueOffMyChest",
    "pettyrevenge",
    "WorkStories",
    "antiwork",
    "relationship_advice",
]

SUB_CONTEXT = {
    "AITA":              "เรื่อง 'ฉันผิดไหม?' จากชีวิตจริง",
    "confessions":       "เรื่องสารภาพบาปที่ซุกซ่อนมานาน",
    "tifu":              "เรื่องเล่าพลาดหน้าแตกชีวิตจริง",
    "TrueOffMyChest":    "เรื่องที่อยากระบาย ต้องบอกสักคน",
    "pettyrevenge":      "เรื่องแก้แค้นสะใจสไตล์คนธรรมดา",
    "WorkStories":       "เรื่องเล่าจากที่ทำงาน",
    "antiwork":          "เรื่องเล่าจากที่ทำงาน",
    "relationship_advice": "เรื่องรัก ดราม่าความสัมพันธ์",
}

# ── History ─────────────────────────────────────────────────────────────────
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return [l.strip() for l in f if l.strip()]
        except Exception:
            return []
    return []

def save_to_history(url):
    items = load_history()
    items.append(url)
    items = items[-300:]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for it in items:
                f.write(it + "\n")
    except Exception as e:
        print(f"History save error: {e}")

def reddit_title_key(title):
    """Stable dedup key for a Reddit post's identity (prefix 'title:').
    จับโพสซ้ำที่ใช้ title/รูปเดิมแต่มาในลิงก์ใหม่หรือพาดหัวใหม่"""
    norm = re.sub(r"[^\w฀-๿]+", "", (title or "").strip().lower())
    if not norm:
        return ""
    return "title:" + hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]

# ── Reddit fetch ─────────────────────────────────────────────────────────────
def get_reddit_story(history_set):
    """ดึง text post จาก subreddits ผ่าน RSS — คืน dict หรือ None"""
    NS = {"atom": "http://www.w3.org/2005/Atom"}
    subs = random.sample(STORY_SUBREDDITS, len(STORY_SUBREDDITS))
    for sub in subs:
        rss_url = f"https://www.reddit.com/r/{sub}/hot.rss?limit=30"
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root    = ET.fromstring(resp.content)
            entries = root.findall("atom:entry", NS)
            candidates = []
            for entry in entries:
                title   = entry.findtext("atom:title", "", NS).strip()
                content = entry.findtext("atom:content", "", NS)
                link_el = entry.find("atom:link", NS)
                permalink = link_el.get("href", "") if link_el is not None else ""

                # ถอด HTML tags เพื่อดูว่ามีเนื้อเรื่องไหม
                body = re.sub(r"<[^>]+>", " ", content or "").strip()
                body = re.sub(r"\s{2,}", " ", body)

                if (len(body) >= 200
                        and permalink not in history_set
                        and reddit_title_key(title) not in history_set
                        and "reddit.com/r/" in permalink):
                    candidates.append({
                        "subreddit": sub,
                        "title":     title,
                        "body":      body[:1200],
                        "permalink": permalink,
                    })
            if candidates:
                chosen = random.choice(candidates[:15])
                print(f"Story: r/{sub} | {chosen['title'][:70]}")
                return chosen
        except Exception as e:
            print(f"Reddit error ({sub}): {e}")
    return None

# ── Gemini text helper ────────────────────────────────────────────────────────
def gemini_text(prompt):
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            time.sleep(2)
        for attempt in range(2):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                return resp.text.strip()
            except Exception as e:
                print(f"[{model}] attempt {attempt+1} failed: {str(e)[:80]}")
                if attempt < 1:
                    time.sleep(10)
    return ""

# ── Translate + create hook ──────────────────────────────────────────────────
def contains_thai(text):
    if not text:
        return False
    return any('\u0e00' <= char <= '\u0e7f' for char in text)

# \u0e04\u0e33\u0e02\u0e36\u0e49\u0e19\u0e15\u0e49\u0e19 hook \u0e17\u0e35\u0e48\u0e16\u0e37\u0e2d\u0e27\u0e48\u0e32 "\u0e21\u0e35\u0e1b\u0e23\u0e30\u0e18\u0e32\u0e19\u0e0a\u0e31\u0e14" \u2014 \u0e1a\u0e23\u0e23\u0e17\u0e31\u0e14\u0e41\u0e23\u0e01\u0e15\u0e49\u0e2d\u0e07\u0e21\u0e35\u0e04\u0e33\u0e43\u0e14\u0e04\u0e33\u0e2b\u0e19\u0e36\u0e48\u0e07
_HOOK_SUBJECTS = (
    "\u0e1a\u0e23\u0e34\u0e29\u0e31\u0e17", "\u0e2b\u0e31\u0e27\u0e2b\u0e19\u0e49\u0e32", "\u0e40\u0e08\u0e49\u0e32\u0e19\u0e32\u0e22", "\u0e40\u0e21\u0e35\u0e22", "\u0e1c\u0e31\u0e27", "\u0e41\u0e1f\u0e19", "\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e19", "\u0e1c\u0e21", "\u0e09\u0e31\u0e19",
    "\u0e25\u0e39\u0e01\u0e04\u0e49\u0e32", "\u0e1e\u0e48\u0e2d", "\u0e41\u0e21\u0e48", "\u0e25\u0e39\u0e01", "\u0e1e\u0e35\u0e48", "\u0e19\u0e49\u0e2d\u0e07", "\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e19\u0e23\u0e48\u0e27\u0e21\u0e07\u0e32\u0e19", "HR", "AI", "\u0e25\u0e38\u0e07", "\u0e1b\u0e49\u0e32",
)
# \u0e27\u0e25\u0e35\u0e25\u0e2d\u0e22\u0e17\u0e35\u0e48\u0e17\u0e33\u0e43\u0e2b\u0e49 hook \u0e2d\u0e48\u0e32\u0e19\u0e44\u0e21\u0e48\u0e23\u0e39\u0e49\u0e40\u0e23\u0e37\u0e48\u0e2d\u0e07 \u2014 \u0e40\u0e08\u0e2d\u0e41\u0e25\u0e49\u0e27 reject
_HOOK_BAD_PHRASES = ("\u0e17\u0e35\u0e48\u0e1a\u0e2d\u0e01", "\u0e21\u0e31\u0e19\u0e04\u0e37\u0e2d\u0e2d\u0e30\u0e44\u0e23", "\u0e04\u0e37\u0e2d\u0e2d\u0e30\u0e44\u0e23", "\u0e43\u0e04\u0e23\u0e08\u0e30\u0e44\u0e1b\u0e22\u0e2d\u0e21")

def is_hook_clear(hook):
    """True \u0e16\u0e49\u0e32 hook \u0e1c\u0e48\u0e32\u0e19\u0e40\u0e01\u0e13\u0e11\u0e4c: \u0e1a\u0e23\u0e23\u0e17\u0e31\u0e14\u0e41\u0e23\u0e01\u0e21\u0e35\u0e1b\u0e23\u0e30\u0e18\u0e32\u0e19 + \u0e44\u0e21\u0e48\u0e21\u0e35\u0e27\u0e25\u0e35\u0e25\u0e2d\u0e22 + \u0e1b\u0e34\u0e14\u0e14\u0e49\u0e27\u0e22\u0e04\u0e33\u0e16\u0e32\u0e21"""
    if not hook or not contains_thai(hook):
        return False
    lines = [l.strip() for l in hook.split("\n") if l.strip()]
    if not lines:
        return False
    first = lines[0]
    if not any(first.startswith(s) or s in first for s in _HOOK_SUBJECTS):
        return False
    if any(bad in hook for bad in _HOOK_BAD_PHRASES):
        return False
    if "\u0e44\u0e2b\u0e21" not in lines[-1] and "?" not in lines[-1]:
        return False
    return True

ACCENT_COLOR = (0, 191, 255)  # ฟ้า #00BFFF
WHITE_COLOR  = (255, 255, 255)

FIRST_PERSON_TERMS = ("ผม", "ฉัน", "ดิฉัน", "หนู", "เรา", "พวกเรา", "ตัวเรา", "ของเรา")

def contains_first_person(text):
    clean = (text or "").replace("\u200b", "")
    return any(term in clean for term in FIRST_PERSON_TERMS)

def apply_slang_rules(text):
    if not text:
        return text
    # Rule: แทนคำว่า ให้ไปตาย / ประหารชีวิต / ฆ่า ในบริบทเล่าเรื่องด้วย ไปคุยกับรากมะม่วง
    text = re.sub(r'ให้(?:ไป)?ตาย|ให้ประหารชีวิต|ส่งไปตาย|เอาไปฆ่า', 'ไปคุยกับรากมะม่วง', text)
    return text

def translate_story(subreddit, title, body):
    """
    คืน (hook, caption, seed_comment, x_thread)
    hook = พาดหัวบนรูป 2 บรรทัด (บรรทัดแรกสีฟ้า บรรทัดสองสีขาว) คั่นด้วย \n
    caption = เรื่องเล่าบุคคลที่สาม 5 ชั้น + คำถามตัดสินใจ (ลงท้าย 1/2)
    seed_comment = ความเห็นแอดมินเลือกข้างเด็ดขาดทันที (2/2)
    x_thread = ข้อความทวีตใน X 2 ทวีต (1/2 และ 2/2)
    """
    context = SUB_CONTEXT.get(subreddit, "เรื่องเล่าจากชีวิตจริง")
    angles = [
        "มุมมองที่ 1: ดราม่าข้อพิพาทความสัมพันธ์ (ความรัก/ครอบครัว/เพื่อนร่วมงาน)",
        "มุมมองที่ 2: บทเรียนราคาแพง / รู้งี้ไม่น่าทำ (The Cost of Cheap — ความผิดพลาดที่เสียเงินก้อนโตเพราะประหยัดผิดจุดหรือไว้ใจผิดคน)",
        "มุมมองที่ 3: ศาลดราม่าความรับผิดชอบ (ใครผิด / ใครควรเป็นฝ่ายจ่ายชดใช้)"
    ]
    chosen_angle = random.choice(angles)

    prompt = (
        f"นี่คือเรื่องเล่าจริงจาก Reddit r/{subreddit} ({context}):\n\n"
        f"Title: {title}\n\n"
        f"Story: {body}\n\n"
        f"งาน: แปลงเรื่องนี้มาทำเป็นคอนเทนต์สไตล์ Threads ชวนถกและตัดสิน ภาษาไทยสำหรับ Facebook เพจกรามค้าง และ X (Twitter)\n"
        f"ทิศทางคอนเทนต์รอบนี้: {chosen_angle}\n"
        "กลุ่มเป้าหมาย: ผู้ชายไทย วัยทำงาน 25-45 ปี\n\n"
        "กฎเหล็กสำคัญที่สุด:\n"
        "1. แอดมินต้องเป็น 'บุคคลที่สาม' (3rd-Party Observer) ที่ไปอ่านเจอเรื่องนี้จาก Reddit/โซเชียล แล้วนำมาเล่าต่อชวนลูกเพจคุย\n"
        "   - ห้ามสวมบทเป็นเจ้าของเรื่องเด็ดขาด ห้ามใช้คำว่า 'แฟนผม/หัวหน้าผม/ผมทำ' ในตัวเรื่อง\n"
        "   - ให้ระบุตัวละคร เช่น 'ชายคนหนึ่ง...', 'พนักงานคนหนึ่ง...', 'คู่รักคู่หนึ่ง...'\n"
        "2. คำศัพท์พิเศษ: หากในเรื่องมีบริบทให้ไปตาย หรือลงโทษสูงสุด ให้ใช้คำสแลงว่า 'ไปคุยกับรากมะม่วง'\n"
        "3. ภาษาพูดผู้ชาย สุภาพแต่เป็นกันเอง คมคาย ตลกร้าย ลงท้ายด้วย 'ครับ' หรือ 'พี่ๆ'\n\n"
        "ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความอื่นนอก JSON):\n"
        '{\n'
        '  "image_line1": "พาดหัวสั้นๆ บรรทัดที่ 1 (ความยาว 8-14 ตัวอักษรไทย เน้นประธาน/ปัญหาหลัก เช่น \'แฟนขอเงินแสน\')",\n'
        '  "image_line2": "พาดหัวสั้นๆ บรรทัดที่ 2 (ความยาว 8-14 ตัวอักษรไทย คำถามหรือทางแยก เช่น \'ควรให้ยืมไหม?\')",\n'
        '  "caption": "caption เล่าเรื่อง 5 ชั้นเป็นความเรียงธรรมชาติ จบด้วยคำถาม 2 ทางเลือกเจาะจงกับเรื่องนี้ และปิดท้ายด้วย \'1/2\'",\n'
        '  "seed_comment": "ความคิดเห็นของแอดมินในฐานะผู้ชาย (ลงท้ายครับ) ที่เลือกข้างอย่างเด็ดขาดข้างใดข้างหนึ่งทันทีเพื่อเปิดประเด็นถกเถียง ห้ามตอบกลางๆ พร้อมหยอดข้อคิดหรือวิธีแก้ปัญหาในชีวิตจริงสั้นๆ และปิดท้ายด้วย \'2/2\'"\n'
        '}\n\n'
        "=== คำอธิบาย caption 5 ชั้น (เขียนต่อกัน ห้ามใส่ bullet points หรือหัวข้อ) ===\n"
        "ชั้น 1 — ATTRIBUTION HOOK: บอกสั้นๆ ว่าไปอ่านเจอเรื่องนี้จาก Reddit แล้วเปิดปมขัดแย้งทันที\n"
        "ชั้น 2 — EXPAND: ขยายบริบทสั้นๆ ยั่วให้อยากติดตาม\n"
        "ชั้น 3 — CLEAR CONTENT: เล่าเรื่องหลักเรียงลำดับ ชัดเจน ไหลลื่น ภาษาคนธรรมชาติ\n"
        "ชั้น 4 — TURNING POINT: จุดพีคที่เป็นทางแยกหรือข้อพิพาท\n"
        "ชั้น 5 — JUDGMENT CALL: ปิดด้วยคำถามที่ระบุสองทางเลือกชัดเจน แล้วลงท้ายด้วย '1/2'\n"
    )
    raw = gemini_text(prompt)
    hook, caption, seed_comment = "", "", ""
    if raw:
        clean_raw = raw.strip()
        if clean_raw.startswith("```"):
            clean_raw = re.sub(r"^```(?:json)?\n", "", clean_raw)
            clean_raw = re.sub(r"\n```$", "", clean_raw)
            clean_raw = clean_raw.strip()

        m = re.search(r'\{.*?\}', clean_raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                l1 = data.get("image_line1", "").strip()
                l2 = data.get("image_line2", "").strip()
                if l1 and l2:
                    hook = f"{l1}\n{l2}"
                elif l1:
                    hook = l1
                caption = data.get("caption", "").strip()
                seed_comment = data.get("seed_comment", "").strip()
            except Exception as e:
                print(f"JSON parse error: {e}")

    # Apply slang and clean
    hook = apply_slang_rules(hook)
    caption = apply_slang_rules(caption)
    seed_comment = apply_slang_rules(seed_comment)

    # Fallback to local high-quality presets if failed or missing Thai
    if not hook or not caption or not seed_comment or not contains_thai(hook) or not contains_thai(caption):
        print("AI generation failed or missing Thai. Using local dilemma presets.")
        fallbacks = [
            {
                "line1": "แฟนแอบนัดคนเก่า",
                "line2": "ควรคุยหรือเลิก?",
                "caption": "ไปเจอเรื่องหนึ่งใน Reddit ครับ ชายคนหนึ่งพบว่าแฟนยังแอบคุยและนัดเจอแฟนเก่านอกรอบ ทั้งที่บอกว่าเป็นแค่เพื่อนร่วมงานธรรมดา ตอนนี้เขาลังเลว่าจะยอมนั่งคุยเปิดอกอีกรอบ หรือตัดสินใจตัดใจจบความสัมพันธ์ไปเลยดี ถ้าเป็นพี่ๆ จะให้โอกาสอธิบายหรือพอแค่นี้ครับ? 1/2",
                "seed_comment": "เคสนี้ถ้าแอบนัดเจอลับหลังคือทำลายความไว้ใจไปแล้ว แนะนำให้ถอยออกมาดีกว่าครับ 2/2"
            },
            {
                "line1": "งานมั่นคงแต่ใจพัง",
                "line2": "ควรทนหรือถอย?",
                "caption": "ไปอ่านเจอกระทู้คนทำงานใน Reddit ครับ พนักงานคนหนึ่งทำงานบริษัทใหญ่เงินเดือนดีมาก แต่ตื่นมาพร้อมความเครียดจนนอนไม่หลับทุกคืน ถ้าต้องเลือกระหว่างความมั่นคงทางการเงิน กับการรักษาชีวิตและสุขภาพจิต ถ้าเป็นพี่ๆ จะยอมกัดฟันทนต่อหรือยื่นใบลาออกครับ? 1/2",
                "seed_comment": "งานหาใหม่เมื่อไหร่ก็ได้ แต่สุขภาพจิตพังแล้วรักษายากมาก เคสนี้ควรรีบวางแผนหางานใหม่แล้วถอยครับ 2/2"
            },
            {
                "line1": "เพื่อนยืมเงินแต่งงาน",
                "line2": "ทวงแล้วทำเงียบ",
                "caption": "มีโพสต์หนึ่งแชร์ใน Reddit ครับ ชายคนหนึ่งให้เพื่อนสนิทยืมเงินก้อนไปจัดงานแต่งงาน ผ่านมาสองปีเพื่อนไม่ยอมคืนเงินสักบาท แต่ลงรูปไปเที่ยวต่างประเทศฉ่ำๆ ถ้าเป็นพี่ๆ จะแตกหักทวงหน้าฟีด หรือยอมตัดใจเสียเงินเพื่อรักษาคำว่าเพื่อนครับ? 1/2",
                "seed_comment": "เพื่อนที่เห็นเราเดือดร้อนแต่ตัวเองไปเที่ยวสบายใจ ไม่ใช่เพื่อนแท้แล้วครับ เคสนี้ควรทวงให้ถึงที่สุด 2/2"
            }
        ]
        chosen = random.choice(fallbacks)
        hook = f"{chosen['line1']}\n{chosen['line2']}"
        caption = chosen["caption"]
        seed_comment = chosen["seed_comment"]

    # Ensure 1/2 and 2/2 markings
    if "1/2" not in caption:
        caption = caption.rstrip() + " 1/2"
    if "2/2" not in seed_comment:
        seed_comment = seed_comment.rstrip() + " 2/2"

    # Build X thread
    t1 = caption[:245]
    if "1/2" not in t1:
        t1 = t1.rstrip() + " 1/2"
    t2 = seed_comment[:245]
    if "2/2" not in t2:
        t2 = t2.rstrip() + " 2/2"
    x_thread = [t1, t2]

    return hook, caption, seed_comment, x_thread

# ── Thai text wrap (leading vowel safe) ──────────────────────────────────────
_LEADING_VOWELS  = set("เแโใไ")
_COMBINING_CHARS = set("่้๊๋์ิีึืุูัํ็")

def _wrap_char(draw, text, font, max_width):
    if "​" in text:
        tokens = text.split("​")
    else:
        tokens = list(text)
    lines, current = [], ""
    for token in tokens:
        test = current + token
        fits = draw.textbbox((0, 0), test, font=font)[2] <= max_width
        if fits or (len(token) == 1 and token in _COMBINING_CHARS):
            current = test
        else:
            if current:
                if current[-1] in _LEADING_VOWELS:
                    orphan  = current[-1]
                    current = current[:-1]
                    if current:
                        lines.append(current)
                    current = orphan + token
                else:
                    lines.append(current)
                    current = token
            else:
                current = token
    if current:
        lines.append(current)
    return lines or [text]

def _wrap_words(draw, text, font, max_width):
    words = [w for w in text.split(" ") if w]
    if not words:
        return [text]
    lines, current = [], ""
    for word in words:
        test = word if not current else current + " " + word
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def wrap_text(draw, text, font, max_width):
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return [text]
    if " " in text.strip():
        lines = _wrap_words(draw, text, font, max_width)
        if getattr(font, "size", 99) <= 75:
            new_lines = []
            for l in lines:
                if draw.textbbox((0, 0), l, font=font)[2] > max_width:
                    new_lines.extend(_wrap_char(draw, l, font, max_width))
                else:
                    new_lines.append(l)
            lines = new_lines
    else:
        lines = [text] if getattr(font, "size", 99) > 75 else _wrap_char(draw, text, font, max_width)
    return lines


# # ── Generate image ───────────────────────────────────────────────────────────
def generate_image(hook):
    """Dark card 1080x1080 — line 1 ฟ้า (#00BFFF), line 2 ขาว (#FFFFFF) auto-fit กึ่งกลาง"""
    bkk  = timezone(timedelta(hours=7))
    ts   = datetime.now(bkk).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"story_{ts}.jpg")

    W = H = 1080
    img  = Image.new("RGB", (W, H), (0, 0, 0))   # pure black
    draw = ImageDraw.Draw(img)

    PAD      = 80
    max_w    = W - PAD * 2   # 920px
    LINE_GAP = 28

    # แยก hook เป็นบรรทัด (ตาม \n ที่ Gemini กำหนด)
    raw_lines = [l.strip() for l in hook.strip().split("\n") if l.strip()]

    # auto-fit: เริ่ม 110px ลดลงทีละ 4 จนพอดี
    font_size = 110
    best_font = None
    best_lines = []
    while font_size >= 36:
        font = ImageFont.truetype(FONT_PATH, font_size)
        wrapped = []
        for idx, l in enumerate(raw_lines):
            for w in wrap_text(draw, l, font, max_w):
                wrapped.append((w, idx == 0))

        def lh(text):
            bb = draw.textbbox((0, 0), text, font=font)
            return bb[3] - bb[1]

        total_h  = sum(lh(t) + LINE_GAP for t, _ in wrapped)
        width_ok = all(draw.textbbox((0, 0), t, font=font)[2] <= max_w for t, _ in wrapped)

        if total_h <= H - PAD * 2 and width_ok:
            best_font  = font
            best_lines = wrapped
            break
        font_size -= 4

    if not best_font:
        best_font  = ImageFont.truetype(FONT_PATH, 36)
        best_lines = []
        for idx, l in enumerate(raw_lines):
            for w in wrap_text(draw, l, best_font, max_w):
                best_lines.append((w, idx == 0))

    print(f"Story image font size: {font_size} | lines: {len(best_lines)}")

    def lh(text):
        bb = draw.textbbox((0, 0), text, font=best_font)
        return bb[3] - bb[1]
    total_h = sum(lh(t) + LINE_GAP for t, _ in best_lines)

    y = (H - total_h) // 2

    for text, is_first in best_lines:
        bb = draw.textbbox((0, 0), text, font=best_font)
        w  = bb[2] - bb[0]
        x  = (W - w) // 2
        dy = y - bb[1]
        line_color = ACCENT_COLOR if is_first else WHITE_COLOR
        draw.text((x + 3, dy + 3), text, font=best_font, fill=(30, 30, 30))
        draw.text((x, dy), text, font=best_font, fill=line_color)
        y += lh(text) + LINE_GAP

    # watermark
    try:
        wm_font = ImageFont.truetype(FONT_PATH, 26)
        wm_text = "เรื่องจริงจาก Reddit"
        bb = draw.textbbox((0, 0), wm_text, font=wm_font)
        draw.text(((W - (bb[2]-bb[0])) // 2, H - 55), wm_text, font=wm_font, fill=(70, 70, 70))
    except Exception:
        pass

    img.save(path, "JPEG", quality=92)
    print(f"Story image saved: {path}")
    return path

# ── Post to X (Twitter) ──────────────────────────────────────────────────────
def post_to_x_thread(tweets, image_path=None):
    """
    โพสต์ thread ลง X โดยใช้ tweepy
    tweets: list ของข้อความ (เช่น ['ข้อความ 1/2', 'ข้อความ 2/2'])
    image_path: พาธรูปภาพประกอบ (จะแนบที่ทวีตแรก)
    """
    X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
    X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET", "")
    X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
    X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

    if not X_CONSUMER_KEY or not X_CONSUMER_SECRET or not X_ACCESS_TOKEN or not X_ACCESS_TOKEN_SECRET:
        print("[WARNING] X credentials not configured. Skipping post to X.")
        return None

    print("Posting story thread to X...")
    try:
        import tweepy
        auth = tweepy.OAuth1UserHandler(X_CONSUMER_KEY, X_CONSUMER_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)
        api = tweepy.API(auth)
        x_client = tweepy.Client(
            consumer_key=X_CONSUMER_KEY,
            consumer_secret=X_CONSUMER_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_TOKEN_SECRET
        )

        media_id = None
        if image_path and os.path.exists(image_path):
            try:
                media = api.media_upload(image_path)
                media_id = media.media_id
                print(f"X media uploaded successfully! ID: {media_id}")
            except Exception as ue:
                print(f"X media upload failed: {ue}")

        # Post first tweet (with image if available)
        first_tweet_text = tweets[0]
        if media_id:
            res1 = x_client.create_tweet(text=first_tweet_text, media_ids=[media_id])
        else:
            res1 = x_client.create_tweet(text=first_tweet_text)

        if not res1 or not res1.data:
            print("Failed to post first tweet of thread.")
            return None

        first_id = res1.data["id"]
        print(f"First tweet posted! ID: {first_id}")

        # Post second tweet in reply to the first
        if len(tweets) > 1:
            second_tweet_text = tweets[1]
            res2 = x_client.create_tweet(text=second_tweet_text, in_reply_to_tweet_id=first_id)
            if res2 and res2.data:
                print(f"Second tweet posted! ID: {res2.data['id']}")

        return first_id
    except Exception as e:
        print(f"Error posting to X thread: {e}")
        return None

# ── Post to Facebook ────────────────────────────────────────────────────────
def post_seed_comment(post_id, seed_comment):
    if not seed_comment:
        return
    try:
        data = {"access_token": PAGE_ACCESS_TOKEN, "message": seed_comment}
        resp = requests.post(f"https://graph.facebook.com/v25.0/{post_id}/comments", data=data, timeout=60)
        res = resp.json()
        print(f"Admin Seed Comment: {'OK id=' + res.get('id', '') if 'id' in res else res}")
    except Exception as e:
        print(f"Error posting admin seed comment: {e}")

def post_facebook(img_path, caption, seed_comment=None):
    print("Posting story to Facebook (using two-step publish)...")
    try:
        # Step 1: Upload photo as unpublished
        with open(img_path, "rb") as f:
            resp = requests.post(
                f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
                data={"access_token": PAGE_ACCESS_TOKEN, "published": "false"},
                files={"source": ("story.jpg", f, "image/jpeg")},
                timeout=60,
            )
        upload_result = resp.json()
        if "id" not in upload_result:
            print(f"Photo upload failed: {upload_result}")
            raise SystemExit(1)
        
        photo_id = upload_result["id"]
        print(f"Photo uploaded successfully as unpublished! ID: {photo_id}")
        
        # Step 2: Publish to feed with long caption
        resp2 = requests.post(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/feed",
            data={
                "access_token": PAGE_ACCESS_TOKEN,
                "message": caption,
                "attached_media": json.dumps([{"media_fbid": photo_id}])
            },
            timeout=60,
        )
        feed_result = resp2.json()
        if "id" in feed_result:
            post_id = feed_result["id"]
            print(f"Posted to feed! ID: {post_id}")
            # Step 3: Publish admin seed comment immediately (2/2)
            if seed_comment:
                post_seed_comment(post_id, seed_comment)
            add_comment(post_id, caption=caption)
            return post_id
        else:
            print(f"Feed publishing failed: {feed_result}")
            raise SystemExit(1)
    except Exception as e:
        print(f"Error posting to FB: {e}")
        raise SystemExit(1)

def add_comment(post_id, caption=None):
    try:
        from affiliate_utils import get_all_comments
        comments = get_all_comments(caption=caption)
    except Exception:
        return
    delay = random.uniform(60, 180)
    print(f"Waiting {delay:.0f}s before first affiliate comment...")
    time.sleep(delay)
    for i, msg in enumerate(comments, 1):
        if isinstance(msg, dict):
            data = {"access_token": PAGE_ACCESS_TOKEN, "message": msg["message"]}
            pic  = msg.get("picture_url", "")
            if pic and pic.startswith("http"):
                data["attachment_url"] = pic
        else:
            data = {"access_token": PAGE_ACCESS_TOKEN, "message": str(msg)}
        if not data.get("message", "").strip():
            continue
        r = requests.post(
            f"https://graph.facebook.com/v25.0/{post_id}/comments",
            data=data, timeout=60,
        )
        res = r.json()
        print(f"Comment {i}: {'OK id=' + res['id'] if 'id' in res else res}")
        if i < len(comments):
            time.sleep(random.uniform(30, 90))

# ── Main ─────────────────────────────────────────────────────────────────────
def main(dry_run=False):
    history_list = load_history()
    history_set  = {h for h in history_list}

    post = None
    for _ in range(2):
        post = get_reddit_story(history_set)
        if post:
            break
        print("Retrying story fetch...")
        time.sleep(2)

    if not post:
        print("No suitable story found from Reddit. Using local high-quality dilemma preset...")
        post = {"subreddit": "AITA", "title": "", "body": ""}

    hook, caption, seed_comment, x_thread = translate_story(post.get("subreddit", "AITA"), post.get("title", ""), post.get("body", ""))

    print(f"\nHook (Line 1 Cyan / Line 2 White):\n{hook}")
    print(f"\nCaption (1/2):\n{caption}\n")
    print(f"Seed Comment (2/2):\n{seed_comment}\n")
    if x_thread:
        print(f"X Thread Preview:\n- Tweet 1: {x_thread[0]}\n- Tweet 2: {x_thread[1] if len(x_thread) > 1 else ''}\n")

    if not hook:
        print("Translation failed — no hook generated")
        return False

    img = generate_image(hook)

    if dry_run:
        sample_path = os.path.join(OUTPUT_DIR, "kram_dilemma_sample.jpg")
        import shutil
        shutil.copy(img, sample_path)
        print(f"[DRY RUN] Generated sample card saved to: {sample_path}")
        print("[DRY RUN] Posting skipped.")
        return True

    caption_full = (
        caption
        + f"\n\n#เรื่องจริง #ดราม่า #ชีวิตจริงยิ่งกว่าละคร"
    )
    post_facebook(img, caption_full, seed_comment=seed_comment)
    post_to_x_thread(x_thread, img)
    if post.get("permalink"):
        save_to_history(post["permalink"])
    if post.get("title"):
        save_to_history(reddit_title_key(post["title"]))

    try:
        os.unlink(img)
    except Exception:
        pass
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)

