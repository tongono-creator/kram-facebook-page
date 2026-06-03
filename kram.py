import os
import re
import random
import time
import subprocess
import requests
import tempfile
import xml.etree.ElementTree as ET
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from google import genai
from google.genai import types
from google.genai.types import HttpOptions

# ── Config ───────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ.get("KRAM_PAGE_ACCESS_TOKEN", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "") or "DUMMY_KEY"

API_ENABLED  = True
client       = genai.Client(api_key=GEMINI_API_KEY, http_options=HttpOptions(timeout=300000))
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
    "technology",
    "todayilearned",
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


# ── History Helper ───────────────────────────────────────────────────
HISTORY_FILE = "posted_history.txt"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception:
            return []
    return []

def save_to_history(item):
    items = load_history()
    items.append(item)
    items = items[-500:] # Cap history
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for it in items:
                f.write(it + "\n")
    except Exception as e:
        print(f"Error saving history: {e}")


# ── Reddit ────────────────────────────────────────────────────────────
def get_reddit_post():
    history = set(load_history())
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
                url = good_imgs[0]
                if url not in history:
                    image_posts.append({
                        "title":     title,
                        "url":       url,
                        "subreddit": subreddit,
                    })

        if not image_posts:
            print(f"[{subreddit}] no unposted image posts in RSS")
            return None

        post = random.choice(image_posts[:10])
        print(f"[{subreddit}] picked: {post['title'][:60]}")
        return post

    except Exception as e:
        print(f"Reddit error ({subreddit}): {e}")
        return None


def get_reddit_video_post():
    """หา video post จาก Reddit RSS — ดึง v.redd.it ID"""
    history = set(load_history())
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
                vid_id = vid_ids[0]
                if vid_id not in history:
                    video_posts.append({
                        "title":     title,
                        "video_id":  vid_id,
                        "subreddit": subreddit,
                    })

        if not video_posts:
            print(f"[{subreddit}] no unposted video posts in RSS")
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
        from affiliate_utils import get_next_scheduled_time, get_all_comments
        slots = ["10:00", "15:00", "20:00"]
        scheduled_time = get_next_scheduled_time(slots)
        
        if scheduled_time:
            comments = get_all_comments(caption=caption, img_path=None)
            comment_texts = []
            for msg in comments:
                if isinstance(msg, dict):
                    comment_texts.append(msg["message"])
                else:
                    comment_texts.append(msg)
            if comment_texts:
                caption += "\n\n📌 ชี้เป้าของดีน่าสนใจ:\n" + "\n".join(comment_texts)
                
            print(f"Scheduling video to Facebook for timestamp {scheduled_time}...")
            api_url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/videos"
            with open(video_path, "rb") as f:
                resp = requests.post(
                    api_url,
                    data={
                        "description":  caption,
                        "access_token": PAGE_ACCESS_TOKEN,
                        "published":    "false",
                        "scheduled_publish_time": scheduled_time
                    },
                    files={"source": ("video.mp4", f, "video/mp4")},
                    timeout=180,
                )
            result = resp.json()
            if "id" in result:
                photo_id = result.get("post_id") or result["id"]
                print(f"Video Scheduled: {photo_id}")
                return True
            else:
                print(f"Video scheduling failed: {result}")
                return False

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
            add_comment(post_id, caption=caption, img_path=None)
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
def analyze_image(img_path, reddit_title=""):
    """Vision ดูรูปแบบคนเล่นโซเชียล — คืน (subject, vibe) tuple"""
    with open(img_path, "rb") as f:
        img_data = f.read()
    title_ctx = f'ชื่อโพสต์ต้นฉบับ: "{reddit_title}"\n' if reddit_title else ""
    prompt = (
        f"{title_ctx}"
        "ดูรูปนี้เหมือนคนไทยที่เล่น Facebook/Twitter ไม่ใช่ AI วิเคราะห์ภาพ\n"
        "เปรียบเทียบชื่อโพสต์ต้นฉบับกับภาพถ่ายที่แนบมาด้วยความระมัดระวัง โดยยึดข้อมูลที่ปรากฏจริงในภาพเป็นหลัก\n"
        "ห้ามตอบโดยอิงตามชื่อโพสต์อย่างเดียวหากรายละเอียดในรูปภาพขัดแย้งกันอย่างเห็นได้ชัด\n\n"
        "ตอบ 2 อย่าง แยกด้วย | :\n"
        "1. เห็นอะไร (สัตว์/เหตุการณ์/ของแปลก) ที่เห็นเด่นชัดจริงๆ ในรูปภาพ สั้นๆ 1-5 คำ (เช่น แมวสีส้ม, สุนัขพันธุ์ไซบีเรียน, โทรศัพท์พัง)\n"
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


def strip_emoji(text):
    """ลบ emoji/สัญลักษณ์พิเศษที่ Kanit font ไม่รองรับ — เหลือแค่ไทย + ASCII"""
    import re
    return re.sub(r'[^฀-๿\x20-\x7E]', '', text).strip()


# subreddits ที่เป็น animal content → ใช้ animal formula
ANIMAL_SUBS = {
    "aww", "AnimalsBeingBros", "rarepuppers",
    "WhatsWrongWithYourCat", "AnimalsBeingDerps",
}


REALISM_FILTER = (
    "เขียนเหมือนคนพิมพ์เองใน Facebook ไม่ใช่นักการตลาด\n"
    "เขียนด้วยบุคลิกแอดมินผู้ชาย (ใช้สรรพนามแทนตัวว่า 'ผม' หรือ 'พี่' และใช้คำลงท้ายว่า 'ครับ' เท่านั้น ห้ามใช้คำลงท้ายของผู้หญิง)\n"
    "ภาษาพูดธรรมดา ความคิดแรกที่นึกได้ ง่ายๆ ตรงๆ\n"
    "avoid: คำคม, punchline ประดิษฐ์, คำเปรียบเทียบแปลกๆ, ภาษาสวย, ประโยคฝืน\n"
    "prioritize: relatable, ความจริงของมนุษย์, มุกที่คนพูดจริงๆ, ตรงใจ\n"
    "ตัวอย่างโทนที่ถูก: 'หน้าเบื่องาน monday', 'เด็กดื้อที่แม่รัก', 'rich kid พันธุ์แท้'\n"
    "ตัวอย่างโทนที่ผิด: punchline ประดิษฐ์, คำเปรียบเทียบไม่เกี่ยวกับรูป\n"
    "\n"
    "CRITICAL — exotic animal rule:\n"
    "ถ้า subject เป็นสัตว์เลื้อยคลาน สัตว์ป่า หรือสัตว์แปลก (ตะกวด, งู, จระเข้, แมงป่อง, นกล่าเหยื่อ ฯลฯ)\n"
    "ห้ามใช้คำเหล่านี้เด็ดขาด: ขี้อ้อน, เป็นมิตร, น่าเลี้ยง, น่ารัก, ซื่อสัตย์, ชอบอยู่กับคน\n"
    "คำเหล่านี้คือนิสัยหมาแมว ไม่ใช่ข้อเท็จจริงของสัตว์ป่า — ใช้แทนด้วย: ขนาด, ความน่าทึ่ง, สถิติ, พฤติกรรมจริงในธรรมชาติ\n"
)


def clean_hook_lines(raw_text):
    text = clean_text(raw_text)
    
    # Check if we should split by pipe or newline
    if "|" in text:
        parts = text.split("|")
    else:
        parts = text.split("\n")
        
    # Pattern to strip prefixes like "บรรทัด 1: ", "ข้อความในโพสต์ Facebook: ", "1. ", etc.
    label_pattern = r'^(ข้อความในโพสต์\s*Facebook|Facebook\s*Caption|Facebook\s*caption|Caption|caption|ข้อความบนรูป|ข้อความในรูป|ข้อความ|คำบรรยาย|คำอธิบาย|บรรทัดที่\s*\d+|บรรทัด\s*\d+|ประโยคที่\s*\d+|ประโยค\s*\d+|Hook\s*text|Hook|Line\s*\d+|[L|l]ine\s*\d+|\d+)\s*[:\-\.\s]\s*'
    
    cleaned_lines = []
    for part in parts:
        cleaned = re.sub(label_pattern, '', part, flags=re.IGNORECASE).strip()
        cleaned = cleaned.strip('"\'“”‘’')
        if cleaned:
            cleaned_lines.append(cleaned)
            
    return cleaned_lines


def contains_thai(text):
    if not text:
        return False
    return any('\u0e00' <= char <= '\u0e7f' for char in text)

_LEADING_VOWELS  = set('เแโใไ')
_COMBINING_CHARS = set('่้๊๋์ิีึืุูัํ็')

THAI_WORDS = [
    "รายละเอียด", "โปรโมชั่น", "เครื่องมือ", "คอมพิวเตอร์", "แอปพลิเคชัน", "เก็บเงินปลายทาง",
    "โทรศัพท์", "แบตเตอรี่", "บัตรเครดิต", "พร้อมส่ง", "จัดส่ง", "ต่างประเทศ",
    "พรีออเดอร์", "ประหยัด", "ปลอดภัย", "คุ้มค่า", "สะดวกสบาย", "ธรรมชาติ",
    "คุณภาพ", "ภาพถ่าย", "พลาสติก", "ของแท้", "รับประกัน", "ลิขสิทธิ์",
    "แนะนำ", "สินค้า", "รีวิว", "สุดยอด", "ดีที่สุด", "สะดวก", "สบาย", "ง่ายดาย",
    "รวดเร็ว", "โปรโมชั่", "ส่วนลด", "คูปอง", "จัดส่ง", "ประกัน",
    "ชาร์จ", "หน้าจอ", "ลำโพง", "หูฟัง", "กล้อง", "เลนส์", "มือถือ", "ปุ่มกด",
    "สำหรับ", "เกี่ยวกับ", "อย่างไร", "เมื่อไหร่", "ที่ไหน", "เท่าไหร่",
    "ทุกคน", "ทุกวัน", "ทุกคืน", "สุดท้าย", "แรกเริ่ม", "จริงจัง",
    "สวัสดี", "ขอบคุณ", "ขอโทษ", "ยินดี", "หัวเราะ", "ร้องไห้",
    "ทำงาน", "พักผ่อน", "ออกกำลัง", "ท่องเที่ยว", "เดินทาง",
    "เก้าอี้", "โต๊ะทำงาน", "เบาะรอง", "พิงหลัง", "สายรัด", "การ์ตูน",
    "กระเป๋า", "รองเท้า", "เสื้อผ้า", "กางเกง", "นาฬิกา", "แว่นตา", "เครื่อง", "ระบบ",
    "ความสุข", "ร่างกาย", "สุขภาพ", "ออกกำลัง", "อาหาร", "ผลไม้", "น้ำดื่ม", "กาแฟ",
    "ราคา", "พิเศษ", "ทั่วไป", "ส่งฟรี", "ลดราคา", "ของแถม", "ปลายทาง",
    "ชั่วโมง", "นาที", "วินาที", "สัปดาห์", "ปีใหม่", "วันนี้", "พรุ่งนี้", "เมื่อวาน",
    "ใครก็ตาม", "สิ่งใด", "ทั้งหมด", "บางส่วน", "ประเภท", "รูปแบบ",
    "ติดตาม", "กดไลก์", "แชร์โพส", "คอมเมนต์", "คลิกลิงก์", "พิกัด", "ชี้เป้า",
    "ค่ะ", "ครับ", "ผม", "เรา", "คุณ", "ท่าน",
    "พี่", "น้อง", "พ่อ", "แม่", "เพื่อน", "บ้าน", "เมือง", "เวลา", "ดีใจ", "เสียใจ", 
    "รัก", "ชอบ", "เกลียด", "กลัว", "โกรธ", "ทำ", "กิน", "นอน", "เดิน", "วิ่ง", "นั่ง", 
    "ยืน", "พูด", "ฟัง", "ดู", "เห็น", "คิด", "รู้", "จำ", "ลืม", "เรียน", "เล่น", "ซื้อ", 
    "ขาย", "ราคา", "ถูก", "แพง", "ลด", "แถม", "ส่ง", "ด่วน", "ฟรี", "รับ", "ศูนย์",
    "แท้", "ใหม่", "เก่า", "แรก", "นี้", "นั้น", "โน้น", "นี่", "นั่น", "โน่น", "อะไร", 
    "ใคร", "กี่", "บ้าง", "ทุก", "บาง", "จริง", "จัง", "แท้", "เทียม", "ปลอม", "สาย", 
    "เคส", "ฟิล์ม", "ภาพ", "รูป", "เสียง", "เพลง", "หนัง", "เกม", "แอป", "เว็บ", "เน็ต", 
    "โค้ด", "โอน", "หวย", "ออก", "เงิน", "เก็บ", "แสน", "แรก", "งาน", "การ", "ช่วย", 
    "บอก", "ให้", "คน", "ทอง", "ร้อย", "พัน", "หมื่น", "ล้าน", "มาก", "น้อย", "ดี", 
    "เลว", "ชั่ว", "สูง", "ต่ำ", "ดำ", "ขาว", "แดง", "เขียว", "เหลือง", "ฟ้า", "ส้ม", 
    "ชมพู", "ม่วง", "เทา", "สวย", "หล่อ", "และ", "หรือ", "แต่", "ที่", "ซึ่ง", "อัน", 
    "ของ", "เพื่อ", "ใน", "จาก", "โดย", "ตาม", "กับ", "มี", "เป็น", "จะ", "ต้อง", 
    "อยาก", "นุ่ม", "แข็ง", "ใหญ่", "เล็ก", "ยาว", "สั้น", "กว้าง", "แคบ", "หนา", 
    "บาง", "ร้อน", "เย็น", "อุ่น", "หนาว", "ง่าย", "ยาก", "เร็ว", "ช้า", "ได้", 
    "เลย", "ด้วย", "จาก", "ถึง", "จน", "กว่า", "ก็", "ยัง", "อีก", "แล้ว", "นะ", 
    "สิ", "ละ", "หน่อย", "นิด", "ชิ้น", "กล่อง", "อัน", "ตัว", "ใบ", "คู่", "ชุด", 
    "แผ่น", "ม้วน"
]

def local_segment_thai(text):
    if not text:
        return ""
    word_set = set(THAI_WORDS)
    max_len = max(len(w) for w in THAI_WORDS)
    
    result = []
    i = 0
    n = len(text)
    
    while i < n:
        if not contains_thai(text[i]):
            result.append(text[i])
            i += 1
            continue
            
        matched = False
        for l in range(min(max_len, n - i), 0, -1):
            substr = text[i:i+l]
            if substr in word_set:
                result.append(substr)
                i += l
                matched = True
                break
        
        if not matched:
            start = i
            while i < n and contains_thai(text[i]):
                word_matched_here = False
                if i > start:
                    for l in range(min(max_len, n - i), 0, -1):
                        if text[i:i+l] in word_set:
                            word_matched_here = True
                            break
                if word_matched_here:
                    break
                i += 1
            result.append(text[start:i])
            
    output = []
    for idx, part in enumerate(result):
        if idx > 0:
            prev_char = result[idx-1][-1]
            curr_char = part[0]
            if (contains_thai(prev_char) and contains_thai(curr_char) and 
                prev_char != '\u200b' and curr_char != '\u200b' and
                curr_char not in _COMBINING_CHARS and
                prev_char not in _LEADING_VOWELS):
                output.append('\u200b')
        output.append(part)
        
    return "".join(output)

def segment_thai_text(text, client=client):
    global API_ENABLED
    if not text or not contains_thai(text):
        return text
    if not API_ENABLED:
        return local_segment_thai(text)
    prompt = (
        "You are an expert Thai word segmentation tool. "
        "Your task is to insert a zero-width space character (\\u200b) at every natural word boundary in the provided Thai text. "
        "Strict rules:\n"
        "1. Do NOT modify, delete, or add any words, characters, punctuation, spaces, or newlines of the original text. "
        "Keep the exact same characters and layout.\n"
        "2. Do NOT add any introductory or concluding remarks. Output ONLY the segmented text.\n"
        "3. Ensure words like 'หวยออก', 'เงินเก็บ', 'แสนแรก', 'ทำงาน' are segmented at their natural boundaries (e.g., 'หวย\\u200bออก' or left as 'หวยออก', but never break syllables awkwardly).\n\n"
        f"Text to segment:\n{text}"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            segmented = resp.text.strip().replace('\\u200b', '\u200b')
            clean_orig = text.replace('\u200b', '').replace('\\u200b', '')
            clean_seg = segmented.replace('\u200b', '').replace('\\u200b', '')
            if len(clean_orig) == len(clean_seg):
                return segmented
        except Exception as e:
            print(f"[{model}] segment_thai_text failed: {e}")
    print("[Warning] segment_thai_text failed on all models. Disabling API calls for this run.")
    API_ENABLED = False
    return local_segment_thai(text)

def verify_image_title_match(img_bytes, reddit_title):
    global API_ENABLED
    if not API_ENABLED:
        return True
    prompt = (
        f"Analyze this image and the Reddit thread title: '{reddit_title}'. "
        "Do the title and the image describe/show the same event, object, or subject matter? "
        "(e.g. if the title is about space telescopes and the image shows a chess board, they do NOT match). "
        "Output ONLY 'yes' or 'no' in lowercase, without punctuation."
    )
    part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[part, prompt]
            )
            result = resp.text.strip().lower()
            print(f"[{model}] Image-title match verification result: '{result}'")
            if "yes" in result:
                return True
            elif "no" in result:
                return False
        except Exception as e:
            print(f"[{model}] verify_image_title_match failed: {e}")
    return True

def translate_to_thai(text):
    if not text or contains_thai(text):
        return text
    prompt = f"Translate the following English text into natural, fluent Thai language. Output ONLY the Thai translation, without explanations, notes, or labels:\n\n{text}"
    for model in TEXT_MODELS:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                translated = resp.text.strip()
                if contains_thai(translated):
                    return translated
            except Exception as e:
                print(f"[{model}] Translation attempt {attempt+1} failed: {e}")
                time.sleep(2)
    return text

FALLBACK_POSTS = [
    {
        "hook1": "ความลับสุดทึ่ง..",
        "hook2": "ปลาโลมาสามารถหลับตาข้างเดียวได้ครับ",
        "caption": "รู้หรือไม่ครับว่าปลาโลมาเป็นสัตว์ที่มีระบบการนอนที่มหัศจรรย์มาก พวกมันจะหลับตาข้างเดียวและพักสมองทีละซีก เพื่อคอยระวังภัยขณะนอนหลับ ส่วนสมองซีกที่เหลือจะคอยสั่งการให้หายใจและพยุงตัวไม่ให้จมน้ำครับ ใครเห็นแล้วประทับใจความฉลาดของโลมาบ้าง ลองคอมเมนต์คุยกันหน่อยครับ\n\n#ปลาโลมา #เรื่องน่ารู้ #สัตว์โลกน่ารัก #ธรรมชาติ"
    },
    {
        "hook1": "เห็ดเรืองแสงได้..",
        "hook2": "พบเห็นได้จริงในป่าลึกตอนกลางคืนครับ",
        "caption": "ธรรมชาติในป่าลึกช่วงหน้าฝนมีความลับที่ชวนขนลุกและมหัศจรรย์ปะปนอยู่ครับ เห็ดเรืองแสงบางชนิดสามารถปล่อยแสงสีเขียวเข้มออกมาท่ามกลางความมืดมิด เพื่อล่อแมลงให้มาตอมและช่วยกระจายสปอร์ในการขยายพันธุ์ต่อไปครับ ใครเคยไปเดินป่าแล้วเจอสิ่งมหัศจรรย์แบบนี้บ้าง มาแชร์ประสบการณ์กันได้เลยครับ\n\n#เห็ดเรืองแสง #ธรรมชาติบำบัด #เรื่องแปลก #เดินป่า"
    },
    {
        "hook1": "หัวใจดวงใหญ่ยักษ์..",
        "hook2": "วาฬสีน้ำเงินมีหัวใจใหญ่เท่ารถยนต์คันเล็กครับ",
        "caption": "วาฬสีน้ำเงินคือสิ่งมีชีวิตที่มีขนาดใหญ่ที่สุดเท่าที่โลกเคยมีมาครับ หัวใจของมันห้องเดียวมีน้ำหนักมากถึง 180 กิโลกรัมแล้ว และเส้นเลือดใหญ่ของมันก็กว้างพอที่จะให้มนุษย์ลงไปว่ายน้ำได้สบายๆ ครับ ธรรมชาติช่างน่าทึ่งจริงๆ ใครชอบเรื่องของวาฬยักษ์พิมพ์คอมเมนต์กันมาหน่อยครับ\n\n#วาฬสีน้ำเงิน #สัตว์ทะเล #เรื่องน่าทึ่ง #โลกใต้ทะเล"
    }
]

def generate_hook(subject, vibe, subreddit):
    """สร้าง hook text 2 บรรทัดสำหรับ PIL overlay
    - สัตว์ → Pet POV หรือ บ่นพฤติกรรมสัตว์เลี้ยงกวนๆ ตลกร้าย (เช่น 'มองแรงใส่ผม..', 'ทวงขนมคำโต..')
    - ว้าว/น่าทึ่ง/วิทยาศาสตร์ → หัวข้อชวนถกเถียงหรือสงสัย (เช่น 'กล้ากินไหมครับ?', 'เรื่องจริงสุดหลอน..')
    """
    vibe_line = f"ฟีล: {vibe}" if vibe else ""
    is_animal = subreddit in ANIMAL_SUBS

    if is_animal:
        prompt = (
            f"รูปสัตว์จาก r/{subreddit}\n"
            f"เห็น: {subject}\n"
            f"{vibe_line}\n\n"
            "เขียน hook text ภาษาไทยสั้นๆ กวนๆ ตลกๆ 2 บรรทัดบนรูปภาพ (ฟีลสัตว์บ่นใส่ทาส หรือเจ้าของทาสบ่นพฤติกรรมสุดกวน):\n"
            "บรรทัด 1: คำพูดตัดพ้อ/บ่น/ทวงความยุติธรรมสั้นๆ 2-5 คำ ลงท้ายด้วย .. (เช่น 'เมื่อปลุกตอนตีสอง..', 'ขอลดทิฐิลงก่อน..')\n"
            "บรรทัด 2: มุกจิกกัดหรือความจริงอันฮาๆ 4-8 คำ เกี่ยวกับพฤติกรรมมัน (เช่น 'ทวงขนมแบบประธานบริษัท', 'คิดว่าผมไม่เห็นมั้งครับ')\n"
            "ใช้ภาษาพูดแบบเป็นกันเอง สรรพนามเพศชาย (ครับ) ไม่เป็นทางการ ห้ามใส่ป้ายกำกับ\n\n"
            "⚠️ CRITICAL RULES:\n"
            "1. DO NOT include any labels like 'Line 1:', 'บรรทัด 1:', 'Hook:', or any intros/outros.\n"
            "2. DO NOT write any conversational intro or acknowledgment filler. Start directly with the hook lines."
        )
    else:
        prompt = (
            f"Interesting fact/news post from r/{subreddit}\n"
            f"Subject visible: {subject}\n"
            f"{vibe_line}\n\n"
            "Write a very short, eye-catching 2-line Thai debate/curiosity hook for this image (NOT a long sentence):\n"
            "Line 1: Shocking/exciting/question statement (3-5 Thai words, e.g. 'กล้าลองไหมครับ?', 'ล้ำหรือหลอนดี?', 'ความลับสุดอึ้ง').\n"
            "Line 2: Subject of debate or mystery (3-5 Thai words, e.g. 'เครื่องจักรมีสมอง', 'ธรรมชาติสุดแปลก', 'ความจริงเรื่องปลา').\n"
            "Absolutely NO long explanations, NO fillers. Keep it extremely short (3-5 words per line) so it renders clearly.\n\n"
            "⚠️ CRITICAL RULES:\n"
            "1. DO NOT include any labels like 'Line 1:', 'บรรทัด 1:', 'Hook:', or any intros/outros. Output ONLY the 2 lines of text.\n"
            "2. Keep the length extremely short (max 5 words per line).\n"
            "3. DO NOT write any conversational intro or acknowledgment filler. Start directly with the hook lines."
        )
    # keywords ที่เป็น prompt echo หรือ filler ของโมเดล — ต้องกรองทิ้งเพิ่มเติมเพื่อป้องกันการโพสต์เสียของ
    ECHO_KEYWORDS = [
        "Hook text", "บรรทัด", "ตอบแค่", "สำหรับใส่บนรูป", "hook text",
        "แน่นอน", "จัดไป", "ตามคำขอ", "ได้เลย", "จัดให้", "ยินดี",
        "นี่คือ", "ข้อความ", "คำโปรย", "คำคม", "หัวข้อ", "ตามคำขอ"
    ]
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            lines = clean_hook_lines(resp.text)
            # กรอง prompt echo ออก
            lines = [l for l in lines if not any(kw in l for kw in ECHO_KEYWORDS)]
            # ลบ emoji ก่อนส่ง overlay
            lines = [strip_emoji(l) for l in lines]
            lines = [l for l in lines if l]  # กรองบรรทัดว่างหลัง strip
            line1 = lines[0] if len(lines) > 0 else strip_emoji(subject[:20])
            line2 = lines[1] if len(lines) > 1 else ""
            
            if not contains_thai(line1):
                line1 = translate_to_thai(line1)
            if line2 and not contains_thai(line2):
                line2 = translate_to_thai(line2)
            return line1, line2
        except Exception as e:
            print(f"[{model}] hook failed: {e}")
            
    fallback_subject = strip_emoji(subject[:20])
    if not contains_thai(fallback_subject):
        fallback_subject = translate_to_thai(fallback_subject)
    return fallback_subject, ""


def make_caption(img_path, subject, vibe, subreddit, reddit_title=""):
    vibe_line = f"ฟีล: {vibe}" if vibe else ""
    title_line = f"ชื่อโพสต์ต้นฉบับ: {reddit_title}" if reddit_title else ""
    is_animal = subreddit in ANIMAL_SUBS
    if is_animal:
        # ─── Animal formula — Short Natural Paragraph ────────────────────
        prompt = (
            f"รูปสัตว์จาก r/{subreddit}\n"
            f"เห็น: {subject}\n"
            f"{vibe_line}\n"
            f"{title_line}\n\n"
            "Strict Chain of Thought (CoT) Caption Consistency:\n"
            "  1. Read the Original Post Title to understand the context.\n"
            "  2. Look at the attached image carefully: Prioritize what animal, pose, object, and environment are ACTUALLY visible in the image. Do not assume or hallucinate details that are not there.\n"
            "  3. Write the caption ensuring it matches the actual visual evidence shown in the image.\n\n"
            + REALISM_FILTER +
            "เขียน Facebook caption เป็นข้อความสั้นปกติ 1 ย่อหน้า (ความยาว 2-4 บรรทัด) สไตล์บ่นพฤติกรรมสุดดื้อ/กวนของสัตว์เลี้ยง (เช่น ขโมยขนม, ปลุกตอนดึก, หน้าเบื่อโลก) หรือมุมมองฮาๆ ของคนเป็นทาส\n"
            "ห้ามเขียนในรูปแบบข้อตกลง หัวข้อย่อย หรือมีสัญลักษณ์นำหน้าบรรทัด เช่น ▪️ หรือ - เด็ดขาด\n"
            "เล่าเหตุการณ์แบบเป็นกันเอง เหมือนเมาท์มอยแฉความมึนของมันให้เพื่อนฟัง\n"
            "คุณ MUST จบด้วยประโยคสั้นๆ ตั้งคำถามชวนให้คนเลี้ยงสัตว์มาแชร์ประสบการณ์ของสัตว์เลี้ยงตัวเองที่บ้าน (เช่น 'บ้านใครโดนหน้าตาแบบนี้ทวงขนมบ้างครับ?', 'ที่บ้านใครมีเด็กดื้อแสบแบบนี้รายงานตัวหน่อยครับ?')\n"
            "จบด้วย hashtag 3-4 อัน\n"
            "ห้าม ** markdown ตอบแค่ caption"
        )
    else:
        # ─── Discovery formula — Short Natural Paragraph ──────────────────
        prompt = (
            f"Interesting fact/news post from r/{subreddit}\n"
            f"Subject visible: {subject}\n"
            f"{vibe_line}\n"
            f"{title_line}\n\n"
            "Strict Chain of Thought (CoT) Caption Consistency:\n"
            "  1. Read the Original Post Title and Context to understand what this post is historically about.\n"
            "  2. Look at the attached image carefully: Prioritize what objects, actions, and details are ACTUALLY visible in the image. Do not assume or hallucinate details that are not there.\n"
            "  3. Write the caption ensuring it matches the actual visual evidence shown in the image.\n\n"
            + REALISM_FILTER +
            "Write a high-engagement Facebook caption in THAI based on this fact/news as a single short paragraph (2-4 sentences). Absolutely NO bullet points, lists, or symbols like ▪️.\n"
            "Structure of the narrative:\n"
            "Start with a shocking claim or interesting fact from the image, explain briefly how it works or why it's cool. Frame the topic as a curiosity debate or question to stimulate comments.\n"
            "Tone: Casual, engaging, informative, and slightly sarcastic/humorous (ภาษาพูดธรรมดา สรรพนามแทนตัวเองด้วยผม/พี่ และลงท้ายสุภาพครับ/ผม).\n"
            "คุณ MUST จบด้วยประโยคตั้งคำถามชวนคุย/ชวนดีเบตความเห็นเรื่องนั้นๆ (เช่น 'ถ้าเจอแบบนี้จะกล้าลองกินไหมครับ?', 'คิดว่าเป็นเรื่องจริงหรือจัดฉากครับ?')\n"
            "Do not use markdown like ** or bolding in the caption.\n"
            "End the caption with 3-4 relevant hashtags.\n"
            "Output ONLY the caption."
        )
    for model in TEXT_MODELS:
        try:
            if img_path and os.path.exists(img_path):
                with open(img_path, "rb") as f:
                    img_data = f.read()
                contents = [
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg"),
                    types.Part.from_text(text=prompt)
                ]
            else:
                contents = [prompt]
            resp = client.models.generate_content(model=model, contents=contents)
            caption = clean_text(resp.text.strip())
            if not contains_thai(caption):
                caption = translate_to_thai(caption)
            return caption
        except Exception as e:
            print(f"[{model}] caption failed: {e}")
            
    fallback_caption = clean_text(subject)
    if not contains_thai(fallback_caption):
        fallback_caption = translate_to_thai(fallback_caption)
    return fallback_caption


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
        from affiliate_utils import get_next_scheduled_time, get_all_comments
        slots = ["10:00", "15:00", "20:00"]
        scheduled_time = get_next_scheduled_time(slots)
        
        if scheduled_time:
            comments = get_all_comments(caption=caption, img_path=img_path)
            comment_texts = []
            for msg in comments:
                if isinstance(msg, dict):
                    comment_texts.append(msg["message"])
                else:
                    comment_texts.append(msg)
            if comment_texts:
                caption += "\n\n📌 ชี้เป้าของดีน่าสนใจ:\n" + "\n".join(comment_texts)
                
            print(f"Scheduling photo to Facebook for timestamp {scheduled_time}...")
            api_url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/photos"
            with open(img_path, "rb") as f:
                resp = requests.post(
                    api_url,
                    data={
                        "message":      caption,
                        "access_token": PAGE_ACCESS_TOKEN,
                        "published":    "false",
                        "unpublished_content_type": "SCHEDULED",
                        "scheduled_publish_time": scheduled_time
                    },
                    files={"source": ("photo.jpg", f, "image/jpeg")},
                    timeout=60,
                )
            result = resp.json()
            if "id" in result:
                photo_id = result.get("post_id") or result["id"]
                print(f"Photo Scheduled: {photo_id}")
                return True
            else:
                print(f"Photo scheduling failed: {result}")
                return False

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
            add_comment(post_id, caption=caption, img_path=img_path)
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
def add_comment(post_id, caption=None, img_path=None):
    from affiliate_utils import get_all_comments
    comments = get_all_comments(caption=caption, img_path=img_path)
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
            timeout=60,
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without posting to Facebook")
    args = parser.parse_args()

    print("=== กรามค้าง Bot ===")
    if args.dry_run:
        print("[DRY RUN MODE ACTIVE]")

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
                title_th = translate_to_thai(video_post["title"])
                caption = make_caption(None, title_th, "", video_post["subreddit"], title_th)
                if not caption or not contains_thai(caption):
                    fallback = random.choice(FALLBACK_POSTS)
                    caption = fallback["caption"]
                else:
                    caption += f"\n📷 via r/{video_post['subreddit']}"
                print(f"Caption:\n{caption}\n")
                if args.dry_run:
                    print(f"[DRY RUN] Would post video. File: {video_path}")
                    return
                success = post_video(caption, video_path)
                if success:
                    save_to_history(video_post["video_id"])
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

    with open(img_path, "rb") as f:
        img_bytes = f.read()

    if not verify_image_title_match(img_bytes, post["title"]):
        print("Safeguard triggered: Image and title do not match. Skipping entry.")
        if os.path.exists(img_path):
            os.unlink(img_path)
        return

    subject, vibe = analyze_image(img_path, reddit_title=post["title"])
    if not subject or "ไม่เกี่ยว" in subject:
        print("Vision: not relevant, using Reddit title as fallback")
        subject = post["title"]
        vibe    = ""

    # Translate title and subject to Thai before using them in prompts
    title_th = translate_to_thai(post["title"])
    subject_th = translate_to_thai(subject)

    print(f"Subject (Thai): {subject_th} | Vibe: {vibe}")
    
    try:
        line1, line2 = generate_hook(subject_th, vibe, post["subreddit"])
        if not contains_thai(line1):
            line1 = translate_to_thai(line1)
        if line2 and not contains_thai(line2):
            line2 = translate_to_thai(line2)
    except Exception as e:
        print(f"Generate hook failed: {e}")
        line1, line2 = "", ""

    try:
        caption = make_caption(img_path, subject_th, vibe, post["subreddit"], title_th)
        if not contains_thai(caption):
            caption = translate_to_thai(caption)
    except Exception as e:
        print(f"Make caption failed: {e}")
        caption = ""

    is_fallback = False
    # Validate output has Thai
    if not line1 or not contains_thai(line1) or not caption or not contains_thai(caption):
        print("Safeguard triggered: missing Thai content. Using FALLBACK_POSTS.")
        is_fallback = True
        fallback = random.choice(FALLBACK_POSTS)
        line1 = fallback["hook1"]
        line2 = fallback["hook2"]
        caption = fallback["caption"]
    else:
        caption += f"\n📷 via r/{post['subreddit']}"

    line1 = segment_thai_text(line1, client)
    line2 = segment_thai_text(line2, client)
    print(f"Hook: {line1} | {line2}")

    # PIL overlay
    try:
        from overlay_utils import add_overlay
        img_to_overlay = img_path
        if is_fallback:
            if fallback["hook1"] == "ความลับสุดทึ่ง..":
                img_to_overlay = os.path.join("fallback_images", "dolphin.png")
            elif fallback["hook1"] == "เห็ดเรืองแสงได้..":
                img_to_overlay = os.path.join("fallback_images", "mushroom.png")
            elif fallback["hook1"] == "หัวใจดวงใหญ่ยักษ์..":
                img_to_overlay = os.path.join("fallback_images", "whale.png")
            else:
                img_to_overlay = None

        overlaid = add_overlay(img_to_overlay, line1, line2, ACCENT_COLOR)
        if img_path and os.path.exists(img_path):
            os.unlink(img_path)
        img_path = overlaid
    except Exception as e:
        print(f"Overlay failed (using original): {e}")

    print(f"Caption:\n{caption}\n")

    if args.dry_run:
        print(f"[DRY RUN] Would post photo. File: {img_path}")
        return

    success = post_photo(caption, img_path)
    if not success:
        print("FAILED")
    else:
        save_to_history(post["url"])


if __name__ == "__main__":
    main()
