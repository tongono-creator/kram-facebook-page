import os
import re
import random
import requests
import tempfile
from google import genai

# ── Config ───────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ["KRAM_PAGE_ACCESS_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "AIzaSyCi6AbETW4XTjJpcbRxj2oL3ftEWRbv_xI")

client      = genai.Client(api_key=GEMINI_API_KEY)
TEXT_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

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
    sort      = random.choice(["hot", "top"])
    params    = {"limit": 25, "t": "week"}
    url       = f"https://www.reddit.com/r/{subreddit}/{sort}.json"

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]

        image_posts = []
        for p in posts:
            d = p["data"]
            if d.get("is_video") or d.get("is_self"):
                continue
            post_url = d.get("url", "")
            has_image = (
                any(post_url.lower().endswith(ext) for ext in IMAGE_EXTS)
                or ("imgur.com" in post_url and not post_url.endswith(".gifv"))
                or ("i.redd.it" in post_url)
            )
            if has_image:
                image_posts.append(d)

        if not image_posts:
            print(f"[{subreddit}] no image posts found")
            return None

        post = random.choice(image_posts[:10])
        print(f"[{subreddit}] picked: {post['title'][:60]} ({post['score']} pts)")
        return {
            "title":     post["title"],
            "url":       post["url"],
            "subreddit": post["subreddit"],
            "score":     post["score"],
        }
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
    try:
        img_resp = requests.get(image_url, headers=HEADERS, timeout=15)
        img_resp.raise_for_status()
    except Exception as e:
        print(f"Image download failed: {e}")
        return False

    suffix = ".jpg"
    for ext in IMAGE_EXTS:
        if image_url.lower().endswith(ext):
            suffix = ext
            break

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(img_resp.content)
    tmp.close()

    try:
        api_url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/photos"
        with open(tmp.name, "rb") as f:
            resp = requests.post(
                api_url,
                data={
                    "message":      caption,
                    "access_token": PAGE_ACCESS_TOKEN,
                },
                files={"source": f},
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
    finally:
        os.unlink(tmp.name)


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
