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
def contains_thai(text):
    if not text:
        return False
    return any('\u0e00' <= char <= '\u0e7f' for char in text)

def translate_story(subreddit, title, body):
    """
    คืน (hook, caption)
    hook = พาดหัวบนรูป — 1-3 บรรทัด คั่นด้วย \n
    caption = เล่าเรื่องภาษาไทย 5 ชั้น สำหรับ Facebook caption
    """
    context = SUB_CONTEXT.get(subreddit, "เรื่องเล่าจากชีวิตจริง")
    prompt = (
        f"นี่คือเรื่องเล่าจริงจาก Reddit r/{subreddit} ({context}):\n\n"
        f"Title: {title}\n\n"
        f"Story: {body}\n\n"
        "งาน: แปลงเรื่องนี้มาทำเป็น 'เรื่องเล่าให้ตัดสิน' (Stories for Judgment) ภาษาไทยสำหรับ Facebook page ผู้ชายไทย วัย 25-45 ปี\n"
        "เขียนด้วยบุคลิกแอดมินผู้ชาย สบายๆ โทนจริงจังและน่าสนใจ (ใช้หางเสียงครับ/ผม/พี่)\n\n"
        "ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความอื่นนอก JSON):\n"
        '{"hook": "พาดหัวบนรูป", "caption": "caption 5 ชั้น"}\n\n'

        "=== กฎ hook ===\n"
        "hook คือข้อความพาดหัวที่จะแสดงบนรูป — ต้องเป็นคำถามหรือการเกริ่นที่ชวนตัดสินหรือชวนเลือกฝั่งโดยตรง\n"
        "เลือกความยาวที่เหมาะกับเนื้อเรื่อง: 1, 2 หรือ 3 บรรทัดก็ได้ (คั่นด้วย \\n)\n"
        "กฎ: ทุกบรรทัดต้องเป็นเรื่องเดียวกัน อ่านต่อเนื่อง — ห้ามมีป้ายกำกับ\n"
        "ตัวอย่าง: 'ผมผิดไหมที่...\\nทิ้งเพื่อนไว้กลางทางครับ', 'เรื่องนี้ใครผิด?\\nเมื่อเมียขอยืมเงินเก็บแสนแรก'\n\n"

        "=== caption 5 ชั้น (เขียนต่อเนื่องเป็นความเรียงปกติ ห้ามใส่หัวข้อ ห้ามใส่หมายเลข ห้ามมี bullet points เด็ดขาด) ===\n\n"
        "ชั้น 1 — HOOK: ประโยคแรกเปิดมาเพื่อเรียกหาการตัดสินคดี/ดราม่าความขัดแย้งของเรื่องทันที (เช่น 'มีเรื่องอยากให้พี่ๆ ช่วยตัดสินหน่อยครับ...')\n"
        "ชั้น 2 — EXPAND: ขยายบริบทสั้นๆ ยั่วให้อยากรู้เนื้อเรื่อง\n"
        "ชั้น 3 — CLEAR CONTENT: เล่าเนื้อเรื่องหลักเรียงลำดับ ชัดเจน ไหลลื่น\n"
        "ชั้น 4 — TURNING POINT: จุดพีคที่เป็นข้อขัดแย้ง\n"
        "ชั้น 5 — JUDGMENT CALL: สรุปแล้วปิดกระแทกด้วยคำถามชวนตัดสินคดีตรงๆ ชวนแชร์ความคิดเห็นหรือบอกทีมฝั่งไหน (เช่น 'พี่ๆ ว่างานนี้ผมผิดไหมครับ?', 'เป็นพี่ๆ จะยอมไหมครับ?', 'เคสนี้คิดว่าใครผิดครับ?')"
    )
    raw = gemini_text(prompt)
    hook, caption = "", ""
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
                hook    = data.get("hook", "").replace("\\n", "\n")
                caption = data.get("caption", "")
            except Exception as e:
                print(f"JSON parse error: {e}")

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

    return hook, caption

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
        # 8-direction outline
        for dx, ddy in [(-3,-3),(-3,0),(-3,3),(0,-3),(0,3),(3,-3),(3,0),(3,3)]:
            draw.text((x+dx, dy+ddy), text, font=best_font, fill=(0, 0, 0))
        draw.text((x, dy), text, font=best_font, fill=COLOR)
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

    hook, caption = translate_story(post["subreddit"], post["title"], post["body"])

    print(f"\nHook:\n{hook}")
    print(f"\nCaption preview:\n{caption[:300]}\n")

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
    save_to_history(post["permalink"])

    try:
        os.unlink(img)
    except Exception:
        pass
