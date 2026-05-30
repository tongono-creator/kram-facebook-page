# -*- coding: utf-8 -*-
"""story.py — ดึงเรื่องเล่าจาก Reddit แปลไทย โพส Facebook เพจกรามค้าง"""

import os, re, sys, io, json, random, time, requests
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
TEXT_MODELS = ["gemini-2.5-flash", "gemini-3.5-flash"]
OUTPUT_DIR  = "output"
FONT_PATH   = os.path.join(os.path.dirname(__file__), "fonts", "Kanit-Bold.ttf")
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
    for model in TEXT_MODELS:
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
def translate_story(subreddit, title, body):
    """
    คืน (line1, line2, caption)
    line1/line2 = hook สั้นๆ บนรูป
    caption = เล่าเรื่องภาษาไทย สำหรับ Facebook caption
    """
    context = SUB_CONTEXT.get(subreddit, "เรื่องเล่าจากชีวิตจริง")
    prompt = (
        f"นี่คือเรื่องเล่าจริงจาก Reddit r/{subreddit} ({context}):\n\n"
        f"Title: {title}\n\n"
        f"Story: {body}\n\n"
        "งาน: สร้างเนื้อหาภาษาไทยสำหรับ Facebook page ผู้ชายไทย วัย 25-45 ปี\n"
        "เขียนแบบแอดมินชาย บุคลิกสบายๆ (ใช้ ครับ/ผม/พี่)\n\n"
        "ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความอื่นนอก JSON):\n"
        "{\n"
        '  "line1": "พาดหัวบรรทัด 1 ภาษาไทย — ดราม่า กระตุ้นความอยากรู้ — 3-6 คำ",\n'
        '  "line2": "พาดหัวบรรทัด 2 ภาษาไทย — ชวนสงสัย อยากอ่านต่อ — 3-7 คำ",\n'
        '  "caption": "เนื้อหา caption ตาม 5 ชั้นด้านล่าง"\n'
        "}\n\n"
        "=== โครงสร้าง caption 5 ชั้น (เขียนต่อเนื่อง ไม่ต้องใส่หัวข้อ) ===\n\n"
        "ชั้น 1 — HOOK (5 วินาทีแรก):\n"
        "  ประโยคแรกต้องทำให้คนหยุดเลื่อนทันที ด้วยสถานการณ์ที่ช็อก ขัดสามัญสำนึก หรือชวนตัดสินใจ\n"
        "  เช่น: 'ผมโกหกบอสทุกวันมา 8 เดือนครับ ว่าเข้าใจงาน ทั้งที่ไม่รู้เรื่องเลยสักอย่าง'\n\n"
        "ชั้น 2 — EXPAND THE HOOK:\n"
        "  ขยายความ เติมบริบท ทำให้อยากรู้ต่อ — เหตุการณ์เกิดขึ้นได้ยังไง ตอนนั้นรู้สึกยังไง\n\n"
        "ชั้น 3 — CLEAR CONTENT (อ่านจนจบ):\n"
        "  เล่าเนื้อเรื่องหลักให้ครบ ชัดเจน รายละเอียดที่ทำให้เชื่อได้ว่าเกิดขึ้นจริง\n\n"
        "ชั้น 4 — TURNING POINT / CONTRADICTION:\n"
        "  จุดพลิก สิ่งที่ไม่คาดคิด หรือความขัดแย้งที่ทำให้เรื่องน่าสนใจขึ้น\n"
        "  เช่น: 'แต่วันนึงบอสให้ผมนำเสนอหน้าทีมทั้งหมด...'\n\n"
        "ชั้น 5 — STRONG ENDING + COMMENT CALL:\n"
        "  ปิดด้วยประโยคที่จำได้ติดหู + ถามความเห็นตรงๆ ให้คนรู้สึกอยากตอบ\n"
        "  เช่น: 'ถ้าเป็นคุณจะทำยังไงครับ? หรือมีใครเคยอยู่ในสถานการณ์แบบนี้บ้าง?'\n\n"
        "ตัวอย่าง line1 / line2:\n"
        '- "แกล้งทำเป็นเข้าใจงาน" / "มา 8 เดือน จนทำไม่ไหว"\n'
        '- "ทิ้งเพื่อนไว้ที่ปั้ม" / "เพราะเธอทำให้ตกเครื่อง"\n'
        '- "รู้ว่าแฟนแอบชีท" / "แต่แกล้งทำเป็นไม่รู้ 2 ปี"'
    )
    raw = gemini_text(prompt)
    m = re.search(r'\{.*?\}', raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            return data.get("line1", ""), data.get("line2", ""), data.get("caption", "")
        except Exception as e:
            print(f"JSON parse error: {e}\nRaw: {raw[:200]}")
    print(f"translate_story fallback. Raw:\n{raw[:200]}")
    return title[:20], "", ""

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
def generate_image(line1, line2):
    """Dark card 1080x1080 — line1 ฟ้า #00BFFF ใหญ่มาก / line2 ขาว"""
    bkk  = timezone(timedelta(hours=7))
    ts   = datetime.now(bkk).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"story_{ts}.jpg")

    W = H = 1080
    img  = Image.new("RGB", (W, H), (10, 10, 14))   # near-black background
    draw = ImageDraw.Draw(img)

    # subtle dark gradient วาดจากบนลงล่าง
    for y in range(H):
        alpha = int(30 * (y / H))
        draw.line([(0, y), (W, y)], fill=(alpha, alpha, int(alpha * 1.2)))

    PAD      = 80
    max_w    = W - PAD * 2
    LINE_GAP = 24
    COLOR1   = (0, 191, 255)    # #00BFFF ฟ้ากรามค้าง
    COLOR2   = (255, 255, 255)  # ขาว

    # auto-fit: เริ่ม font ใหญ่ลดลงจนพอดี
    font_size = 120
    while font_size >= 40:
        font1 = ImageFont.truetype(FONT_PATH, font_size)
        font2 = ImageFont.truetype(FONT_PATH, max(36, int(font_size * 0.72)))

        lines1 = wrap_text(draw, line1, font1, max_w) if line1 else []
        lines2 = wrap_text(draw, line2, font2, max_w) if line2 else []

        def line_h(text, font):
            bb = draw.textbbox((0, 0), text, font=font)
            return bb[3] - bb[1]

        total_h = sum(line_h(t, font1) + LINE_GAP for t in lines1)
        if lines1 and lines2:
            total_h += LINE_GAP * 2   # separator gap
        total_h += sum(line_h(t, font2) + LINE_GAP for t in lines2)

        width_ok = (
            all(draw.textbbox((0, 0), t, font=font1)[2] <= max_w for t in lines1) and
            all(draw.textbbox((0, 0), t, font=font2)[2] <= max_w for t in lines2)
        )
        if total_h <= H - PAD * 2 and width_ok:
            break
        font_size -= 4

    print(f"Story image font size: {font_size}")

    # วาด — centering ทั้งกลุ่ม
    y = (H - total_h) // 2

    def draw_outlined(text, font, color, y_pos):
        bb = draw.textbbox((0, 0), text, font=font)
        w  = bb[2] - bb[0]
        x  = (W - w) // 2
        dy = y_pos - bb[1]
        # 8-direction outline สีดำ
        for dx, ddy in [(-3,-3),(-3,0),(-3,3),(0,-3),(0,3),(3,-3),(3,0),(3,3)]:
            draw.text((x+dx, dy+ddy), text, font=font, fill=(0, 0, 0))
        draw.text((x, dy), text, font=font, fill=color)
        return bb[3] - bb[1]   # คืนความสูงจริง

    for text in lines1:
        h = draw_outlined(text, font1, COLOR1, y)
        y += h + LINE_GAP

    if lines1 and lines2:
        y += LINE_GAP   # extra gap ระหว่าง 2 บรรทัด

    for text in lines2:
        h = draw_outlined(text, font2, COLOR2, y)
        y += h + LINE_GAP

    # watermark เล็กๆ ด้านล่าง
    try:
        wm_font = ImageFont.truetype(FONT_PATH, 28)
        wm_text = "📖 เรื่องจริงจาก Reddit"
        bb = draw.textbbox((0, 0), wm_text, font=wm_font)
        draw.text(((W - (bb[2]-bb[0])) // 2, H - 60), wm_text, font=wm_font, fill=(80, 80, 80))
    except Exception:
        pass

    img.save(path, "JPEG", quality=92)
    print(f"Story image saved: {path}")
    return path

# ── Post to Facebook ────────────────────────────────────────────────────────
def post_facebook(img_path, caption):
    print("Posting story to Facebook...")
    with open(img_path, "rb") as f:
        resp = requests.post(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
            data={"access_token": PAGE_ACCESS_TOKEN, "caption": caption, "published": "true"},
            files={"source": ("story.jpg", f, "image/jpeg")},
            timeout=60,
        )
    result = resp.json()
    if "id" in result:
        post_id = result.get("post_id") or result["id"]
        print(f"Posted! ID: {post_id}")
        add_comment(post_id)
        return post_id
    else:
        print(f"FB Error: {result}")
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

    line1, line2, caption = translate_story(post["subreddit"], post["title"], post["body"])

    print(f"\nHook: [{line1}] / [{line2}]")
    print(f"Caption preview:\n{caption[:300]}\n")

    if not line1:
        print("Translation failed — no hook generated")
        raise SystemExit(1)

    if args.dry_run:
        print("[DRY RUN] Image and post skipped.")
        raise SystemExit(0)

    img = generate_image(line1, line2)
    caption_full = (
        caption
        + f"\n\n#เรื่องจริง #ดราม่า #ชีวิตจริงยิ่งกว่าละคร"
    )
    post_facebook(img, caption_full)
    save_to_history(post["permalink"])

    try:
        os.unlink(img)
    except Exception:
        pass
