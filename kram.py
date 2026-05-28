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

# ── Config ───────────────────────────────────────────────────────────
PAGE_ID           = "116701184708556"
PAGE_ACCESS_TOKEN = os.environ["KRAM_PAGE_ACCESS_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")

client       = genai.Client(api_key=GEMINI_API_KEY, http_options={'timeout': 90.0})
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


def generate_hook(subject, vibe, subreddit):
    """สร้าง hook text 2 บรรทัดสำหรับ PIL overlay
    - สัตว์ → inner monologue สั้นๆ ที่อ่านแล้วเข้าใจได้ทันที ไม่สั้นห้วนจนงง
    - ว้าว/น่าทึ่ง → discovery hook สั้นๆ ดึงดูดความสนใจ (ไม่ใช่ประโยคเล่าเรื่องยาว)
    """
    vibe_line = f"ฟีล: {vibe}" if vibe else ""
    is_animal = subreddit in ANIMAL_SUBS

    if is_animal:
        prompt = (
            f"รูปสัตว์จาก r/{subreddit}\n"
            f"เห็น: {subject}\n"
            f"{vibe_line}\n\n"
            "เขียน hook text ภาษาไทยสั้นๆ กวนๆ ดึงดูดสายตา 2 บรรทัดบนรูปภาพ (อ่านแล้วเข้าใจมุกได้ทันที ไม่ห้วนจนงง):\n"
            "บรรทัด 1: สิ่งที่สัตว์คิด/รู้สึกสั้นๆ 2-5 คำ ลงท้ายด้วย .. (เช่น 'มองแรงขั้นสุด..', 'เนียนเลยนะ..')\n"
            "บรรทัด 2: หักมุมหรือคำอธิบายความในใจสั้นๆ 4-8 คำ เพื่อให้เข้าใจมุกได้ชัดเจน (เช่น 'เหมือนโดนเรียกทำโอทีวันหยุด', 'นึกว่าแม่ไม่เห็น')\n"
            "ใช้ภาษาพูดธรรมดาสั้นๆ ไม่เขียนคำบรรยายยาว ไม่เขียนคำนำหรือป้ายกำกับ\n\n"
            "⚠️ CRITICAL RULES:\n"
            "1. DO NOT include any labels like 'Line 1:', 'บรรทัด 1:', 'Hook:', or any intros/outros.\n"
            "2. DO NOT write any conversational intro or acknowledgment filler like 'แน่นอน!', 'จัดไป!', 'ตามคำขอ', 'ได้เลยครับ' etc. Start directly with the hook lines."
        )
    else:
        prompt = (
            f"Interesting fact/news post from r/{subreddit}\n"
            f"Subject visible: {subject}\n"
            f"{vibe_line}\n\n"
            "Write a very short, punchy, eye-catching 2-line Thai hook for this image (NOT a long sentence or paragraph):\n"
            "Line 1: Shocking/exciting keyword or brief claim (3-5 Thai words, e.g. 'เรื่องจริงสุดอึ้ง', 'เทคโนโลยีสุดล้ำ', 'ที่แรกในโลก').\n"
            "Line 2: Core curiosity generator / subject (3-5 Thai words, e.g. 'ศูนย์ข้อมูลใต้น้ำ', 'สิ่งมีชีวิตลึกลับ', 'ภาพถ่ายประวัติศาสตร์').\n"
            "Absolutely NO long explanations, NO conversational sentences, NO fillers. Keep it extremely short (3-5 words per line) so it renders very large and clear on the image.\n\n"
            "⚠️ CRITICAL RULES:\n"
            "1. DO NOT include any labels like 'Line 1:', 'บรรทัด 1:', 'Hook:', or any intros/outros. Output ONLY the 2 lines of text.\n"
            "2. Keep the length extremely short (max 5 words per line).\n"
            "3. DO NOT write any conversational intro or acknowledgment filler like 'แน่นอน!', 'จัดไป!', 'ตามคำขอ', 'ได้เลยครับ' etc. Start directly with the hook lines."
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
            return line1, line2
        except Exception as e:
            print(f"[{model}] hook failed: {e}")
    return subject[:20], ""


def make_caption(img_path, subject, vibe, subreddit, reddit_title=""):
    vibe_line = f"ฟีล: {vibe}" if vibe else ""
    title_line = f"ชื่อโพสต์ต้นฉบับ: {reddit_title}" if reddit_title else ""
    is_animal = subreddit in ANIMAL_SUBS

    if is_animal:
        # ─── Animal formula — ▪️ bullet narrative ────────────────────
        prompt = (
            f"รูปสัตว์จาก r/{subreddit}\n"
            f"เห็น: {subject}\n"
            f"{vibe_line}\n"
            f"{title_line}\n\n"
            + REALISM_FILTER +
            "เขียน Facebook caption แบบ ▪️ bullet narrative สไตล์เพจสัตว์ไวรัลไทย\n"
            "ใช้ ▪️ นำหน้าทุก bullet — 6-8 จุด เล่าเรื่องมีความต่อเนื่อง\n"
            "โครงสร้าง:\n"
            "▪️ 1-2: Setup — เหตุการณ์ที่เห็นในรูป สัตว์ทำอะไร สถานการณ์คืออะไร\n"
            "▪️ 3-4: Narrate — เล่าเหมือนผู้บรรยายละคร dramatic ใส่ความรู้สึก\n"
            "▪️ 5-6: Inner voice — ใส่ \" \" เขียนจากมุมมองสัตว์พูดเอง + insight โดยอ้างอิงและบรรยายสิ่งที่เห็นเด่นชัดในรูปภาพจริง\n"
            "▪️ 7-8: Engage — punchline ตลกๆ หรือ life lesson + คำถามชวน comment\n"
            "แต่ละ bullet: 1-2 ประโยค ภาษาพูดธรรมดา relatable\n"
            "จบด้วย hashtag 3-4 อัน\n"
            "ห้าม ** markdown ห้ามอวยเกินจริง ตอบแค่ caption"
        )
    else:
        # ─── Discovery formula — ▪️ bullet narrative ──────────────────
        prompt = (
            f"Interesting fact/news post from r/{subreddit}\n"
            f"Subject visible: {subject}\n"
            f"{vibe_line}\n"
            f"{title_line}\n\n"
            + REALISM_FILTER +
            "Write a high-engagement Facebook caption in THAI based on this fact/news. Use a '▪️ bullet narrative' style:\n"
            "Start each bullet point with a ▪️ emoji. Generate 6-8 bullet points in total. 1-2 sentences per bullet.\n"
            "Structure of the narrative:\n"
            "▪️ 1-2: Hook — A shocking claim, modern tech news, or fascinating fact to stop the user from scrolling. Introduce who, what, and where (based on the image and original post title).\n"
            "▪️ 3-4: Context & Explanation — How it works, the background details, or why this happened. Bring in real-world facts (tech, science, history, or business details depending on the post topic).\n"
            "▪️ 5-6: Wow details — Mind-blowing statistics, comparisons, or details that make people say 'wow'.\n"
            "▪️ 7-8: Relatable Engagement — Connect this fact/news to a funny, sarcastic, or relatable human angle (e.g. office syndrome, manager struggles, money wastage, or daily life habits) to stimulate comments and shares.\n\n"
            "Tone: Casual, engaging, informative, and slightly sarcastic/humorous (ภาษาพูดธรรมดา ทั่วไป ไม่เป็นทางการ ไม่เก๊กเท่, เหมือนคนทั่วไปบ่นหรือเล่าเรื่องฮาๆ ให้ฟัง).\n"
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
                caption = make_caption(None, video_post["title"], "", video_post["subreddit"], video_post["title"])
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

    subject, vibe = analyze_image(img_path, reddit_title=post["title"])
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

    caption = make_caption(img_path, subject, vibe, post["subreddit"], post.get("title", ""))
    caption += f"\n📷 via r/{post['subreddit']}"
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
