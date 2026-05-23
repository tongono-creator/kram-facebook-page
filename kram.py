import os
import re
import random
import time
import subprocess
import requests
import tempfile
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

# ── Config ───────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ["KRAM_PAGE_ACCESS_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "AIzaSyCi6AbETW4XTjJpcbRxj2oL3ftEWRbv_xI")

client       = genai.Client(api_key=GEMINI_API_KEY)
TEXT_MODELS  = ["gemini-2.5-flash", "gemini-3.5-flash"]
ACCENT_COLOR = (0, 191, 255)  # ฟ้า #00BFFF

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
    "Damnthatsinteresting",
    "AbsoluteUnits",
    "educationalgifs",
    "Whatcouldgowrong",
    "ThatsInsane",
    "BeAmazed",
]

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# subreddits ที่มี video เยอะ (ใช้สำหรับ video mode เพิ่มเติม)
VIDEO_SUBREDDITS = [
    "Unexpected",
    "AnimalsBeingDerps",
    "AnimalsBeingBros",
    "WhatsWrongWithYourCat",
    "NatureIsFuckingLit",
    "nextfuckinglevel",
    "oddlyterrifying",
    "aww",
]


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


def get_reddit_video_post():
    """หา video post จาก Reddit RSS — ดึง v.redd.it ID"""
    subreddit = random.choice(VIDEO_SUBREDDITS)
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        video_posts = []
        for entry in entries:
            title   = entry.findtext("atom:title", "", ns).strip()
            content = entry.findtext("atom:content", "", ns) or ""
            # หา v.redd.it ID จาก content HTML
            vid_ids = re.findall(r'https://v\.redd\.it/([a-zA-Z0-9]+)', content)
            if vid_ids and title:
                video_posts.append({
                    "title":     title,
                    "video_id":  vid_ids[0],
                    "subreddit": subreddit,
                })

        if not video_posts:
            print(f"[{subreddit}] no video posts in RSS")
            return None

        post = random.choice(video_posts[:10])
        print(f"[{subreddit}] video: {post['title'][:60]}")
        return post

    except Exception as e:
        print(f"Reddit video error ({subreddit}): {e}")
        return None


def download_video_with_audio(video_id):
    """Download v.redd.it video + audio แล้ว merge ด้วย ffmpeg"""
    MAX_BYTES = 80 * 1024 * 1024  # 80MB limit
    video_url = f"https://v.redd.it/{video_id}/DASH_720.mp4"
    audio_url = f"https://v.redd.it/{video_id}/DASH_audio.mp4"

    # Download video track
    try:
        v_resp = requests.get(video_url, headers=HEADERS, timeout=30, stream=True)
        v_resp.raise_for_status()
        v_data = b""
        for chunk in v_resp.iter_content(65536):
            v_data += chunk
            if len(v_data) > MAX_BYTES:
                print("Video too large, skipping")
                return None
    except Exception as e:
        print(f"Video track download failed: {e}")
        return None

    v_tmp = tempfile.NamedTemporaryFile(suffix="_v.mp4", delete=False)
    v_tmp.write(v_data)
    v_tmp.close()

    # Download audio track (optional — ไม่ใช่ทุก post มี audio)
    a_tmp_name = None
    try:
        a_resp = requests.get(audio_url, headers=HEADERS, timeout=15, stream=True)
        a_resp.raise_for_status()
        a_data = b""
        for chunk in a_resp.iter_content(65536):
            a_data += chunk
        a_tmp = tempfile.NamedTemporaryFile(suffix="_a.mp4", delete=False)
        a_tmp.write(a_data)
        a_tmp.close()
        a_tmp_name = a_tmp.name
        print(f"Audio downloaded: {len(a_data)} bytes")
    except Exception:
        print("No audio track (silent video)")

    # Merge ด้วย ffmpeg
    out_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    out_tmp.close()

    if a_tmp_name:
        cmd = [
            "ffmpeg", "-y",
            "-i", v_tmp.name,
            "-i", a_tmp_name,
            "-c:v", "copy", "-c:a", "aac",
            "-shortest",
            out_tmp.name,
        ]
    else:
        cmd = ["ffmpeg", "-y", "-i", v_tmp.name, "-c", "copy", out_tmp.name]

    result = subprocess.run(cmd, capture_output=True, timeout=120)
    os.unlink(v_tmp.name)
    if a_tmp_name:
        os.unlink(a_tmp_name)

    if result.returncode != 0:
        print(f"ffmpeg failed: {result.stderr.decode()[:300]}")
        os.unlink(out_tmp.name)
        return None

    size = os.path.getsize(out_tmp.name)
    print(f"Video ready: {size / 1024 / 1024:.1f} MB")
    return out_tmp.name


def post_video(caption, video_path):
    """โพส video ลง Facebook page"""
    try:
        api_url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/videos"
        with open(video_path, "rb") as f:
            resp = requests.post(
                api_url,
                data={
                    "description":  caption,
                    "access_token": PAGE_ACCESS_TOKEN,
                },
                files={"source": ("video.mp4", f, "video/mp4")},
                timeout=180,
            )
        result = resp.json()
        if "id" in result:
            post_id = result.get("post_id") or result["id"]
            print(f"Video Posted: {post_id}")
            add_comment(post_id)
            return True
        else:
            print(f"Video post failed: {result}")
            return False
    except Exception as e:
        print(f"Facebook video error: {e}")
        return False
    finally:
        if video_path and os.path.exists(video_path):
            os.unlink(video_path)


# ── Gemini ────────────────────────────────────────────────────────────
def analyze_image(img_path):
    """Vision ดูรูปแบบคนเล่นโซเชียล — คืน (subject, vibe) tuple"""
    with open(img_path, "rb") as f:
        img_data = f.read()
    prompt = (
        "ดูรูปนี้เหมือนคนไทยที่เล่น Facebook/Twitter ไม่ใช่ AI วิเคราะห์ภาพ\n"
        "ตอบ 2 อย่าง แยกด้วย | :\n"
        "1. เห็นอะไร (สัตว์/เหตุการณ์/ของแปลก) สั้นๆ 1-5 คำ\n"
        "2. ความรู้สึกแรก/มุกที่คนไทยน่าจะเล่น เช่น: "
        "'เหมือนพนักงานโดนเรียกโอที', 'หน้าเบื่องาน monday', 'rich kid', 'เด็กดื้อที่แม่รัก', 'ดราม่ามาก'\n"
        "ถ้าไม่มีอะไรน่าสนใจเลย ตอบว่า: ไม่เกี่ยว|ไม่เกี่ยว"
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
            # parse subject|vibe format
            if "|" in result:
                parts = result.split("|", 1)
                subject = parts[0].strip()
                vibe    = parts[1].strip()
            else:
                subject = result
                vibe    = ""
            return subject, vibe
        except Exception as e:
            print(f"[{model}] vision failed: {e}")
    return None, None


def generate_hook(subject, vibe, subreddit):
    """สร้าง hook text 2 บรรทัดสำหรับ PIL overlay — ใช้ internet brain"""
    vibe_line = f"ฟีล: {vibe}" if vibe else ""
    prompt = (
        f"รูปจาก r/{subreddit}\n"
        f"เห็น: {subject}\n"
        f"{vibe_line}\n\n"
        "คิด 4 ข้อนี้ก่อน (ไม่ต้องตอบ):\n"
        "1. ภาพนี้เหมือนคนประเภทไหน\n"
        "2. คนเห็นแล้วนึกถึงสถานการณ์อะไร\n"
        "3. มุกที่คนไทยน่าจะเล่นคืออะไร\n"
        "4. ถ้าโพสต์นี้อยู่ในเพจไวรัลไทย จะเขียนยังไง\n\n"
        "แล้วเขียน hook text สำหรับใส่บนรูป:\n"
        "บรรทัด 1: hook 3-6 คำ หยุดนิ้วได้ทันที (เล่นมุก/ชั้วๆ/ตรงใจ)\n"
        "บรรทัด 2: คำถาม/ประโยคเสริม สั้น 4-8 คำ\n"
        "ตอบแค่ 2 บรรทัด ไม่มี hashtag ไม่มี **"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            lines = clean_text(resp.text.strip()).split("\n")
            lines = [l.strip() for l in lines if l.strip()]
            line1 = lines[0] if len(lines) > 0 else subject[:20]
            line2 = lines[1] if len(lines) > 1 else ""
            return line1, line2
        except Exception as e:
            print(f"[{model}] hook failed: {e}")
    return subject[:20], ""


def make_caption(subject, vibe, subreddit):
    vibe_line = f"ฟีล: {vibe}" if vibe else ""
    prompt = (
        f"รูปจาก r/{subreddit}\n"
        f"เห็น: {subject}\n"
        f"{vibe_line}\n\n"
        "คิดเหมือนคนไถ Facebook จริงๆ ไม่ใช่นักการตลาด\n"
        "วิเคราะห์อารมณ์จากภาพ เดาความรู้สึกแรกที่คนเห็น\n"
        "ถ้ามีฟีลตลก/แปลก/awkward → เล่นมุกได้เลย ห้ามอวยอัตโนมัติ\n\n"
        "เขียน Facebook caption สำหรับเพจ 'กรามค้าง' (สัตว์/ธรรมชาติ/น่าทึ่ง):\n"
        "บรรทัด 1: hook ที่คนอยากอ่านต่อ (เล่นมุกหรือตรงใจก็ได้)\n"
        "บรรทัด 2: อธิบาย 1-2 ประโยค ตรงกับรูปที่เห็น\n"
        "บรรทัด 3: hashtag 3-5 อัน\n"
        "ห้าม ** markdown ตอบแค่ caption"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return clean_text(resp.text.strip())
        except Exception as e:
            print(f"[{model}] caption failed: {e}")
    return clean_text(subject)


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
                files={"source": ("photo.jpg", f, "image/jpeg")},
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

    # 40% video mode / 60% image mode
    use_video = random.random() < 0.40
    print(f"Mode: {'VIDEO' if use_video else 'IMAGE'}")

    # ── VIDEO MODE ───────────────────────────────────────────────────
    if use_video:
        video_post = None
        for attempt in range(3):
            video_post = get_reddit_video_post()
            if video_post:
                break
            print(f"Video retry {attempt + 1}/3...")

        if video_post:
            video_path = download_video_with_audio(video_post["video_id"])
            if video_path:
                caption = make_caption(video_post["title"], "", video_post["subreddit"])
                caption += f"\n📷 via r/{video_post['subreddit']}"
                print(f"Caption:\n{caption}\n")
                success = post_video(caption, video_path)
                if success:
                    return
                print("Video post failed, falling back to image mode")
            else:
                print("Video download failed, falling back to image mode")
        else:
            print("No video post found, falling back to image mode")

    # ── IMAGE MODE ───────────────────────────────────────────────────
    post = None
    for attempt in range(5):
        post = get_reddit_post()
        if post:
            break
        print(f"Retry {attempt + 1}/5...")

    if not post:
        print("No suitable post found after 5 attempts")
        return

    # Download รูปก่อน → Vision → hook + caption → overlay → post
    img_path = download_image(post["url"])
    if not img_path:
        print("Image download failed")
        return

    subject, vibe = analyze_image(img_path)
    if not subject or "ไม่เกี่ยว" in subject:
        print("Vision: not relevant, using Reddit title as fallback")
        subject = post["title"]
        vibe    = ""

    print(f"Subject: {subject} | Vibe: {vibe}")
    line1, line2 = generate_hook(subject, vibe, post["subreddit"])
    print(f"Hook: {line1} | {line2}")

    # PIL overlay
    try:
        from overlay_utils import add_overlay
        overlaid = add_overlay(img_path, line1, line2, ACCENT_COLOR)
        os.unlink(img_path)
        img_path = overlaid
    except Exception as e:
        print(f"Overlay failed (using original): {e}")

    caption = make_caption(subject, vibe, post["subreddit"])
    caption += f"\n📷 via r/{post['subreddit']}"
    print(f"Caption:\n{caption}\n")

    success = post_photo(caption, img_path)
    if not success:
        print("FAILED")


if __name__ == "__main__":
    main()
