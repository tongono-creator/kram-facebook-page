import os
import re
import random
import time
import requests
import tempfile
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

# ── Config ───────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ["KRAM_PAGE_ACCESS_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "AIzaSyCi6AbETW4XTjJpcbRxj2oL3ftEWRbv_xI")

client      = genai.Client(api_key=GEMINI_API_KEY)
TEXT_MODELS = ["gemini-2.5-flash", "gemini-3.5-flash"]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KramBot/1.0; +github)"}

# ── Subreddits ────────────────────────────────────────────────────────
SUBREDDITS = [
    "aww",
    "AnimalsBeingBros",
    "rarepuppers",
    "WhatsWrongWithYourCat",
    "AnimalsBeingDerps",
    "NatureIsFuckingLit",
    "interestingasfuck",
    "nextfuckinglevel",
    "Unexpected",
    "oddlyterrifying",
    "mildlyinteresting",
]

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


# ── Reddit ────────────────────────────────────────────────────────────
def get_reddit_post():
    subreddit = random.choice(SUBREDDITS)
    # RSS feed — ไม่โดน block เหมือน JSON API
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        image_posts = []
        for entry in entries:
            title   = entry.findtext("atom:title", "", ns).strip()
            content = entry.findtext("atom:content", "", ns)
            link_el = entry.find("atom:link", ns)
            post_link = link_el.get("href", "") if link_el is not None else ""

            # ดึง image URL จาก content HTML
            img_urls = re.findall(r'https?://[^\s"<>]+\.(?:jpg|jpeg|png|gif|webp)', content or "")
            # กรอง reddit preview / thumbnail ออก เอาแค่ i.redd.it หรือ imgur
            good_imgs = [u for u in img_urls if "i.redd.it" in u or "imgur.com" in u]

            if good_imgs and title:
                image_posts.append({
                    "title":     title,
                    "url":       good_imgs[0],
                    "subreddit": subreddit,
                })

        if not image_posts:
            print(f"[{subreddit}] no image posts in RSS")
            return None

        post = random.choice(image_posts[:10])
        print(f"[{subreddit}] picked: {post['title'][:60]}")
        return post

    except Exception as e:
        print(f"Reddit error ({subreddit}): {e}")
        return None


# ── Gemini ────────────────────────────────────────────────────────────
def analyze_image(img_path):
    """Vision วิเคราะห์รูปว่าเห็นอะไร — สัตว์/ธรรมชาติ"""
    with open(img_path, "rb") as f:
        img_data = f.read()
    prompt = (
        "ดูรูปนี้แล้วอธิบายสั้นๆ ภาษาไทย ว่าเห็นอะไรในรูป 1-2 ประโยค "
        "เน้นสัตว์หรือธรรมชาติที่เห็น ถ้าไม่มีสัตว์หรือธรรมชาติเลย ตอบว่า 'ไม่เกี่ยว'"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg"),
                    types.Part.from_text(text=prompt),
                ],
            )
            result = resp.text.strip()
            print(f"Vision: {result}")
            return result
        except Exception as e:
            print(f"[{model}] vision failed: {e}")
    return None


def make_caption(image_desc, subreddit):
    prompt = (
        f"รูปจาก r/{subreddit} เห็น: {image_desc}\n\n"
        "เขียน Facebook caption ภาษาไทย สำหรับเพจข่าวสัตว์/ธรรมชาติ ชื่อ 'กรามค้าง'\n"
        "บรรทัด 1: หัวข้อสั้น กระชับ ทำให้คนอยากดู ไม่เกิน 50 ตัวอักษร\n"
        "บรรทัด 2: อธิบายสั้นๆ 1-2 ประโยค ตรงกับรูปที่เห็น\n"
        "บรรทัด 3: hashtag 3-5 อัน\n"
        "ห้ามใช้ ** markdown ตอบแค่ caption เลย"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return clean_text(resp.text.strip())
        except Exception as e:
            print(f"[{model}] caption failed: {e}")
    return clean_text(image_desc)


def clean_text(text):
    text = text.replace("\\n", "\n")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"__(.+?)__",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    text = re.sub(r"^#+\s*",        "",    text, flags=re.MULTILINE)
    return text.strip()


# ── Facebook ──────────────────────────────────────────────────────────
def download_image(image_url):
    MAX_BYTES = 4 * 1024 * 1024
    try:
        img_resp = requests.get(image_url, headers=HEADERS, timeout=15, stream=True)
        img_resp.raise_for_status()
        content_length = int(img_resp.headers.get("content-length", 0))
        if content_length > MAX_BYTES:
            print(f"Image too large: {content_length} bytes")
            return None
        data = b""
        for chunk in img_resp.iter_content(chunk_size=65536):
            data += chunk
            if len(data) > MAX_BYTES:
                print("Image too large (streaming)")
                return None
    except Exception as e:
        print(f"Image download failed: {e}")
        return None

    suffix = ".jpg"
    for ext in IMAGE_EXTS:
        if image_url.lower().split("?")[0].endswith(ext):
            suffix = ext
            break
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def post_photo(caption, img_path):
    try:
        api_url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/photos"
        with open(img_path, "rb") as f:
            resp = requests.post(
                api_url,
                data={
                    "message":      caption,
                    "access_token": PAGE_ACCESS_TOKEN,
                },
                files={"source": ("photo" + suffix, f, "image/jpeg")},
                timeout=60,
            )
        result = resp.json()
        if "id" in result:
            post_id = result.get("post_id") or result["id"]
            print(f"Posted: {post_id}")
            add_comment(post_id)
            return True
        else:
            print(f"Post failed: {result}")
            return False
    except Exception as e:
        print(f"Facebook error: {e}")
        return False
    finally:
        if img_path and os.path.exists(img_path):
            os.unlink(img_path)


# ── Comment ───────────────────────────────────────────────────────────
def add_comment(post_id):
    from affiliate_utils import get_all_comments
    comments = get_all_comments()
    delay0 = random.uniform(60, 180)
    print(f"Waiting {delay0:.0f}s before first comment...")
    time.sleep(delay0)
    for i, msg in enumerate(comments, 1):
        if isinstance(msg, dict):
            data = {"access_token": PAGE_ACCESS_TOKEN, "message": msg["message"]}
            if msg.get("picture_url"):
                data["attachment_url"] = msg["picture_url"]
        else:
            data = {"access_token": PAGE_ACCESS_TOKEN, "message": msg}
        resp = requests.post(
            f"https://graph.facebook.com/v21.0/{post_id}/comments",
            data=data,
        )
        result = resp.json()
        if "id" in result:
            print(f"Comment {i} added: {result['id']}")
        else:
            print(f"Comment {i} error: {result}")
        if i < len(comments):
            time.sleep(random.uniform(30, 90))


# ── Main ──────────────────────────────────────────────────────────────
def main():
    print("=== กรามค้าง Bot ===")

    post = None
    for attempt in range(5):
        post = get_reddit_post()
        if post:
            break
        print(f"Retry {attempt + 1}/5...")

    if not post:
        print("No suitable post found after 5 attempts")
        return

    # Download รูปก่อน → Vision → caption
    img_path = download_image(post["url"])
    if not img_path:
        print("Image download failed")
        return

    image_desc = analyze_image(img_path)
    if not image_desc or "ไม่เกี่ยว" in image_desc:
        print(f"Vision: not relevant, using Reddit title as fallback")
        image_desc = post["title"]

    caption = make_caption(image_desc, post["subreddit"])
    caption += f"\n📷 via r/{post['subreddit']}"
    print(f"Caption:\n{caption}\n")

    success = post_photo(caption, img_path)
    if not success:
        print("FAILED")


if __name__ == "__main__":
    main()
