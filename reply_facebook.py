# -*- coding: utf-8 -*-
"""reply_facebook.py — ตรวจสอบและตอบกลับคอมเมนต์บน Facebook Page ด้วย Gemini อัจฉริยะ"""

import sys, io, os, time, random, re, requests
from google import genai

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# === PAGE CONFIGURATIONS & PERSONAS ===
PAGE_CONFIGS = {
    "chowchow": {
        "name": "Chow Chow",
        "page_id": "102319399434080",
        "token_env": "CHOWCHOW_PAGE_ACCESS_TOKEN",
        "system_instruction": "คุณคือแอดมินน้องหมา Chow Chow ของเพจ Chow Chow (เพจรีวิวสินค้าสัตว์เลี้ยงแสนน่ารัก ขี้เล่น อารมณ์ดี)\n"
                              "ตอบกลับโดยแทนตัวว่า 'น้องหมา' หรือ 'โฮ่ง' หรือ 'ผม' และใช้คำลงท้ายตระกูลสุนัขเช่น 'ครับโฮ่ง', 'ฮะโฮ่ง', 'ครับ' เท่านั้น ห้ามลืมเด็ดขาด\n"
                              "เน้นความตลก ขี้เล่น และทำตัวเหมือนหมาคุยกับคน คุยเล่นเป็นกันเองสุดๆ",
        "fallbacks": [
            "โฮ่ง! ขอบคุณที่เอ็นดูพวกเราครับโฮ่ง 🐶",
            "แฮ่ๆ เรื่องนี้ผมเห็นด้วยเลยครับโฮ่ง!",
            "มีของอร่อย/ของเล่นใหม่มาบอกผมด้วยนะฮะโฮ่ง 🦴",
            "ขอบคุณมากครับโฮ่ง ไว้มาคุยกันอีกน้า บ๊อกๆ"
        ]
    },
    "kram": {
        "name": "กรามค้าง",
        "page_id": "116701184708556",
        "token_env": "KRAM_PAGE_ACCESS_TOKEN",
        "system_instruction": "คุณคือแอดมินเพจ กรามค้าง (เพจแชร์เรื่องเล่าสไตล์ Pantip, เรื่องลี้ลับ, เรื่องชาวบ้าน ตลกขบขัน เสียดสีสังคม)\n"
                              "ตอบกลับด้วยบุคลิกผู้ชายเป็นกันเอง (แทนตัวว่า 'ผม' หรือ 'พี่' และใช้คำลงท้ายว่า 'ครับ' เท่านั้น)\n"
                              "เน้นการคุยแบบเข้าอกเข้าใจ แอบแซวขำๆ หรือเม้าท์มอยสไตล์คนชอบเผือกเรื่องตลกๆ",
        "fallbacks": [
            "จริงครับพี่ เรื่องนี้พูดอีกก็ถูกอีก 😂",
            "โหยยย เรื่องนี้ต่อมเผือกผมทำงานเลยครับ",
            "เฉียบเลยครับประโยคนี้ โดนใจผมเต็มๆ",
            "ขอบคุณที่มาแชร์มุมมองกันครับพี่ ไว้มาร่วมกรามค้างกันอีกนะ"
        ]
    },
    "somtam": {
        "name": "พริก 10 เม็ด",
        "page_id": "554501167740603",
        "token_env": "SOMTAM_PAGE_ACCESS_TOKEN",
        "system_instruction": "คุณคือแอดมินเพจ พริก 10 เม็ด (เพจรีวิวของกิน ของแซ่บ และเรื่องดราม่าวงการอาหารแบบเผ็ดร้อนแต่ตลกขบขัน)\n"
                              "ตอบกลับด้วยบุคลิกผู้หญิงแอดมินสุดแซ่บ (แทนตัวว่า 'พี่' หรือ 'เรา' หรือ 'พริก' และใช้คำลงท้ายว่า 'ค่ะ' หรือ 'คะ' เท่านั้น ห้ามลืมเด็ดขาด)\n"
                              "คุยเล่นแบบตลก เป็นกันเอง แอบเหน็บแนมวงการของกินขำๆ หรือพูดถึงเรื่องความอร่อย/ความเผ็ดร้อน",
        "fallbacks": [
            "จริงค่ะ เรื่องนี้แซ่บระดับพริก 10 เม็ดเลย 😂",
            "เห็นด้วยเลยค่ะ พูดแล้วน้ำลายสอเลยเนอะ",
            "เฉียบมากค่ะประโยคนี้ โดนใจทีมงานพริก 10 เม็ดสุดๆ",
            "ขอบคุณที่มาคอมเมนต์คุยกันนะคะ ไว้มากินส้มตำแซ่บๆ กันน้า"
        ]
    },
    "rocket": {
        "name": "Rocket21",
        "page_id": "111830598532037",
        "token_env": "PAGE_ACCESS_TOKEN",
        "system_instruction": "คุณคือแอดมินเพจ Rocket21 (เพจบันทึกชีวิตคนทำงาน การเงิน และสัจธรรมชีวิตสู้ชีวิตตลกๆ เป็นกันเองมาก)\n"
                              "ตอบกลับโดยสุ่มบุคลิกเป็นกันเอง (ใช้ 'ผม'/'ครับ' หรือ 'พี่'/'ค่ะ' ตามความเหมาะสม)\n"
                              "คุยสั้นๆ ง่ายๆ เกี่ยวกับประเด็นชีวิตคนทำงาน การสู้ชีวิต และเรื่องเงินๆ ทองๆ แบบตลกขบขันสู้ชีวิต",
        "fallbacks": [
            "จริงครับพี่ เรื่องสู้ชีวิตนี่พูดอีกก็ถูกอีก 😂",
            "สู้ๆ ครับผม ค่อยๆ ปรับตัวกันไปเนอะ ✌️",
            "เฉียบครับประโยคนี้ โดนใจคนทำงานสู้ชีวิตแบบผมเลย",
            "ขอบคุณที่มาแชร์มุมมองกันครับพี่ ไว้มาร่วมพูดคุยกันอีกนะครับ"
        ]
    },
    "default": {
        "name": "แอดมินเพจ",
        "page_id": "",
        "token_env": "PAGE_ACCESS_TOKEN",
        "system_instruction": "คุณคือแอดมินเพจผู้เป็นมิตร ตอบกลับคอมเมนต์อย่างเป็นกันเองและสุภาพ",
        "fallbacks": [
            "ขอบคุณที่มาแสดงความคิดเห็นและแชร์มุมมองร่วมกันนะครับ/ค่ะ"
        ]
    }
}

# --- Auto-Detect Repo Context ---
cwd = os.getcwd().lower().replace("\\", "/")
if "chowchow" in cwd:
    page_key = "chowchow"
elif "kram" in cwd:
    page_key = "kram"
elif "somtam" in cwd:
    page_key = "somtam"
elif "rocket" in cwd:
    page_key = "rocket"
else:
    page_key = "default"

cfg = PAGE_CONFIGS[page_key]
print(f"Auto-detected page context: {cfg['name']} (Key: {page_key})")

# === LOAD API KEYS & TOKENS ===
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PAGE_ACCESS_TOKEN = os.environ.get(cfg["token_env"], "")

# If specific env var was empty, try fallback env vars
if not PAGE_ACCESS_TOKEN:
    PAGE_ACCESS_TOKEN = (
        os.environ.get("PAGE_ACCESS_TOKEN") or
        os.environ.get("CHOWCHOW_PAGE_ACCESS_TOKEN") or
        os.environ.get("KRAM_PAGE_ACCESS_TOKEN") or
        os.environ.get("SOMTAM_PAGE_ACCESS_TOKEN") or
        ""
    )

# Fallback to config.py for local testing
try:
    import config
    if not GEMINI_API_KEY:
        GEMINI_API_KEY = getattr(config, "GEMINI_API_KEY", "")
    if not PAGE_ACCESS_TOKEN:
        PAGE_ACCESS_TOKEN = getattr(config, "PAGE_ACCESS_TOKEN", PAGE_ACCESS_TOKEN)
        # Check specific config tokens
        if page_key == "somtam":
            PAGE_ACCESS_TOKEN = getattr(config, "SOMTAM_PAGE_ACCESS_TOKEN", PAGE_ACCESS_TOKEN)
        elif page_key == "chowchow":
            PAGE_ACCESS_TOKEN = getattr(config, "CHOWCHOW_PAGE_ACCESS_TOKEN", PAGE_ACCESS_TOKEN)
        elif page_key == "kram":
            PAGE_ACCESS_TOKEN = getattr(config, "KRAM_PAGE_ACCESS_TOKEN", PAGE_ACCESS_TOKEN)
except ImportError:
    pass

PAGE_ID = cfg["page_id"]
TEXT_MODELS       = ["gemini-1.5-flash", "gemini-1.5-flash"]
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "replied_fb_comments.txt")

if not PAGE_ACCESS_TOKEN:
    print("Error: PAGE_ACCESS_TOKEN ว่างเปล่า ไม่สามารถดำเนินงานได้")
    sys.exit(1)

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY, http_options={'timeout': 90.0})
else:
    print("Warning: GEMINI_API_KEY ว่างเปล่า จะใช้ระบบ fallback ข้อความตอบกลับ")

def load_replied_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def save_replied_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for cid in sorted(history):
            f.write(f"{cid}\n")

def get_page_details():
    """ดึง Page ID และ Name จาก /me เพื่อยืนยันความถูกต้อง"""
    url = f"https://graph.facebook.com/v21.0/me?fields=id,name&access_token={PAGE_ACCESS_TOKEN}"
    try:
        resp = requests.get(url, timeout=15)
        result = resp.json()
        if "id" in result:
            return result["id"], result.get("name", "")
        print(f"Failed to get page details: {result}")
    except Exception as e:
        print(f"Error getting page details: {e}")
    return "", ""

def get_recent_posts(p_id):
    """ดึงโพสต์ล่าสุด 5 โพสต์จาก Page Feed"""
    url = f"https://graph.facebook.com/v21.0/{p_id}/feed?fields=id,message,created_time&limit=5&access_token={PAGE_ACCESS_TOKEN}"
    try:
        resp = requests.get(url, timeout=15)
        result = resp.json()
        if "data" in result:
            return result["data"]
        print(f"Failed to get feed: {result}")
    except Exception as e:
        print(f"Error getting feed: {e}")
    return []

def get_post_comments(post_id):
    """ดึงคอมเมนต์ใต้โพสต์"""
    url = f"https://graph.facebook.com/v21.0/{post_id}/comments?fields=id,message,from,created_time&limit=25&access_token={PAGE_ACCESS_TOKEN}"
    try:
        resp = requests.get(url, timeout=15)
        result = resp.json()
        if "data" in result:
            return result["data"]
        print(f"Failed to get comments for {post_id}: {result}")
    except Exception as e:
        print(f"Error getting comments for {post_id}: {e}")
    return []

def is_valid_comment(text):
    """กรองคอมเมนต์สั้น แท็กเพื่อน หรือไม่มีเนื้อหา"""
    if not text:
        return False
    clean = text.strip()
    # ข้ามพวกแท็กเพื่อน (เริ่มด้วย @ หรือมีรูปชื่อแท็ก)
    if clean.startswith("@") or re.match(r'^@\w+\s*$', clean):
        return False
    # ข้ามคอมเมนต์สั้นเกินไป เช่น "555", "โอเค", "ดี"
    if len(clean) < 4:
        return False
    # ข้ามคอมเมนต์ที่มีแค่อีโมจิล้วนๆ
    if not re.search(r'[a-zA-Zก-๙0-9]', clean):
        return False
    return True

def generate_reply(post_text, commenter_name, comment_text):
    """ใช้ Gemini สร้างคำตอบตาม Persona"""
    if not client:
        return random.choice(cfg["fallbacks"])

    prompt = (
        f"{cfg['system_instruction']}\n\n"
        f"โพสต์หลักมีข้อความดังนี้:\n\"\"\"\n{post_text}\n\"\"\"\n\n"
        f"มีลูกเพจชื่อ \"{commenter_name}\" เข้ามาคอมเมนต์ใต้โพสต์นี้ว่า:\n\"\"\"\n{comment_text}\n\"\"\"\n\n"
        "กรุณาเขียนข้อความตอบกลับลูกเพจคนนี้อย่างเป็นธรรมชาติและเป็นกันเองเหมือนมนุษย์จริงๆ คุยเล่นกัน:\n"
        "กฎในการตอบ:\n"
        "1. อ่านและตอบกลับให้ตรงบริบทและประเด็นที่ลูกเพจคอมเมนต์มาโดยเฉพาะ (ห้ามเฉไฉไปพูดเรื่องอื่น)\n"
        "2. ตอบสั้นและเป็นกันเอง 1-2 ประโยคสั้นๆ เท่านั้น (ห้ามยาว ยืดเยื้อ หรือเป็นทางการเด็ดขาด)\n"
        "3. ห้ามใช้ markdown ** ตัวหนา หรือเครื่องหมายอัญประกาศครอบข้อความ\n"
        "4. สามารถใส่อีโมจิตลกๆ สู้ชีวิต ที่เข้ากับเรื่องได้ 1-2 ตัวอย่างเป็นธรรมชาติ"
    )
    
    for model_idx, model in enumerate(TEXT_MODELS):
        if model_idx > 0:
            import time; time.sleep(2)
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            result = resp.text.strip()
            result = result.strip('"\'“”‘’')
            if result:
                return result
        except Exception as e:
            print(f"[{model}] reply generation failed: {e}")
            
    return random.choice(cfg["fallbacks"])

def post_reply_comment(comment_id, text):
    """ส่งโพสต์ตอบกลับคอมเมนต์"""
    url = f"https://graph.facebook.com/v21.0/{comment_id}/comments"
    data = {
        "message": text,
        "access_token": PAGE_ACCESS_TOKEN
    }
    try:
        resp = requests.post(url, data=data, timeout=15)
        result = resp.json()
        if "id" in result:
            return result["id"]
        print(f"Error posting comment reply: {result}")
    except Exception as e:
        print(f"Error posting reply: {e}")
    return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without posting reply or saving history")
    args = parser.parse_args()

    print("=== Facebook AI Auto-Reply System ===")
    
    # 1. ยืนยันเพจผ่าน token
    api_page_id, page_name = get_page_details()
    if api_page_id:
        print(f"Token is valid for Page: {page_name} (ID: {api_page_id})")
        PAGE_ID = api_page_id
    else:
        if PAGE_ID:
            print(f"Warning: Could not fetch page name. Proceeding with fallback Page ID: {PAGE_ID}")
        else:
            print("Error: ไม่พบ Page ID ทั้งจากการดึงผ่าน API หรือจาก Config ของเพจ")
            sys.exit(1)

    history = load_replied_history()
    print(f"Loaded {len(history)} replied comment history.")

    posts = get_recent_posts(PAGE_ID)
    if not posts:
        print("No recent posts found on page feed.")
        sys.exit(0)

    reply_count = 0
    max_replies_per_run = 3  # จำกัดตอบสูงสุด 3 คอมเมนต์ต่อรอบรัน
    reply_probability = 0.4  # โอกาสสุ่มตอบ 40%

    for post in posts:
        post_id = post["id"]
        post_text = post.get("message", "")
        print(f"\nChecking Post [{post_id}]: \"{post_text[:50]}...\"")
        
        comments = get_post_comments(post_id)
        if not comments:
            print("  No comments found under this post.")
            continue
            
        print(f"  Found {len(comments)} total comments.")
        
        for comment in comments:
            comment_id = comment["id"]
            comment_text = comment.get("message", "")
            
            # ดึงข้อมูลผู้คอมเมนต์
            commenter_info = comment.get("from", {})
            commenter_id = commenter_info.get("id", "")
            commenter_name = commenter_info.get("name", "ลูกเพจ")
            
            # 1. ข้ามถ้าเคยตอบไปแล้ว
            if comment_id in history:
                continue
                
            # 2. ข้ามคอมเมนต์ของตัวเราเอง (แอดมินตอบคอมเมนต์ตัวเอง)
            if commenter_id and commenter_id == PAGE_ID:
                continue
                
            # 3. ข้ามคอมเมนต์ที่ไม่ผ่านเกณฑ์ความยาว/แท็กเพื่อน
            if not is_valid_comment(comment_text):
                print(f"  - Skip trivial comment from {commenter_name}: \"{comment_text}\"")
                continue
                
            print(f"  - New valid comment from {commenter_name}: \"{comment_text}\"")
            
            # 4. สุ่มตามสัดส่วนความน่าจะเป็น (เช่น 40%)
            if random.random() > reply_probability:
                print("    [Chance skipped] Random selection decided not to reply to this one.")
                # ถือว่าประมวลผลแล้ว เพื่อไม่ให้จมอยู่กับคอมเมนต์เดิมในรอบถัดไป
                if not args.dry_run:
                    history.add(comment_id)
                continue

            # 5. เจนคำตอบด้วย AI
            print("    Generating AI reply...")
            reply_msg = generate_reply(post_text, commenter_name, comment_text)
            print(f"    AI Reply message: \"{reply_msg}\"")
            
            # 6. ตอบกลับคอมเมนต์
            if args.dry_run:
                print("    [Dry-run] Simulated reply. Not posting to API.")
            else:
                sent_id = post_reply_comment(comment_id, reply_msg)
                if sent_id:
                    print(f"    Reply posted successfully! ID: {sent_id}")
                    history.add(comment_id)
                    reply_count += 1
                else:
                    print("    Failed to post reply.")
            
            # เช็คว่าเต็มโควตาการตอบในรอบนี้หรือยัง
            if reply_count >= max_replies_per_run:
                print("\nReached max replies quota per run. Stopping.")
                break
                
        if reply_count >= max_replies_per_run:
            break

    if not args.dry_run and reply_count > 0:
        save_replied_history(history)
        print(f"\nCompleted! Saved updated history with {reply_count} new replies.")
    else:
        print("\nFinished (No actual replies posted or run under --dry-run).")
