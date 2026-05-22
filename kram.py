import os
import re
import random
import requests
import tempfile
import xml.etree.ElementTree as ET
from google import genai

# ── Config ───────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ["KRAM_PAGE_ACCESS_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "AIzaSyCi6AbETW4XTjJpcbRxj2oL3ftEWRbv_xI")

client      = genai.Client(api_key=GEMINI_API_KEY)
TEXT_MODELS = ["gemini-1.5-flash", "gemini-2.5-flash-preview-05-20"]

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
def make_caption(title, subreddit):
    prompt = (
        f"Reddit post จาก r/{subreddit}:\n\"{title}\"\n\n"
        "เขียน Facebook caption ภาษาไทย สำหรับเพจข่าวสัตว์/ธรรมชาติ ชื่อ 'กรามค้าง'\n"
        "รูปแบบ:\n"
        "บรรทัด 1: หัวข้อสั้น กระชับ ทำให้คนอยากดู ไม่เกิน 50 ตัวอักษร\n"
        "บรรทัด 2: ขึ้นบรรทัดใหม่ อธิบายสั้นๆ 1-2 ประโยค\n"
        "บรรทัด 3: ขึ้นบรรทัดใหม่ hashtag 3-5 อัน\n"
        "ห้ามใช้ ** markdown ตอบแค่ caption เลย ไม่มีคำอธิบายเพิ่ม"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return clean_text(resp.text.strip())
        except Exception as e:
            print(f"[{model}] caption failed: {e}")
    return clean_text(title)


def clean_text(text):
    text = text.replace("\\n", "\n")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"__(.+?)__",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    text = re.sub(r"^#+\s*",        "",    text, flags=re.MULTILINE)
    return text.strip()


# ── Facebook ──────────────────────────────────────────────────────────
def post_photo(caption, image_url):
    # ใช้ url parameter — Facebook download รูปเอง ไม่ต้อง upload ไฟล์
    try:
        api_url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/photos"
        resp = requests.post(
            api_url,
            data={
                "message":      caption,
                "url":          image_url,
                "access_token": PAGE_ACCESS_TOKEN,
            },
            timeout=30,
        )
        result = resp.json()
        if "id" in result:
            print(f"Posted: {result['id']}")
            return True
        else:
            print(f"Post failed: {result}")
            return False
    except Exception as e:
        print(f"Facebook error: {e}")
        return False


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

    caption = make_caption(post["title"], post["subreddit"])
    print(f"Caption:\n{caption}\n")

    success = post_photo(caption, post["url"])
    if not success:
        print("FAILED")


if __name__ == "__main__":
    main()
