# -*- coding: utf-8 -*-
"""review.py — generate รูปรีวิวสินค้าจาก review_products.xlsx แล้วโพส FB"""

import sys, io, os, base64, requests, time, random, re
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from google import genai
import openpyxl
from overlay_utils import add_overlay

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY",    "")
PAGE_ACCESS_TOKEN = os.environ.get("KRAM_PAGE_ACCESS_TOKEN", "")
PAGE_ID           = "116701184708556"
TEXT_MODELS       = ["gemini-2.5-flash", "gemini-3.5-flash"]
OUTPUT_DIR        = "output"
EXCEL_PATH        = os.path.join(os.path.dirname(__file__), "review_products.xlsx")
AFFILIATE_DIR     = os.path.join(os.path.dirname(__file__), "affiliate_data")
ACCENT_COLOR      = (0, 191, 255) # ฟ้า #00BFFF สำหรับกรามค้าง

if not GEMINI_API_KEY:
    try:
        from config import GEMINI_API_KEY, PAGE_ACCESS_TOKEN
    except ImportError:
        pass

os.makedirs(OUTPUT_DIR, exist_ok=True)
client = genai.Client(api_key=GEMINI_API_KEY, http_options={'timeout': 60000.0})

def load_next_product():
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active
    for row in ws.iter_rows(min_row=2, values_only=False):
        no    = row[0].value
        detail= row[1].value
        shopee= row[2].value
        lazada= row[3].value
        imgurl= row[4].value
        promo = row[5].value
        posted= row[6].value

        # ข้าม sample row และ posted แล้ว
        if not detail or "วางรายละเอียด" in str(detail):
            continue
        if str(posted).strip().lower() == "done" or str(posted).strip().startswith("done"):
            continue
        if not shopee or "xxx" in str(shopee):
            continue

        return {
            "row": row[0].row,
            "no": no,
            "detail": str(detail).strip(),
            "shopee": str(shopee).strip(),
            "lazada": str(lazada).strip() if lazada else "",
            "image_url": str(imgurl).strip() if imgurl else "",
            "promo": str(promo).strip() if promo else "",
        }, wb, ws
    return None, wb, ws

def mark_posted(wb, ws, row_num):
    bkk = timezone(timedelta(hours=7))
    ts = datetime.now(bkk).strftime("%Y-%m-%d %H:%M")
    ws.cell(row=row_num, column=7, value=f"done {ts}")
    wb.save(EXCEL_PATH)
    print(f"Marked row {row_num} as done")

def clean_promo(raw):
    """เอาเฉพาะบรรทัดที่มี ฿ หรือ ลด หรือ % หรือ ส่งฟรี"""
    if not raw:
        return ""
    lines = raw.strip().splitlines()
    kept = [l.strip() for l in lines if re.search(r'฿|ลด|%|ส่งฟรี|flash|sale', l, re.IGNORECASE)]
    return " | ".join(kept[:3]) if kept else ""

def get_allowed_xlsx_files():
    path = os.path.abspath(__file__).replace("\\", "/")
    if "chowchow" in path:
        return ["สัตว์เลี้ยง.xlsx"]
    elif "somtam" in path:
        return ["อาหารและเครื่องดื่ม.xlsx"]
    elif "rocket" in path:
        return ["เครื่องใช้ไฟฟ้าภายในบ้าน.xlsx"]
    elif "x-bot" in path:
        return ["สินค้าขายดี.xlsx"]
    else:  # kram-facebook-page
        return ["เครื่องใช้ในบ้าน.xlsx", "ค่าคอมพิเศษ.xlsx", "เสื้อผ้าแฟชั่นผู้หญิง.xlsx", "สินค้าสำหรับเม้นใต้คลิป.xlsx"]

def get_posted_urls(ws):
    urls = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 4:
            continue
        shopee = row[2]
        lazada = row[3]
        if shopee and str(shopee).strip().startswith("http"):
            urls.add(str(shopee).strip())
        if lazada and str(lazada).strip().startswith("http"):
            urls.add(str(lazada).strip())
    return urls

def append_posted_fallback(wb, ws, product):
    bkk = timezone(timedelta(hours=7))
    ts = datetime.now(bkk).strftime("%Y-%m-%d %H:%M")
    row_num = ws.max_row + 1
    
    ws.cell(row=row_num, column=1, value=product["no"])
    ws.cell(row=row_num, column=2, value=product["detail"])
    ws.cell(row=row_num, column=3, value=product["shopee"])
    ws.cell(row=row_num, column=4, value=product["lazada"])
    ws.cell(row=row_num, column=5, value=product["image_url"])
    ws.cell(row=row_num, column=6, value=product["promo"])
    ws.cell(row=row_num, column=7, value=f"done {ts}")
    
    wb.save(EXCEL_PATH)
    print(f"Appended fallback product to review_products.xlsx at row {row_num}")

def load_affiliate_product(posted_urls):
    """Fallback: สุ่มสินค้าจาก AFFILIATE_DIR เมื่อ review_products.xlsx หมด"""
    import glob
    allowed_names = get_allowed_xlsx_files()
    xlsx_files = []
    for name in allowed_names:
        p = os.path.join(AFFILIATE_DIR, name)
        if os.path.exists(p):
            xlsx_files.append(p)
            
    # Fallback to any xlsx files if no mapped files exist
    if not xlsx_files:
        xlsx_files = glob.glob(os.path.join(AFFILIATE_DIR, "*.xlsx"))
        
    if not xlsx_files:
        print(f"[affiliate] No xlsx files found in {AFFILIATE_DIR}")
        return None
        
    random.shuffle(xlsx_files)
    for xlsx_path in xlsx_files:
        try:
            wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
            ws = wb.active
            candidates = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or len(row) < 10:
                    continue
                name   = row[1]
                imgurl = row[2]
                price  = row[3]
                shopee = row[9]
                lazada = row[10] if len(row) > 10 else None
                if not shopee or not name:
                    continue
                
                shopee_val = str(shopee).strip()
                lazada_val = str(lazada).strip() if lazada else ""
                
                # Check against posted URLs
                if shopee_val in posted_urls or (lazada_val and lazada_val in posted_urls):
                    continue
                    
                candidates.append({
                    "no": row[0],
                    "detail": f"{name} ราคา {price} บาท",
                    "shopee": shopee_val,
                    "lazada": lazada_val,
                    "image_url": str(imgurl).strip() if imgurl else "",
                    "promo": "",
                    "row": None,
                })
            wb.close()
            if candidates:
                product = random.choice(candidates)
                print(f"[affiliate] Loaded from {os.path.basename(xlsx_path)}: {product['detail'][:60]}")
                return product
        except Exception as e:
            print(f"[affiliate] Failed to read {xlsx_path}: {e}")
    print("[affiliate] No valid product found in any xlsx file")
    return None


def extract_highlights(detail, promo):
    """ให้ AI สกัดจุดเด่นจาก raw detail"""
    highlights = None
    prompt = (
        f"จากรายละเอียดสินค้านี้:\n{detail}\n\n"
        f"สกัดจุดเด่นสินค้าเป็นประโยคข้อความสั้นแนวธรรมชาติ 1-2 ย่อหน้าสั้นๆ (ห้ามทำเป็นข้อๆ หรือมีสัญลักษณ์รายการ/bullet points เช่น •, ▪️, - หรือเลขข้อ) "
        f"เน้นประโยชน์ที่คนซื้อสนใจและใช้งานจริง ห้ามใส่ข้อมูลราคาหรือโปรโมชั่น "
        f"ตอบเฉพาะส่วนรายละเอียดเนื้อความเท่านั้น"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            highlights = resp.text.strip()
            if highlights:
                break
        except Exception as e:
            err_msg = str(e)
            print(f"[{model}] highlights failed: {err_msg[:80]}")
            if any(x in err_msg.lower() for x in ["api key not valid", "permission_denied", "api_key_invalid"]):
                break
    if not highlights:
        print("[Warning] Highlights AI failed, using local fallback.")
        lines = [l.strip() for l in detail.splitlines() if l.strip()]
        points = []
        for line in lines:
            cleaned = re.sub(r'^[•\-\*\d\.\s–]+', '', line).strip()
            if cleaned and 5 < len(cleaned) < 100:
                points.append(cleaned)
            if len(points) >= 3:
                break
        if not points:
            points = [line[:80] for line in lines[:2]]
        highlights = " ".join(points) if points else "รายละเอียดเพิ่มเติมศึกษาต่อได้ที่หน้าร้านเลยครับ"
    if promo:
        highlights += f"\n🔥 โปรตอนนี้: {promo}"
    return highlights

def download_image(url):
    """Download รูปแรกจาก URL"""
    first_url = url.strip().split("\n")[0].strip()
    resp = requests.get(first_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code == 200:
        bkk = timezone(timedelta(hours=7))
        ts = datetime.now(bkk).strftime("%Y%m%d_%H%M%S")
        ext = "webp" if "webp" in first_url else "jpg"
        path = os.path.join(OUTPUT_DIR, f"product_{ts}.{ext}")
        with open(path, "wb") as f:
            f.write(resp.content)
        print(f"Product image downloaded: {path}")
        return path
    raise RuntimeError(f"Image download failed: {resp.status_code}")

def generate_hook(detail, highlights):
    """สร้างหัวข้อสั้นพาดหัวรูปภาพ 2 บรรทัด คั่นด้วย '|'"""
    prompt = (
        f"จากรายละเอียดสินค้าต่อไปนี้:\n{detail}\n\n"
        f"จุดเด่นสินค้าที่สกัดแล้ว:\n{highlights}\n\n"
        "กรุณาสร้างคำพาดหัวโฆษณารีวิวสินค้านี้ภาษาไทยสั้นๆ 2 บรรทัด คั่นด้วยเครื่องหมาย pipe '|' (บรรทัด 1 | บรรทัด 2)\n"
        "กฎในการร่าง:\n"
        "- บรรทัด 1: คำโปรย/ชื่อเล่นสุดปังสไตล์วัยรุ่นหรือคนทำงานขำขัน (3-5 คำ)\n"
        "- บรรทัด 2: เหตุผลโดนใจ/จุดเด่นในการแก้ปัญหา (4-7 คำ)\n"
        "- ห้ามใช้เครื่องหมายคำพูด อัญประกาศ หรือข้อความนำหน้า/ตามหลังใดๆ\n"
        "- ห้ามมี Emoji ปนในหัวข้อนี้เด็ดขาด\n"
        "ตัวอย่าง: เบาะรองนั่งสู้ชีวิต | นั่งทำงาน 10 ชม. ไม่ปวดหลัง"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            result = resp.text.strip()
            label_pattern = r'^(ข้อความในโพสต์\s*Facebook|Facebook\s*Caption|Facebook\s*caption|Caption|caption|ข้อความบนรูป|ข้อความในรูป|ข้อความ|คำบรรยาย|คำอธิบาย|บรรทัดที่\s*\d+|บรรทัด\s*\d+|ประโยคที่\s*\d+|ประโยค\s*\d+|Hook\s*text|Hook|Line\s*\d+|[L|l]ine\s*\d+|\d+)\s*[:\-\.\s]\s*'
            result = re.sub(label_pattern, '', result, flags=re.IGNORECASE).strip()
            result = result.strip('"\'“”‘’')
            if "|" in result:
                parts = result.split("|", 1)
                line1 = parts[0].strip()
                line2 = parts[1].strip()
                return line1, line2
            else:
                return result[:15], ""
        except Exception as e:
            print(f"[{model}] hook generation failed: {e}")
    # Smart local fallback for hook
    first_line = detail.split('\n')[0].strip()
    first_line = re.sub(r'[\[\]\(\)]', '', first_line)
    first_line = re.sub(r'^[•\-\*\d\.\s–]+', '', first_line).strip()
    _specs = ['ราคา', 'แพ็ค', 'ขนาด', 'สำหรับ', 'จำนวน', 'กรัม', 'ลิตร', ' ml', ' kg', ' g ', ',']
    _stop = len(first_line)
    for _kw in _specs:
        _idx = first_line.find(_kw)
        if _idx > 2:
            _stop = min(_stop, _idx)
    short_title = first_line[:_stop].strip()
    words = short_title.split()
    line1 = "สินค้าแนะนำ"
    for n in (3, 2, 1):
        candidate = " ".join(words[:n]) if words else "สินค้าแนะนำ"
        if len(candidate) <= 20 or n == 1:
            line1 = candidate
            break
    price_m = re.search(r'ราคา\s*([\d,]+(?:\.\d+)?)\s*บาท', detail)
    if price_m:
        line2 = f"ราคา {price_m.group(1)} บาท"
    else:
        feat_lines = [l.strip() for l in detail.splitlines() if l.strip() and l.strip() != first_line.strip()]
        feat_lines = [re.sub(r'^[•\-\*\d\.\s–]+', '', l).strip() for l in feat_lines]
        feat_lines = [l for l in feat_lines if 5 < len(l) < 60]
        line2 = feat_lines[0][:20] if feat_lines else ""
    return line1, line2

def generate_caption(detail, shopee, lazada, promo, highlights):
    promo_line = f"\n🔥 โปรโมชั่น: {promo}" if promo else ""
    lazada_line = f"\n🛍️ Lazada → {lazada}" if lazada and "xxx" not in lazada else ""
    import hashlib as _hs_p
    _seed_p = int(_hs_p.md5(detail.encode()).hexdigest()[:8], 16)
    _archetypes_p = [
        "เพื่อนที่เพิ่งซื้อมาใช้แล้ว อยากแชร์ให้รู้จัก ไม่ได้ขายของ",
        "คนที่มีปัญหาในชีวิตประจำวัน แล้วบังเอิญเจอสินค้าตัวนี้ช่วยแก้",
        "คนที่เจอราคาดีหรือโปรน่าสนใจ กลัวเพื่อนพลาดเลยรีบบอก",
        "คนที่ใช้มาสักพักแล้ว มาเล่าประสบการณ์จริงๆ ให้ฟัง",
    ]
    _archetype_p = _archetypes_p[_seed_p % 4]
    prompt = (
        f"คุณคือ{_archetype_p} ไม่ใช่นักขาย ไม่ใช่แอดมินเพจ ใช้คำลงท้ายว่า 'ครับ' และสรรพนาม 'ผม'\n"
        f"ก่อนเขียน ให้คิดก่อนว่า: สินค้านี้แก้ปัญหาอะไรในชีวิตประจำวัน คนซื้อเพราะอะไร จุดไหนที่ทำให้รู้สึกว่า 'น่าสนใจ'\n\n"
        f"รายละเอียดสินค้า:\n{detail}\n\n"
        f"เขียน Facebook post ตามลำดับนี้:\n"
        f"1. เปิดด้วยปัญหาหรือความรู้สึก — ห้ามขึ้นต้นด้วยชื่อสินค้าหรือแบรนด์\n"
        f"2. เล่าว่าเจออะไร สั้นๆ\n"
        f"3. พูดถึงสินค้า — ใช้ชื่อแบรนด์หรือชื่อย่อเท่านั้น ห้าม copy title เต็มจาก Shopee\n"
        f"4. บอกเหตุผลที่ชอบ 1-2 จุด จากมุมผู้ใช้จริง\n"
        f"5. จบด้วย 'ดูลิ้งในคอมเมนต์แรกเลยครับ 👇'\n\n"
        f"ความยาว: 3-5 ประโยค\n"
        f"ห้ามใช้: คุ้มมาก, ของมันต้องมี, รีบซื้อ, โปรโมชั่น, สั่งได้เลย, อย่าพลาด, ไม่ควรพลาด\n"
        f"ห้าม copy ชื่อสินค้าเต็มจาก Shopee, ห้าม bullet points, ห้าม **, ห้ามสเปกยาวๆ\n"
        f"ตอบเฉพาะตัวโพสต์เท่านั้น ไม่ต้องพูดอะไรนำหน้า"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            caption = resp.text.strip()
            lines = caption.splitlines()
            while lines and (
                re.search(r'^(ได้เลย|นี่คือ|จริง|แน่นอน|โพสต์รีวิว|ครับ|ค่ะ|---)', lines[0].strip(), re.IGNORECASE)
                or lines[0].strip() in ("", "---")
            ):
                lines.pop(0)
            caption = "\n".join(lines).strip()
            if promo:
                caption += promo_line
            return caption
        except Exception as e:
            print(f"[{model}] caption generation failed: {e}")
    # local fallback caption
    import hashlib as _hs
    _seed = int(_hs.md5(detail.encode()).hexdigest()[:8], 16)
    _price_m = re.search(r'ราคา\s*([\d,]+(?:\.\d+)?)\s*บาท', detail)
    _price_str = f"\n\nราคาแค่ {_price_m.group(1)} บาท" if _price_m else ""
    _fallback_templates = [
        f"เจอของดีมาบอกต่อ ลองใช้แล้วชอบครับ{_price_str}\n\nดูลิ้งในคอมเมนต์แรก 👇",
        f"มีปัญหาแบบนี้อยู่เหมือนกัน เพิ่งหาทางออกเจอครับ{_price_str}\n\nรายละเอียดในคอมเมนต์แรก 👇",
        f"นานๆ จะเจอของดีราคานี้ แปะไว้ก่อนครับ{_price_str}\n\nดูในคอมเมนต์แรก 👇",
        f"ใช้มาพักนึงแล้ว ดีกว่าที่คิดไว้ครับ{_price_str}\n\nดูลิ้งในคอมเมนต์แรก 👇",
    ]
    caption = _fallback_templates[_seed % 4]
    if promo:
        caption += f"\n🔥 โปร: {promo}"
    return caption

def _post_one_comment(post_id, text):
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v21.0/{post_id}/comments",
            data={"access_token": PAGE_ACCESS_TOKEN, "message": text},
            timeout=30
        )
        result = resp.json()
        if "id" in result:
            print(f"Comment posted: {result['id']}")
        else:
            print(f"Comment failed: {result}")
    except Exception as e:
        print(f"Comment error: {e}")

def post_link_comment(post_id, shopee, lazada, promo):
    """โพส comment ลิ้งใต้โพส แยก Shopee / Lazada คนละคอมเม้น"""
    promo_line = f"\n🔥 โปร: {promo}" if promo else ""
    if shopee and "xxx" not in shopee:
        _post_one_comment(post_id, f"👉 ซื้อได้ที่ Shopee → {shopee}{promo_line}")
    if lazada and "xxx" not in lazada:
        _post_one_comment(post_id, f"🛍️ หรือสั่งทาง Lazada → {lazada}")

def post_to_page(img_path, caption, shopee=None, lazada=None, promo=None, scheduled_timestamp=None):
    print("Posting to Facebook Page...")
    from affiliate_utils import get_next_scheduled_time

    if scheduled_timestamp is not None:
        scheduled_time = scheduled_timestamp
    else:
        slots = ["08:00"]
        scheduled_time = get_next_scheduled_time(slots)
    
    if scheduled_time:
        comment_texts = []
        promo_line = f"\n🔥 โปร: {promo}" if promo else ""
        if shopee and "xxx" not in shopee:
            comment_texts.append(f"👉 ซื้อได้ที่ Shopee → {shopee}{promo_line}")
        if lazada and "xxx" not in lazada:
            comment_texts.append(f"🛍️ หรือสั่งทาง Lazada → {lazada}")
            
        if comment_texts:
            caption += "\n\n📌 ชี้เป้าของดีน่าสนใจ:\n" + "\n".join(comment_texts)
            
        print(f"Scheduling to Facebook for timestamp {scheduled_time}...")
        with open(img_path, "rb") as f:
            resp = requests.post(
                f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
                data={
                    "access_token": PAGE_ACCESS_TOKEN,
                    "message": caption,
                    "published": "false",
                    "unpublished_content_type": "SCHEDULED",
                    "scheduled_publish_time": scheduled_time
                },
                files={"source": ("review.png", f, "image/png")},
                timeout=60
            )
        result = resp.json()
        if "id" in result:
            photo_id = result.get("post_id") or result["id"]
            print(f"Scheduled successfully! Photo ID: {photo_id}")
            return photo_id, True
        else:
            print(f"FB Error: {result}")
            raise SystemExit(1)

    with open(img_path, "rb") as f:
        resp = requests.post(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
            data={"access_token": PAGE_ACCESS_TOKEN, "message": caption, "published": "true"},
            files={"source": ("review.png", f, "image/png")},
            timeout=60
        )
    result = resp.json()
    if "id" in result:
        post_id = result.get("post_id") or result["id"]
        print(f"Page Posted! ID: {post_id}")
        print(f"https://www.facebook.com/{post_id}")
        return post_id, False
    else:
        print(f"FB Error: {result}")
def extract_badge_text(promo):
    if not promo:
        return None
    pct_match = re.search(r'(ลด\s*\d+\s*%)|(\d+\s*%\s*OFF)', promo, re.IGNORECASE)
    if pct_match:
        val = pct_match.group(0)
        val = re.sub(r'\s+', ' ', val)
        return val
    price_match = re.search(r'฿\s*\d+', promo)
    if price_match:
        return price_match.group(0).replace(" ", "")
    return None


if __name__ == "__main__":
    import argparse
    import time as _time

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without posting or marking as done")
    args = parser.parse_args()

    IMMEDIATE = os.environ.get("IMMEDIATE", "false").lower() == "true"

    bkk = timezone(timedelta(hours=7))
    now_bkk = datetime.now(bkk)

    # Pre-calculate 5 timestamps: 05:00/08:00/11:00/14:00/17:00 BKK
    # IMMEDIATE=true (workflow_dispatch) -> post now, no scheduling
    slot_times = ["05:00", "08:00", "11:00", "14:00", "17:00"]
    def make_slot_ts(slot_str):
        if IMMEDIATE:
            return None
        h, m = map(int, slot_str.split(":"))
        dt = now_bkk.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt <= now_bkk:
            dt += timedelta(days=1)
        return int(dt.timestamp())

    slot_timestamps = [make_slot_ts(s) for s in slot_times]
    posted_this_run = set()

    for i, sched_ts in enumerate(slot_timestamps):
        print(f"\n--- Post {i+1}/5 (slot {slot_times[i]}) ---")

        product, wb, ws = load_next_product()
        affiliate_mode = False
        if not product:
            print("review_products.xlsx หมดแล้ว — ลอง fallback จาก AFFILIATE_DIR")
            posted_urls = get_posted_urls(ws)
            product = load_affiliate_product(posted_urls)
            affiliate_mode = True
            if not product:
                print("ไม่มีสินค้าเหลือ หยุด")
                break

        if product.get("shopee") in posted_this_run:
            print(f"[Skip] ซ้ำใน run นี้: {str(product.get('shopee',''))[:60]}")
            continue

        print(f"Product: {product['detail'][:60]}...")

        promo_clean = clean_promo(product["promo"])
        highlights  = extract_highlights(product["detail"], promo_clean)

        line1, line2 = generate_hook(product["detail"], highlights)
        print(f"Hook: {line1} | {line2}")

        product_img = download_image(product["image_url"])

        try:
            badge_text = extract_badge_text(product.get("promo"))
            review_img = add_overlay(
                product_img, line1, line2, ACCENT_COLOR,
                font_name="Itim-Regular.ttf",
                badge_text=badge_text,
                watermark="คราม Kram"
            )
            os.unlink(product_img)
            print(f"Review image overlaid: {review_img}")
        except Exception as overlay_err:
            print(f"Overlay failed, using original image: {overlay_err}")
            review_img = product_img

        caption = generate_caption(
            product["detail"], product["shopee"],
            product["lazada"], promo_clean, highlights
        )
        print(f"Caption:\n{caption}\n")

        if args.dry_run:
            print(f"Dry run post {i+1}. image={review_img}")
            print(f"Link: 👉 Shopee → {product['shopee']}")
            posted_this_run.add(product.get("shopee"))
        else:
            post_id, was_scheduled = post_to_page(
                review_img, caption,
                product["shopee"], product["lazada"], promo_clean,
                scheduled_timestamp=sched_ts
            )
            posted_this_run.add(product.get("shopee"))
            if os.path.exists(review_img):
                os.unlink(review_img)
            if not was_scheduled:
                post_link_comment(post_id, product["shopee"], product["lazada"], promo_clean)
            if not affiliate_mode:
                mark_posted(wb, ws, product["row"])
            else:
                append_posted_fallback(wb, ws, product)
            _time.sleep(5)

