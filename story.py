# -*- coding: utf-8 -*-
"""story.py — ดึงเรื่องเล่าจาก Reddit แปลไทย โพส Facebook เพจกรามค้าง"""

import os, re, sys, io, json, random, time, requests, hashlib
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

# ── Config ──────────────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ.get("KRAM_PAGE_ACCESS_TOKEN", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "") or "DUMMY_KEY"

client      = genai.Client(api_key=GEMINI_API_KEY, http_options=HttpOptions(timeout=300000))
TEXT_MODELS       = ["gemini-1.5-flash", "gemini-1.5-flash"]
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
            import time; time.sleep(2)
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

def translate_story(subreddit, title, body):
    """
    คืน (hook, caption, x_thread)
    hook = พาดหัวบนรูป — 1-3 บรรทัด คั่นด้วย \n
    caption = เล่าเรื่องภาษาไทย 5 ชั้น สำหรับ Facebook caption
    x_thread = ข้อความโพสต์ใน X 2 ทวีต
    """
    context = SUB_CONTEXT.get(subreddit, "เรื่องเล่าจากชีวิตจริง")
    prompt = (
        f"นี่คือเรื่องเล่าจริงจาก Reddit r/{subreddit} ({context}):\n\n"
        f"Title: {title}\n\n"
        f"Story: {body}\n\n"
        "งาน: แปลงเรื่องนี้มาทำเป็น 'เรื่องเล่าให้ตัดสิน' (Stories for Judgment) ภาษาไทยสำหรับ Facebook page ผู้ชายไทย วัย 25-45 ปี\n"
        "เขียนด้วยบุคลิกแอดมินผู้ชาย สบายๆ โทนจริงจังและน่าสนใจ (ใช้หางเสียงครับ/ผม/พี่)\n\n"
        "ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความอื่นนอก JSON):\n"
        '{\n'
        '  "core_issue": "สรุปประเด็นหลักของเรื่องเป็นประโยคภาษาไทยธรรมดาและสมบูรณ์ 1 ประโยค (ระบุชัดเจนว่า ใคร ทำอะไร กับใคร/ปัญหาคืออะไร เช่น \'บริษัทบอกว่าไม่บังคับ แต่กดดันให้ผู้สมัครสัมภาษณ์งานกับ AI ก่อนเจอ HR\')",\n'
        '  "hook": "พาดหัวสั้นๆ กระชับบนรูปภาพ คั่นบรรทัดด้วย \\\\n (ย่อ/สรุปจาก core_issue โดยอ่านแล้วต้องรู้ทันทีว่า ใคร ทำอะไร ปัญหาคืออะไร และห้ามใช้วลีที่ไม่ครบความหมาย ห้ามใช้ประโยคไม่มีประธาน และห้ามใช้คำว่า \'ที่บอก...\' เด็ดขาด)",\n'
        '  "caption": "caption 5 ชั้น เล่าเป็นภาษาพูดธรรมชาติที่ลื่นไหล",\n'
        '  "x_thread": [\n'
        '    "ข้อความโพสต์ที่ 1 ของ thread ใน X (สรุปเนื้อเรื่องส่วนที่ 1/คำถามชวนคิดเพื่อดึงดูดความสนใจ, ยาวไม่เกิน 250 ตัวอักษร, จบด้วย \'1/2\')",\n'
        '    "ข้อความโพสต์ที่ 2 ของ thread ใน X (สรุปคำเฉลย/จุดพีค/การชวนตัดสินคดี, ยาวไม่เกิน 250 ตัวอักษร, จบด้วย \'2/2\')"\n'
        '  ]\n'
        '}\n\n'

        "=== วิธีสร้าง core_issue และ hook (ทำตามลำดับ) ===\n"
        "STEP 1: เขียน core_issue = ประโยคไทยสมบูรณ์ 1 ประโยค โครงสร้าง [ประธาน] + [ทำอะไร] + [ปัญหา]\n"
        "STEP 2: ย่อเป็น hook โดยยึดกติกา 3 ข้อนี้เท่านั้น:\n"
        "  (ก) บรรทัดแรกของ hook ต้องเริ่มด้วยประธานที่จับต้องได้ — เลือกจาก: บริษัท / หัวหน้า / เมีย / แฟน / เพื่อน / ผม / ลูกค้า ฯลฯ\n"
        "  (ข) บรรทัดสุดท้ายเป็นคำถามชวนตัดสิน ลงท้าย 'ไหมครับ?' หรือ 'ดีไหมครับ?'\n"
        "  (ค) ยาว 2-3 บรรทัด คั่นด้วย \\n อ่านปุ๊บรู้ทันทีว่าใครทำอะไรเกิดปัญหาอะไร\n\n"
        "เทียบให้เห็นชัด ❌ผิด vs ✅ถูก (เรื่องสัมภาษณ์ AI):\n"
        "  ❌ 'สมัครงานเจอ AI สัมภาษณ์\\nที่บอก ไม่บังคับ มันคืออะไร?\\nใครจะไปยอมทำกันครับ!'\n"
        "     << ผิดเพราะ: ไม่มีประธาน, 'ที่บอก...' ลอย, อ่านแล้วงงว่าใครทำอะไร >>\n"
        "  ✅ 'บริษัทให้ AI\\nสัมภาษณ์งานแทนคน\\nแบบนี้พี่ๆ รับได้ไหมครับ?'\n"
        "     << ถูกเพราะ: ขึ้นต้น 'บริษัท' (ประธานชัด), เล่าครบ, ปิดด้วยคำถาม >>\n\n"
        "ตัวอย่าง hook ที่ดีอีก:\n"
        "  ✅ 'หัวหน้าสั่งให้ผม\\nทำงานเสาร์อาทิตย์ฟรี\\nผมควรปฏิเสธไหมครับ?'\n"
        "  ✅ 'เมียขอยืมเงินแสนแรก\\nที่ผมเก็บมาทั้งชีวิต\\nควรให้ยืมดีไหมครับ?'\n\n"

        "=== กฎการสร้าง x_thread ===\n"
        "1. x_thread ต้องประกอบด้วยข้อความ 2 ข้อความ (โพสต์ที่ 1 และ 2) เพื่อนำไปโพสต์ต่อกันเป็น Thread บน X (Twitter)\n"
        "2. โพสต์ที่ 1: ตั้งคำถามชวนคิดหรือเล่าเรื่องเกริ่นตอนต้นให้ชวนติดตาม โดยให้มีอารมณ์ดราม่าและชวนตัดสินเหมือน Facebook caption และแนบภาพเสมอ จบท้ายด้วย '1/2'\n"
        "3. โพสต์ที่ 2: เล่าจุดจบหรือสรุปผลและยิงคำถามชวนแสดงความคิดเห็นแบบเดียวกับ Facebook caption และจบท้ายด้วย '2/2'\n"
        "4. ทั้งสองโพสต์ต้องจำกัดความยาวไม่เกิน 250 ตัวอักษรภาษาไทยต่อโพสต์ (เพื่อไม่ให้เกินขีดจำกัด 280 ตัวอักษรของ X)\n"
        "5. เขียนด้วยภาษาพูดสบายๆ โทนจริงจังและน่าสนใจ (ใช้หางเสียงครับ/ผม/พี่ เหมือนเดิม)\n\n"

        "=== caption 5 ชั้น (เขียนต่อเนื่องเป็นความเรียงปกติ ห้ามใส่หัวข้อ ห้ามใส่หมายเลข ห้ามมี bullet points เด็ดขาด) ===\n"
        "ชั้น 1 — HOOK: ประโยคแรกเปิดมาเพื่อเรียกหาการตัดสินคดี/ดราม่าความขัดแย้งของเรื่องทันที (หลีกเลี่ยงประโยคซ้ำซ้อนไม่เป็นธรรมชาติ ให้เขียนเป็นภาษาพูดปกติ เช่น 'มีเรื่องอยากให้พี่ๆ ช่วยตัดสินหน่อยครับ...' หรือ 'เดี๋ยวนี้บางบริษัทเริ่มให้ผู้สมัครตอบคำถามกับระบบ AI ก่อนเจอคนจริง บางที่บอกว่าไม่บังคับ แต่คนสมัครก็อดคิดไม่ได้ว่า ถ้าไม่ทำจะเสียเปรียบไหม')\n"
        "ชั้น 2 — EXPAND: ขยายบริบทสั้นๆ ยั่วให้อยากรู้เนื้อเรื่อง\n"
        "ชั้น 3 — CLEAR CONTENT: เล่าเนื้อเรื่องหลักเรียงลำดับ ชัดเจน ไหลลื่น ภาษาคนธรรมชาติ\n"
        "ชั้น 4 — TURNING POINT: จุดพีคที่เป็นข้อขัดแย้ง\n"
        "ชั้น 5 — JUDGMENT CALL: สรุปแล้วปิดกระแทกด้วยคำถามชวนตัดสินคดีตรงๆ ชวนแชร์ความคิดเห็นหรือบอกทีมฝั่งไหน (เช่น 'พี่ๆ ว่างานนี้ผมผิดไหมครับ?', 'ถ้าเป็นพี่ๆ จะยอมสัมภาษณ์กับ AI ไหมครับ หรือมองว่าการรับคนควรมีมนุษย์คุยกับมนุษย์ก่อน?')"
    )
    raw = gemini_text(prompt)
    hook, caption, core_issue, x_thread = "", "", "", []
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
                hook       = data.get("hook", "").replace("\\n", "\n")
                caption    = data.get("caption", "")
                core_issue = data.get("core_issue", "")
                x_thread   = data.get("x_thread", [])
            except Exception as e:
                print(f"JSON parse error: {e}")

    # Validation: ถ้า hook ไม่เคลียร์ (ไม่มีประธาน/วลีลอย/ไม่มีคำถาม) สั่งสร้างใหม่จาก core_issue 1 รอบ
    if hook and core_issue and not is_hook_clear(hook):
        print(f"Hook ไม่ผ่านเกณฑ์: {hook!r} — regenerate จาก core_issue")
        fix_prompt = (
            f"ประเด็น: {core_issue}\n\n"
            "เขียน 'พาดหัวบนรูป' ภาษาไทย 2-3 บรรทัด คั่นบรรทัดด้วย \\n ตามกติกา:\n"
            "1. บรรทัดแรกต้องขึ้นต้นด้วยประธานชัดเจน (บริษัท/หัวหน้า/เมีย/แฟน/เพื่อน/ผม/ลูกค้า)\n"
            "2. บรรทัดสุดท้ายเป็นคำถามชวนตัดสิน ลงท้าย 'ไหมครับ?'\n"
            "3. ห้ามวลีลอย เช่น 'ที่บอก...' หรือ 'มันคืออะไร'\n"
            "ตอบเฉพาะข้อความพาดหัว ไม่ต้องมีอย่างอื่น\n"
            "ตัวอย่าง: บริษัทให้ AI\\nสัมภาษณ์งานแทนคน\\nแบบนี้พี่ๆ รับได้ไหมครับ?"
        )
        fixed = gemini_text(fix_prompt)
        if fixed:
            fixed = fixed.strip().strip('"').replace("\\n", "\n")
            if is_hook_clear(fixed):
                print(f"Hook ใหม่ผ่าน: {fixed!r}")
                hook = fixed

    # Fallback to direct translation if JSON parsing failed or output has no Thai
    if not hook or not caption or not contains_thai(hook) or not contains_thai(caption):
        print("JSON translation failed or missing Thai. Trying direct translation fallback...")
        fallback_prompt = (
            f"แปลเรื่องเล่าจาก Reddit r/{subreddit} นี้เป็นภาษาไทย:\n"
            f"Title: {title}\n"
            f"Body: {body}\n\n"
            "เขียนคำตอบออกมา 2 บรรทัด คั่นด้วยเครื่องหมาย | :\n"
            "บรรทัดที่ 1: พาดหัวภาษาไทยสั้นๆ กวนๆ น่าดึงดูดใจ สำหรับใส่บนรูปภาพ (ยาวไม่เกิน 10 คำ)\n"
            "บรรทัดที่ 2: เนื้อหาคำยายเรื่องเล่าฉบับเต็มภาษาไทยสำหรับแอดมินเพจวัยรุ่น/ผู้ชาย ลงท้ายด้วยครับ/ผม/พี่ และจบด้วยคำถามชวนแสดงความเห็น\n"
            "ห้ามใช้ JSON หรืออธิบายเพิ่มเติม ตอบเฉพาะข้อมูลที่ระบุในฟอร์แมต: พาดหัว | คำบรรยาย"
        )
        fallback_raw = gemini_text(fallback_prompt)
        if fallback_raw and "|" in fallback_raw:
            try:
                parts = fallback_raw.split("|", 1)
                hook = parts[0].strip()
                caption = parts[1].strip()
                print(f"Fallback direct translation success! Hook: {hook[:30]}")
            except Exception as fe:
                print(f"Fallback split error: {fe}")

    # Fallback to predefined local Thai stories if all AI methods fail
    if not hook or not caption or not contains_thai(hook) or not contains_thai(caption):
        print("All AI translation methods failed or missing Thai. Using local fallback database.")
        fallbacks = [
            {
                "hook": "แฟนทำแบบนี้..\nผมควรทนต่อไหมครับ?",
                "caption": "ผมมีเรื่องอยากระบายและขอความเห็นจากทุกคนหน่อยครับ คือเรื่องมีอยู่ว่าแฟนผมมักจะติดต่อกับแฟนเก่าของเธออยู่เรื่อยๆ โดยที่เธออ้างว่าเป็นแค่เพื่อนร่วมงานกัน แต่ล่าสุดผมดันไปเห็นแชทที่พวกเขานัดเจอกันนอกรอบแบบไม่บอกผม ผมรู้สึกสับสนมากครับว่าคิดมากไปเองหรือควรคุยตรงๆ ดี ใครเคยเจอเรื่องแนวนี้ช่วยแนะนำทีครับ"
            },
            {
                "hook": "โกหกหัวหน้างาน..\nจนปวดหัวเอง",
                "caption": "คือเรื่องมันเริ่มจากผมรับงานโปรเจกต์นึงมา แล้วตอนประชุมผมดันบอกหัวหน้าไปว่าเข้าใจระบบทั้งหมดและทำคนเดียวได้สบายมาก ทั้งที่จริงๆ ผมไม่เข้าใจเลยครับ ตอนนี้เดดไลน์เหลืออีกแค่ 3 วัน แต่งานยังไม่คืบหน้าเลย ผมเครียดมากและกลัวหัวหน้าด่าจนแทบไม่ได้นอนเลยครับ ใครเคยตกอยู่ในสถานการณ์แบบนี้บ้างไหมครับ มาแชร์วิธีแก้ปัญหากันหน่อยครับ"
            },
            {
                "hook": "ทิ้งเพื่อนที่ปั๊มน้ำมัน..\nผมผิดไหม?",
                "caption": "ผมอยากถามทุกคนว่าผมใจดำเกินไปไหมครับ คือวันนั้นพวกเรานัดกันจะไปขึ้นเครื่องบินไปเที่ยวต่างจังหวัดกัน แล้วเพื่อนผมคนนึงมัวแต่นอนตื่นสายและทำตัวชิลมากๆ ตอนแวะปั๊มเธอก็เดินหายไปซื้อของโดยไม่รักษาเวลา จนผมตัดสินใจให้คนรถขับออกไปขึ้นเครื่องก่อนเลยโดยไม่รอเธอ ทำให้เธอตกเครื่องและโกรธผมมากครับ คิดว่าผมทำถูกแล้วหรือผิดกันแน่ ลองแสดงความเห็นมาคุยกันหน่อยครับ"
            }
        ]
        chosen = random.choice(fallbacks)
        hook = chosen["hook"]
        caption = chosen["caption"]

    # Ensure x_thread is populated
    if not x_thread or len(x_thread) < 2:
        # Split the caption into two parts for thread
        lines = [l.strip() for l in caption.split("\n") if l.strip()]
        half = len(lines) // 2
        p1 = " ".join(lines[:half])[:250] + " 1/2"
        p2 = " ".join(lines[half:])[:250] + " 2/2"
        x_thread = [p1, p2]

    # Clean thread elements just to be safe
    x_thread = [t.strip() for t in x_thread]

    return hook, caption, x_thread

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


# ── Generate image ───────────────────────────────────────────────────────────
def generate_image(hook):
    """Dark card 1080x1080 — hook text ขาว font size เดียว auto-fit ให้ใหญ่สุด"""
    bkk  = timezone(timedelta(hours=7))
    ts   = datetime.now(bkk).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"story_{ts}.jpg")

    W = H = 1080
    img  = Image.new("RGB", (W, H), (0, 0, 0))   # pure black
    draw = ImageDraw.Draw(img)

    PAD      = 80
    max_w    = W - PAD * 2   # 920px
    LINE_GAP = 28
    COLOR    = (255, 255, 255)

    # แยก hook เป็นบรรทัด (ตาม \n ที่ Gemini กำหนด)
    raw_lines = [l.strip() for l in hook.strip().split("\n") if l.strip()]

    # auto-fit: เริ่ม 120px ลดลงทีละ 4 จนพอดี
    font_size = 120
    best_font = None
    best_lines = []
    while font_size >= 36:
        font = ImageFont.truetype(FONT_PATH, font_size)
        # wrap แต่ละบรรทัดถ้ายาวเกิน max_w
        wrapped = []
        for l in raw_lines:
            wrapped.extend(wrap_text(draw, l, font, max_w))

        def lh(text):
            bb = draw.textbbox((0, 0), text, font=font)
            return bb[3] - bb[1]

        total_h  = sum(lh(t) + LINE_GAP for t in wrapped)
        width_ok = all(draw.textbbox((0, 0), t, font=font)[2] <= max_w for t in wrapped)

        if total_h <= H - PAD * 2 and width_ok:
            best_font  = font
            best_lines = wrapped
            break
        font_size -= 4

    if not best_font:
        best_font  = ImageFont.truetype(FONT_PATH, 36)
        best_lines = []
        for l in raw_lines:
            best_lines.extend(wrap_text(draw, l, best_font, max_w))

    print(f"Story image font size: {font_size} | lines: {len(best_lines)}")

    # คำนวณ total_h จริงก่อนวาด
    def lh(text):
        bb = draw.textbbox((0, 0), text, font=best_font)
        return bb[3] - bb[1]
    total_h = sum(lh(t) + LINE_GAP for t in best_lines)

    y = (H - total_h) // 2

    for text in best_lines:
        bb = draw.textbbox((0, 0), text, font=best_font)
        w  = bb[2] - bb[0]
        x  = (W - w) // 2
        dy = y - bb[1]
        # Native stroke in PIL for clean text outline
        draw.text((x, dy), text, font=best_font, fill=COLOR, stroke_width=3, stroke_fill=(0, 0, 0))
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
def post_facebook(img_path, caption):
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
            add_comment(post_id)
            return post_id
        else:
            print(f"Feed publishing failed: {feed_result}")
            raise SystemExit(1)
    except Exception as e:
        print(f"Error posting to FB: {e}")
        raise SystemExit(1)

def add_comment(post_id):
    try:
        from affiliate_utils import get_all_comments
        comments = get_all_comments()
    except Exception:
        return
    delay = random.uniform(60, 180)
    print(f"Waiting {delay:.0f}s before first comment...")
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
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    history_list = load_history()
    history_set  = {h for h in history_list}

    post = None
    for _ in range(5):
        post = get_reddit_story(history_set)
        if post:
            break
        print("Retrying story fetch...")
        time.sleep(3)

    if not post:
        print("No suitable story found after 5 attempts")
        raise SystemExit(1)

    hook, caption, x_thread = translate_story(post["subreddit"], post["title"], post["body"])

    print(f"\nHook:\n{hook}")
    print(f"\nCaption preview:\n{caption[:300]}\n")
    if x_thread:
        print(f"X Thread Preview:\n- Tweet 1: {x_thread[0]}\n- Tweet 2: {x_thread[1] if len(x_thread) > 1 else ''}\n")

    if not hook:
        print("Translation failed — no hook generated")
        raise SystemExit(1)

    if args.dry_run:
        print("[DRY RUN] Image and post skipped.")
        raise SystemExit(0)

    img = generate_image(hook)
    caption_full = (
        caption
        + f"\n\n#เรื่องจริง #ดราม่า #ชีวิตจริงยิ่งกว่าละคร"
    )
    post_facebook(img, caption_full)
    post_to_x_thread(x_thread, img)
    save_to_history(post["permalink"])
    save_to_history(reddit_title_key(post["title"]))

    try:
        os.unlink(img)
    except Exception:
        pass
