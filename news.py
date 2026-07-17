# -*- coding: utf-8 -*-
"""news.py — ดึงข่าวเทคโนโลยีและเรื่องราวน่าสนใจจาก Reddit แปลเป็นไทยด้วย Gemini Vision ทำรูปพาดหัว แล้วโพสต์ลง FB"""

import sys
import io
import os
import re
import time
import random
import argparse
import requests
import feedparser
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from google import genai
from google.genai import types
from overlay_utils import add_overlay

# === CONFIG (ดึงจาก env vars หรือ config.py) ===
GOOGLE_API_KEY    = os.environ.get("GOOGLE_API_KEY", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
PAGE_ID           = os.environ.get("PAGE_ID", "111830598532037")
TEXT_MODELS       = ["gemini-flash-latest", "gemini-flash-latest"]
OUTPUT_DIR        = "output"
ACCENT_COLOR      = (11, 47, 29)  # Gold/Yellow สำหรับ Rocket21

if not GOOGLE_API_KEY:
    try:
        from config import GOOGLE_API_KEY, PAGE_ACCESS_TOKEN, PAGE_ID
    except ImportError:
        pass

API_ENABLED = True

os.makedirs(OUTPUT_DIR, exist_ok=True)
client = genai.Client(api_key=GOOGLE_API_KEY, http_options={'timeout': 15000.0})

# --- Thai Helpers and Fallbacks ---
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

def contains_thai(text):
    if not text:
        return False
    return bool(re.search(r'[\u0e00-\u0e7f]', text))

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
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            import time; time.sleep(2)
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
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            import time; time.sleep(2)
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
    if not text:
        return ""
    if contains_thai(text):
        return text
    prompt = f"Translate the following interesting, weird, or amazing news/story text to natural Thai. Only output the translation, no explanation:

{text}"
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            import time; time.sleep(2)
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            translated = resp.text.strip()
            if contains_thai(translated):
                return translated
        except Exception as e:
            print(f"[{model}] Translation failed: {e}")
    return text  # Fallback to original text if translation fails

FALLBACK_NEWS = [
    {
        "line1": "ความสำเร็จขั้นสุด",
        "line2": "นักวิทย์ผลิตแบตเตอรี่โซลิดสเตตสำเร็จ",
        "caption": "นักวิทยาศาสตร์ประสบความสำเร็จในการพัฒนาแบตเตอรี่โซลิดสเตต (Solid-State Battery) รุ่นใหม่ที่มีความหนาแน่นพลังงานสูงกว่าเดิมถึง 2 เท่า และสามารถชาร์จเต็มได้ภายในเวลาเพียง 5 นาทีครับ\n\nเทคโนโลยีนี้คาดว่าจะถูกนำมาใช้งานในรถยนต์ไฟฟ้า (EV) ยุคถัดไป ซึ่งจะช่วยแก้ปัญหาเรื่องระยะเวลาการชาร์จและเพิ่มความปลอดภัยอย่างมาก เนื่องจากไม่มีของเหลวไวไฟอยู่ภายในเหมือนแบตเตอรี่ลิเธียมไอออนทั่วไปครับ\n\nทุกท่านคิดว่าเทคโนโลยีแบตเตอรี่ใหม่นี้จะเปลี่ยนโฉมวงการรถยนต์ไฟฟ้าได้เร็วแค่ไหนครับ ลองคอมเมนต์คุยกันได้เลยครับ\n\n#เทคโนโลยี #แบตเตอรี่ #รถยนต์ไฟฟ้า"
    },
    {
        "line1": "เทคโนโลยีสุดล้ำ",
        "line2": "จีนสร้างศูนย์ข้อมูล AI ใต้น้ำเป็นที่แรก",
        "caption": "วิศวกรจีนประสบความสำเร็จในการจัดตั้งศูนย์ข้อมูล (Data Center) สำหรับ AI ใต้ทะเลลึกเพื่อใช้ประโยชน์จากน้ำทะเลเย็นในการช่วยระบายความร้อนให้กับเครื่องเซิร์ฟเวอร์ครับ\n\nการย้ายศูนย์ข้อมูลลงใต้น้ำช่วยประหยัดพลังงานไฟฟ้าที่ใช้ในระบบหล่อเย็นได้มากกว่า 40% และยังช่วยประหยัดพื้นที่บนบกที่มีราคาสูงอีกด้วย โดยระบบทั้งหมดถูกออกแบบมาให้ทนทานต่อแรงดันน้ำและการกัดกร่อนของเกลือทะเลได้เป็นอย่างดีครับ\n\nทุกท่านคิดว่าไอเดียการสร้างดาต้าเซ็นเตอร์ใต้น้ำแบบนี้จะกลายเป็นมาตรฐานใหม่ในอนาคตไหมครับ\n\n#ศูนย์ข้อมูลใต้น้ำ #ปัญญาประดิษฐ์ #เทคโนโลยีจีน"
    },
    {
        "line1": "การค้นพบใหม่",
        "line2": "นาซาพบเบาะแสน้ำเหลวบนดาวอังคาร",
        "caption": "ยานสำรวจรุ่นล่าสุดขององค์การนาซา (NASA) ได้ค้นพบหลักฐานใหม่ที่บ่งชี้ถึงการมีอยู่ของแหล่งน้ำไหลที่เป็นของเหลวใต้พื้นผิวดาวอังคารในอดีต ซึ่งอาจเป็นกุญแจสำคัญในการค้นหาสิ่งมีชีวิตนอกโลกครับ\n\nข้อมูลระบุว่าน้ำดังกล่าวอาจมีความเค็มจัดจนไม่แข็งตัวภายใต้อุณหภูมิที่หนาวเย็นของดาวอังคาร ทำให้นักวิทยาศาสตร์มีความหวังมากขึ้นในการส่งภารกิจสำรวจที่มีมนุษย์ควบคุมไปลงจอดในพื้นที่ดังกล่าวในอนาคตครับ\n\nคิดว่าเราจะได้เห็นมนุษย์คนแรกไปเหยียบดาวอังคารภายในทศวรรษนี้ไหมครับ ลองแบ่งปันมุมมองกันได้ครับ\n\n#นาซา #ดาวอังคาร #ดาราศาสตร์"
    }
]

# --- แหล่งข่าวซับเรดดิตยอดนิยม (เน้นเทคโนโลยี วิทยาศาสตร์ และเรื่องราวน่าสนใจระดับโลก) ---
NEWS_SUBREDDITS = ["interestingasfuck", "Damnthatsinteresting", "weird", "nottheonion", "mildlyinteresting", "todayilearned"]

def get_reddit_image(entry):
    """สกัดรูปภาพประกอบจาก feed entry ของ Reddit"""
    # 1. เช็ก media_thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get("url", "")
        if url and "redd.it" in url:
            return url

    # 2. ค้นหารูปในเนื้อหา (summary/content)
    for field in ["summary", "content"]:
        text = ""
        if field == "content" and hasattr(entry, "content"):
            text = entry.content[0].value
        elif field == "summary" and hasattr(entry, "summary"):
            text = entry.summary
        urls = re.findall(r'<img[^>]+src="([^"]+)"', text)
        for url in urls:
            if "redd.it" in url:
                return url
    return None

def fetch_top_candidates():
    """ดึงข่าวอันดับแรก (Hottest) ที่มีรูปภาพจากแต่ละ Subreddit เพื่อนำมาเป็นตัวเลือกข่าว"""
    candidates = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    for sub in NEWS_SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/.rss"
        print(f"Fetching RSS from r/{sub} for curation...")
        try:
            feed = feedparser.parse(url, request_headers=headers)
            # สแกนเรียงลำดับความร้อนแรงจากบนลงล่าง (Hot to Cold)
            for entry in feed.entries:
                img_url = get_reddit_image(entry)
                if not img_url:
                    continue
                
                # ตรวจสอบความถูกต้องของรูปภาพประกอบ
                try:
                    resp = requests.get(img_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code != 200:
                        continue
                    content_type = resp.headers.get("Content-Type", "")
                    if not content_type.startswith("image/"):
                        continue
                    img_bytes = resp.content
                    Image.open(BytesIO(img_bytes)).verify()
                    
                    candidates.append({
                        "img_bytes": img_bytes,
                        "reddit_title": getattr(entry, "title", ""),
                        "subreddit": sub,
                        "link": getattr(entry, "link", "")
                    })
                    print(f"-> Candidate found from r/{sub}: {entry.title[:60]}")
                    break # เอาเฉพาะข่าวท็อปสุด 1 ข่าวต่อซับเรดดิตที่ผ่านเกณฑ์รูป
                except Exception as e:
                    print(f"Verify failed for candidate from r/{sub}: {e}")
                    continue
        except Exception as e:
            print(f"Failed to fetch RSS for r/{sub}: {e}")
            
    return candidates

def select_best_news_candidate(candidates):
    """ส่งหัวข้อข่าวตัวเลือกทั้งหมดให้ Gemini คัดเลือกข่าวที่น่าสนใจและมีแววไวรัลสูงสุดสำหรับคนไทย"""
    import json
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
        
    prompt = (
        "จากรายชื่อหัวข้อข่าวเทคโนโลยี/วิทยาศาสตร์/เรื่องน่าสนใจรอบโลกภาษาอังกฤษด้านล่างนี้:\n\n"
    )
    for idx, c in enumerate(candidates):
        prompt += f"[{idx}] (Subreddit: r/{c['subreddit']}): {c['reddit_title']}\n"
        
    prompt += (
        "\nจงวิเคราะห์และเลือกข่าวเด่นเพียง 1 ข่าวที่มีความน่าสนใจ แปลกใหม่ ชวนตะลึง หรือมีโอกาสที่จะสร้างความไวรัล (Viral) และกระตุ้นให้ผู้ใหญ่ชาวไทยวัยทำงาน (อายุ 30+) เข้ามาเขียนคอมเมนต์พูดคุย/ถกเถียงกันในเพจมากที่สุด\n"
        "ตอบกลับในรูปแบบ JSON เท่านั้น โดยมีคีย์ดังนี้:\n"
        "{\n"
        "  \"selected_index\": <ตัวเลขดัชนีของข่าวที่เลือก เช่น 0, 1, 2...>\n"
        "}"
    )
    
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            import time; time.sleep(2)
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            data = json.loads(resp.text.strip())
            idx = int(data.get("selected_index", 0))
            if 0 <= idx < len(candidates):
                selected = candidates[idx]
                print(f"[{model}] selected candidate [{idx}]: {selected['reddit_title']}")
                return selected
        except Exception as e:
            print(f"[{model}] candidate selection failed: {e}")
            
    # Fallback สุ่มดึง
    chosen = random.choice(candidates)
    print(f"Fallback selected candidate: {chosen['reddit_title']}")
    return chosen


def generate_news_content(img_bytes, reddit_title, sub, original_link):
    """ส่งให้ Gemini Vision ช่วยแปล วิเคราะห์ และแต่งข้อความพาดหัว+แคปชั่นข่าวในสไตล์แอดมินเพจผู้ชาย"""
    prompt = (
        f"This image is from the Reddit thread: '{reddit_title}' in r/{sub}.\n"
        "Analyze the Reddit title and the image together to understand the context. Then, generate highly engaging, informative tech/science news content in Thai.\n"
        "Output format must have exactly 3 sections separated by labels:\n"
        "===HOOK1=== [Hook Line 1: very short, 3-5 Thai words, e.g. 'จะรอดไหม', 'เทคโนโลยีใหม่', 'สุดล้ำ', 'ความจริงวันนี้']\n"
        "===HOOK2=== [Hook Line 2: very short, 4-7 Thai words, describing the core event or a dilemma, e.g. 'เอไอเตรียมแทนที่คน']\n"
        "===CAPTION=== [Facebook Caption: A detailed, highly engaging explanation structured in 1-2 paragraphs. Reframe the news context around everyday adulting, work-life, productivity, job stability, or financial struggles of 30+ year olds (e.g., if it is AI news, highlight job replacement fears; if it is remote work, compare remote vs office work; if it is gadgets, discuss tech costs/worth). Write in the friendly, talkative male persona of 'กรามค้าง' who loves sharing interesting/mysterious/funny stories from around the world. Use 'ครับ' and 'ผม' or 'พี่'. You MUST end the caption with a direct, reply-eliciting question (e.g., 'คิดยังไงกันบ้างครับเรื่องนี้?', 'เป็นพี่ๆ จะกล้าลองไหมครับ?') Absolutely NO markdown bolding (**), NO bullet points, lists, or symbols like ▪️ or - anywhere. Include hashtags and citation.]\n\n"
        "Requirements:\n"
        "- Write in natural, fluent Thai.\n"
        "- Maintain strict factual accuracy. Do not fabricate or speculate. Use real numbers or data if mentioned.\n"
        "- Hook lines and caption must be logical and consistent.\n"
        "- Do not use any markdown bolding (**) in the caption.\n"
        "- Absolutely no bullet points or lists of any kind.\n"
    )

    part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
    
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            import time; time.sleep(2)
        for attempt in range(3):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[part, prompt]
                )
                result = resp.text.strip()
                print(f"Gemini Response [{model}]:\n{result[:500]}...\n")

                line1 = "ข่าวใหม่วันนี้"
                line2 = ""
                caption = ""

                h1_match = re.search(r'===HOOK1===\s*(.*)', result, re.IGNORECASE)
                h2_match = re.search(r'===HOOK2===\s*(.*)', result, re.IGNORECASE)
                cap_match = re.search(r'===CAPTION===\s*(.*)', result, re.DOTALL | re.IGNORECASE)

                if h1_match:
                    line1 = h1_match.group(1).split('\n')[0].strip()
                if h2_match:
                    line2 = h2_match.group(1).split('\n')[0].strip()
                if cap_match:
                    caption = cap_match.group(1).strip()

                # คลีนป้ายกำกับที่อาจปนมาบนภาพพาดหัว
                label_pattern = r'^(ข้อความในโพสต์\s*Facebook|Facebook\s*Caption|Facebook\s*caption|Caption|caption|ข้อความบนรูป|ข้อความในรูป|ข้อความ|คำบรรยาย|คำอธิบาย|บรรทัดที่\s*\d+|บรรทัด\s*\d+|ประโยคที่\s*\d+|ประโยค\s*\d+|Hook\s*text|Hook|Line\s*\d+|[L|l]ine\s*\d+|\d+)\s*[:\-\.\s]\s*'
                line1 = re.sub(label_pattern, '', line1, flags=re.IGNORECASE).strip()
                line2 = re.sub(label_pattern, '', line2, flags=re.IGNORECASE).strip()
                line1 = line1.strip('"\'“”‘’')
                line2 = line2.strip('"\'“”‘’')

                # ประกอบที่มาของข่าว
                if original_link:
                    caption += f"\n.\nที่มา: {original_link}"

                return line1, line2, caption, False
            except Exception as e:
                print(f"[{model}] attempt {attempt + 1} failed: {e}")
                time.sleep(5)
                
    # Fallback if all models and attempts fail
    translated_title = translate_to_thai(reddit_title)
    if contains_thai(translated_title):
        line1 = "ข่าวเด่นวันนี้"
        line2 = translated_title[:30] if len(translated_title) <= 30 else translated_title[:27] + "..."
        caption = f"{translated_title}\n\nรายละเอียดเพิ่มเติมกำลังตามมาครับ ติดตามอัปเดตข่าวสารเทคโนโลยีกับพวกเราได้เลยครับ\n\n#เทคโนโลยี #ข่าวสาร"
        if original_link:
            caption += f"\n.\nที่มา: {original_link}"
        return line1, line2, caption, False

    fb = random.choice(FALLBACK_NEWS)
    caption = fb["caption"]
    if original_link:
        caption += f"\n.\nที่มา: {original_link}"
    return fb["line1"], fb["line2"], caption, True

def post_facebook(img_path, caption):
    """โพสต์รูปภาพข่าวพร้อมแคปชั่นลงเพจ Facebook"""
    print("Posting to Facebook...")
    try:
        api_url = f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos"
        with open(img_path, "rb") as f:
            resp = requests.post(
                api_url,
                data={"access_token": PAGE_ACCESS_TOKEN, "caption": caption, "published": "true"},
                files={"source": ("news.png", f, "image/png")},
                timeout=60,
            )
        result = resp.json()
        if "id" in result:
            post_id = result.get("post_id") or result["id"]
            print(f"Posted Successfully! ID: {post_id}")
            add_comment(post_id, caption=caption, img_path=img_path)
            return post_id
        else:
            print(f"Post failed: {result}")
            return None
    except Exception as e:
        print(f"Facebook API error: {e}")
        return None

def add_comment(post_id, caption=None, img_path=None):
    """คอมเมนต์ลิงก์สินค้าแนะนำหรือข้อมูลสมาชิกร่วมกันหลังจากโพสต์"""
    try:
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
                f"https://graph.facebook.com/v25.0/{post_id}/comments",
                data=data,
                timeout=30
            )
            result = resp.json()
            if "id" in result:
                print(f"Comment {i} added: {result['id']}")
            else:
                print(f"Comment {i} error: {result}")
            if i < len(comments):
                time.sleep(random.uniform(30, 90))
    except Exception as e:
        print(f"Failed to post comments: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run locally without posting to Facebook")
    args = parser.parse_args()

    print("=== Rocket21 News Bot ===")
    
    # ดึงข่าวท็อปของแต่ละซับเรดดิตมาเป็นทางเลือก
    candidates = fetch_top_candidates()
    if not candidates:
        print("No news candidates found.")
        sys.exit(0)
        
    news_posted = False
    
    while candidates:
        # ให้ Gemini เลือกข่าวที่ดีที่สุดและมีแนวโน้มได้รับความนิยมสูงสุด
        news = select_best_news_candidate(candidates)
        if not news:
            break
            
        print(f"\nEvaluating Curation Winner: r/{news['subreddit']}")
        print(f"Title: {news['reddit_title']}")
        
        # Verify if image matches the title
        if not verify_image_title_match(news["img_bytes"], news["reddit_title"]):
            print(f"[Warning] Image and Title mismatch for: '{news['reddit_title']}'. Removing from candidates and trying next best.")
            candidates.remove(news)
            continue
            
        # ดำเนินการโพสต์ข่าว
        temp_path = "temp_news.jpg"
        with open(temp_path, "wb") as f:
            f.write(news["img_bytes"])

        # เจนเนอเรตเนื้อหาข่าว
        line1, line2, caption, is_static_fallback = generate_news_content(
            news["img_bytes"], 
            news["reddit_title"], 
            news["subreddit"],
            news["link"]
        )
        # ถ้า Gemini ล้มเหลวจนต้องใช้ static canned news -> ข้าม candidate นี้
        # ไม่โพส (เพราะจะได้รูปดำ + caption ที่ไม่ตรงกับ ที่มา reddit link) ลองตัวถัดไปแทน
        if is_static_fallback:
            print("[Skip] Gemini content generation failed (static fallback). Skipping this candidate to avoid posting a black canned card with a mismatched source link.")
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            candidates.remove(news)
            continue
        line1 = segment_thai_text(line1, client)
        line2 = segment_thai_text(line2, client)
        print(f"Hook generated: {line1} | {line2}")
        print(f"Caption:\n{caption}\n")

        # ใส่ overlay ข้อความบนรูปภาพ
        out_path = os.path.join(OUTPUT_DIR, f"news_{int(time.time())}.jpg")
        try:
            img_to_overlay = None if is_static_fallback else temp_path
            final_img = add_overlay(img_to_overlay, line1, line2, accent_color=ACCENT_COLOR, out_path=out_path)
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            print(f"Overlay created: {final_img}")
        except Exception as e:
            print(f"Overlay failed: {e}")
            final_img = None if is_static_fallback else temp_path

        # โพสต์หรือหยุดทำแห้ง (dry-run)
        if args.dry_run:
            print(f"Dry-run mode complete. Local image path: {final_img}")
        else:
            post_facebook(final_img, caption)
            if os.path.exists(final_img):
                os.unlink(final_img)
        
        news_posted = True
        break

    if not news_posted:
        print("No suitable news found after evaluating candidates.")

if __name__ == "__main__":
    main()
