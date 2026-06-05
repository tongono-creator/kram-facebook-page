# -*- coding: utf-8 -*-
"""review.py — generate รูปรีวิวสินค้าจาก review_products.xlsx แล้วโพส FB"""

import sys, io, os, base64, requests, time, random, re, json
from datetime import datetime, timezone, timedelta
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from google import genai
from google.genai import types
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
    return "สินค้าแนะนำ", ""

def generate_caption(detail, shopee, lazada, promo, highlights):
    promo_line = f"\n🔥 โปรโมชั่น: {promo}" if promo else ""
    lazada_line = f"\n🛍️ Lazada → {lazada}" if lazada and "xxx" not in lazada else ""
    prompt = (
        f"เขียน Facebook post ภาษาไทยรีวิวสินค้าอย่างตรงไปตรงมาและน่าอ่าน สไตล์เพจรีวิวชื่อดัง (เช่น CatDumb)\n"
        "เขียนด้วยบุคลิกแอดมินผู้ชาย (ใช้คำลงท้ายว่า 'ครับ' และแทนตัวว่า 'ผม' หรือ 'พี่' เท่านั้น)\n"
        f"รายละเอียดสินค้า:\n{detail}\n\n"
        f"จุดเด่นสินค้า:\n{highlights}\n\n"
        f"คุณต้องเขียนรีวิวโดยใช้เทคนิค 3 ขั้นตอนดังนี้:\n"
        f"1. เปิดให้น่าสนใจ (Hook): ประโยคเปิดหัวพาดหัวเรื่องให้น่าตื่นเต้น จี้ใจ ดึงดูดให้อยากอ่านต่อทันที\n"
        f"2. เล่าให้เห็นภาพ (Vivid Storytelling): รีวิวคุณสมบัติเด่น ประสิทธิภาพการใช้งานจริง หรือผลลัพธ์หลังจากใช้แล้วให้เห็นภาพชัดเจน\n"
        f"3. ปิดจบต้องบอกว่า 'ควรทำอะไร' (Call to Action): บอกให้สั่งซื้อโดยการกดที่ตะกร้า ชี้เป้าลิงก์ หรือบอกว่ามีโปรโมชั่นจัดหนักอยู่\n\n"
        f"เขียนให้น่าอ่าน สั้นกระชับ เป็นกันเอง ท้ายโพสต์ใส่แฮชแท็ก 2-3 อัน\n"
        f"ห้ามใช้ markdown ตัวหนา (**) และห้ามมีสัญลักษณ์หัวข้อย่อยหรือ bullet points (เช่น •, ▪️, -) เด็ดขาด เขียนอธิบายไหลลื่นเป็นย่อหน้าธรรมชาติเท่านั้น ตอบเฉพาะตัวแคปชั่นรีวิวเท่านั้น"
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
    first_few = " ".join([l.strip() for l in detail.splitlines() if l.strip()][:3])
    caption = (
        f"สวัสดีครับ วันนี้มีสินค้าดีๆ มาแนะนำครับ!\n\n"
        f"{first_few} บอกเลยว่าตอบโจทย์ชีวิตประจำวันมากครับ {highlights}\n\n"
        f"ใครสนใจกดลิ้งคอมเมนต์แรกได้เลยครับ 👇"
    )
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

def post_to_page(img_path, caption, shopee=None, lazada=None, promo=None):
    print("Posting to Facebook Page...")
    from affiliate_utils import get_next_scheduled_time
    
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
        raise SystemExit(1)

def get_product_metadata(name, detail):
    prompt = (
        f"วิเคราะห์สินค้าสำหรับทำการตลาด:\n"
        f"ชื่อสินค้า: {name}\n"
        f"รายละเอียด: {detail}\n\n"
        "เราจะสร้างภาพโฆษณารีวิวสินค้าสไตล์อินโฟกราฟิกเด่น (Infographic ad card) ขนาด 1080x1080 พิกเซล\n"
        "หน้าที่ของคุณคือ สรุปจุดเด่นของสินค้าและวางแผนคำพาดหัว คุณลักษณะเด่น และการชี้จุดขายบนรูป\n"
        "ตอบกลับในรูปแบบ JSON เท่านั้น ห้ามเขียนคำนำ ห้ามเขียนสรุป ห้ามใส่ markdown block (เช่น ```json) ตอบเฉพาะ JSON ดิบตามโครงสร้างนี้:\n"
        "{\n"
        "  \"imagen_prompt\": \"Detailed English prompt for Imagen 4.0. Describe the product accurately and place it center-focused on a clean, professional, premium lifestyle background (e.g. minimalist room, home desk). ABSOLUTELY NO text, watermarks, or overlays inside the image.\",\n"
        "  \"headline_line1\": \"พาดหัวแถว 1 ชวนดึงดูด (ไม่เกิน 5-6 คำภาษาไทย, เช่น 'พัดลมไร้สายพกพา!')\",\n"
        "  \"headline_line2\": \"พาดหัวแถว 2 ขยายจุดเด่นหลัก (ไม่เกิน 5-6 คำภาษาไทย, เช่น 'เย็นนาน 24 ชั่วโมง พกพาสะดวก')\",\n"
        "  \"features\": [\n"
        "    {\n"
        "      \"icon\": \"Emoji สัญลักษณ์ เช่น 🔋 หรือ 💡 หรือ 🌀 ที่ตรงกับฟีเจอร์\",\n"
        "      \"text_line1\": \"ฟีเจอร์สั้นแถว 1 (2-3 คำ)\",\n"
        "      \"text_line2\": \"ฟีเจอร์สั้นแถว 2 (2-3 คำ)\"\n"
        "    },\n"
        "    ... (ต้องมีครบ 3 ฟีเจอร์พอดี)\n"
        "  ],\n"
        "  \"callouts\": [\n"
        "    {\n"
        "      \"text\": \"คำชี้จุดเด่นสั้นมาก (1-3 คำ เช่น 'ปรับหมุนได้ 90°')\",\n"
        "      \"x\": 180,       # พิกัด X ของตัวกล่องข้อความชี้เป้า (ช่วง 100 - 300 หรือ 780 - 980)\n"
        "      \"y\": 450,       # พิกัด Y ของตัวกล่องข้อความชี้เป้า (ช่วง 300 - 750)\n"
        "      \"point_x\": 450, # พิกัด X ที่ต้องการให้เส้นชี้ไปหาจุดเด่นบนตัวสินค้า (ช่วง 400 - 680)\n"
        "      \"point_y\": 500  # พิกัด Y ที่ต้องการให้เส้นชี้ไปหาจุดเด่นบนตัวสินค้า (ช่วง 400 - 680)\n"
        "    },\n"
        "    ... (มี 2-3 จุดที่ชี้ไปยังตัวสินค้า)\n"
        "  ]\n"
        "}"
    )
    
    last_err = None
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt
            )
            raw = resp.text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\n", "", raw)
                raw = re.sub(r"\n```$", "", raw)
                raw = raw.strip()
            return json.loads(raw)
        except Exception as e:
            last_err = e
    raise last_err

def generate_base_image(prompt):
    print("Calling Imagen to generate base product photo...")
    response = client.models.generate_images(
        model='imagen-4.0-fast-generate-001',
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="1:1",
            output_mime_type="image/jpeg"
        )
    )
    image_bytes = response.generated_images[0].image.image_bytes
    from PIL import Image
    return Image.open(io.BytesIO(image_bytes))

def draw_infographic(img, meta):
    from PIL import ImageDraw, ImageFont
    W, H = img.size
    draw = ImageDraw.Draw(img)
    
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "Itim-Regular.ttf")
    emoji_font_path = r"C:\Windows\Fonts\seguiemj.ttf"
    
    font_hl = ImageFont.truetype(font_path, 42)
    font_feat_title = ImageFont.truetype(font_path, 24)
    font_callout = ImageFont.truetype(font_path, 22)
    
    if os.path.exists(emoji_font_path):
        font_emoji = ImageFont.truetype(emoji_font_path, 36)
    else:
        font_emoji = font_feat_title
        
    # ── 1. Draw Headline at the Top ──────────────────────────────────────────
    text_hl = f"{meta['headline_line1']}\n{meta['headline_line2']}"
    hl_bbox = draw.textbbox((0, 0), text_hl, font=font_hl, align="center")
    hl_w = hl_bbox[2] - hl_bbox[0]
    hl_h = hl_bbox[3] - hl_bbox[1]
    
    rect_padding_x = 40
    rect_padding_y = 20
    rect_w = hl_w + rect_padding_x * 2
    rect_h = hl_h + rect_padding_y * 2
    rect_x1 = (W - rect_w) // 2
    rect_y1 = 40
    rect_x2 = rect_x1 + rect_w
    rect_y2 = rect_y1 + rect_h
    
    # Draw shadow
    draw.rounded_rectangle([rect_x1 + 6, rect_y1 + 6, rect_x2 + 6, rect_y2 + 6], radius=30, fill=(0, 0, 0, 80))
    # Draw bubble outline
    draw.rounded_rectangle([rect_x1 - 3, rect_y1 - 3, rect_x2 + 3, rect_y2 + 3], radius=30, fill=(0, 0, 0))
    # Draw bubble body
    draw.rounded_rectangle([rect_x1, rect_y1, rect_x2, rect_y2], radius=30, fill=(255, 255, 255))
    
    # Draw text
    center_x = (rect_x1 + rect_x2) // 2
    hl_left = center_x - hl_w // 2
    hl_top = rect_y1 + rect_padding_y
    draw.text((hl_left, hl_top), text_hl, font=font_hl, fill=(0, 0, 0), align="center")
    
    # ── 2. Draw 3 Feature Boxes at the Bottom ─────────────────────────────────
    PAD_X = 50
    GAP = 30
    box_w = (W - PAD_X * 2 - GAP * 2) // 3
    box_h = 160
    box_y1 = H - box_h - 40
    box_y2 = box_y1 + box_h
    
    for idx, feat in enumerate(meta['features']):
        bx1 = PAD_X + idx * (box_w + GAP)
        bx2 = bx1 + box_w
        
        # Shadow
        draw.rounded_rectangle([bx1 + 4, box_y1 + 4, bx2 + 4, box_y2 + 4], radius=20, fill=(0, 0, 0, 80))
        # Border
        draw.rounded_rectangle([bx1 - 3, box_y1 - 3, bx2 + 3, box_y2 + 3], radius=20, fill=(0, 0, 0))
        # White background
        draw.rounded_rectangle([bx1, box_y1, bx2, box_y2], radius=20, fill=(255, 255, 255))
        
        # Draw Emoji Icon
        emoji = feat['icon']
        emoji_w = 40
        if os.path.exists(emoji_font_path):
            draw.text((bx1 + (box_w - emoji_w) // 2, box_y1 + 15), emoji, font=font_emoji, fill=(0,0,0), embedded_color=True)
        else:
            draw.text((bx1 + (box_w - emoji_w) // 2, box_y1 + 15), emoji, font=font_emoji, fill=(0,0,0))
            
        # Draw Text below emoji
        text_f = f"{feat['text_line1']}\n{feat['text_line2']}"
        f_bbox = draw.textbbox((0, 0), text_f, font=font_feat_title, align="center")
        f_w = f_bbox[2] - f_bbox[0]
        
        feat_center_x = bx1 + box_w // 2
        feat_left = feat_center_x - f_w // 2
        feat_top = box_y1 + 75
        draw.text((feat_left, feat_top), text_f, font=font_feat_title, fill=(0, 0, 0), align="center")
        
    # ── 3. Draw Callouts with Pointer Lines ───────────────────────────────────
    for callout in meta['callouts']:
        text = callout['text']
        cx = callout['x']
        cy = callout['y']
        px = callout['point_x']
        py = callout['point_y']
        
        c_bbox = draw.textbbox((0, 0), text, font=font_callout)
        c_w = c_bbox[2] - c_bbox[0]
        c_h = c_bbox[3] - c_bbox[1]
        
        pad_x = 25
        pad_y = 12
        bx1 = cx - c_w // 2 - pad_x
        by1 = cy - c_h // 2 - pad_y
        bx2 = cx + c_w // 2 + pad_x
        by2 = cy + c_h // 2 + pad_y
        
        if px < cx:
            line_start_x = bx1
        else:
            line_start_x = bx2
        line_start_y = cy
        
        # Draw shadow line
        draw.line([(line_start_x + 2, line_start_y + 2), (px + 2, py + 2)], fill=(0, 0, 0, 80), width=4)
        # Draw outline line
        draw.line([(line_start_x, line_start_y), (px, py)], fill=(0, 0, 0), width=6)
        draw.line([(line_start_x, line_start_y), (px, py)], fill=(255, 255, 255), width=3)
        
        # Draw small circle at the end of the line
        R = 6
        draw.ellipse([px - R - 1, py - R - 1, px + R + 1, py + R + 1], fill=(0, 0, 0))
        draw.ellipse([px - R, py - R, px + R, py + R], fill=(255, 255, 255))
        
        # Draw box shadow
        draw.rounded_rectangle([bx1 + 4, by1 + 4, bx2 + 4, by2 + 4], radius=15, fill=(0, 0, 0, 80))
        # Draw box outline
        draw.rounded_rectangle([bx1 - 2, by1 - 2, bx2 + 2, by2 + 2], radius=15, fill=(0, 0, 0))
        # Draw box body
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=15, fill=(255, 255, 255))
        
        # Draw text inside box
        draw.text((cx, cy - c_bbox[1] - c_h // 2), text, font=font_callout, fill=(0, 0, 0), anchor="mm")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without posting or marking as done")
    args = parser.parse_args()

    product, wb, ws = load_next_product()
    affiliate_mode = False
    if not product:
        print("review_products.xlsx หมดแล้ว — ลอง fallback จาก AFFILIATE_DIR")
        posted_urls = get_posted_urls(ws)
        product = load_affiliate_product(posted_urls)
        affiliate_mode = True
        if not product:
            print("ไม่มีสินค้าที่ต้องโพส (ครบแล้วหรือยังไม่ได้เพิ่ม)")
            raise SystemExit(0)


    print(f"Product #{product['no']}: {product['detail'][:60]}...")

    promo_clean = clean_promo(product["promo"])
    highlights  = extract_highlights(product["detail"], promo_clean)
    print(f"Highlights:\n{highlights}\n")

    review_img = None
    
    # Try generating infographic via Imagen 4.0 and Pillow drawing
    try:
        print("Extracting metadata for infographic...")
        meta = get_product_metadata(product["detail"], product["detail"])
        print(f"Metadata extracted: {json.dumps(meta, ensure_ascii=False)}")
        
        print("Generating lifestyle image...")
        base_img = generate_base_image(meta["imagen_prompt"])
        
        print("Drawing infographic overlays...")
        draw_infographic(base_img, meta)
        
        bkk = timezone(timedelta(hours=7))
        ts = datetime.now(bkk).strftime("%Y%m%d_%H%M%S")
        review_img = os.path.join(OUTPUT_DIR, f"review_{ts}.jpg")
        base_img.save(review_img, "JPEG", quality=95)
        print(f"Infographic image saved successfully: {review_img}")
    except Exception as infographic_err:
        print(f"[Warning] Infographic generation failed: {infographic_err}. Falling back to original image + overlay flow.")
        # Fallback to original flow
        try:
            line1, line2 = generate_hook(product["detail"], highlights)
            print(f"Hook generated: {line1} | {line2}")
            product_img = download_image(product["image_url"])
            review_img = add_overlay(product_img, line1, line2, ACCENT_COLOR, font_name="Itim-Regular.ttf")
            if os.path.exists(product_img):
                os.unlink(product_img)
            print(f"Fallback review image overlaid: {review_img}")
        except Exception as fallback_err:
            print(f"[Error] Fallback flow also failed: {fallback_err}")
            raise SystemExit(1)

    caption = generate_caption(
        product["detail"], product["shopee"],
        product["lazada"], promo_clean, highlights
    )
    print(f"Caption:\n{caption}\n")

    if args.dry_run:
        print(f"Dry run complete. Local image path: {review_img}")
        print(f"Link comment would be: 👉 Shopee → {product['shopee']}")
    else:
        post_id, was_scheduled = post_to_page(review_img, caption, product["shopee"], product["lazada"], promo_clean)
        if os.path.exists(review_img):
            os.unlink(review_img)
        if not was_scheduled:
            post_link_comment(post_id, product["shopee"], product["lazada"], promo_clean)
        if not affiliate_mode:
            mark_posted(wb, ws, product["row"])
        else:
            append_posted_fallback(wb, ws, product)

