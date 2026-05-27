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
PAGE_ID           = os.environ.get("PAGE_ID", "116701184708556")
TEXT_MODELS       = ["gemini-2.5-flash", "gemini-3.5-flash"]
OUTPUT_DIR        = "output"
EXCEL_PATH        = os.path.join(os.path.dirname(__file__), "review_products.xlsx")
ACCENT_COLOR      = (0, 191, 255) # ฟ้า #00BFFF สำหรับกรามค้าง

if not GEMINI_API_KEY:
    try:
        from config import GEMINI_API_KEY, PAGE_ACCESS_TOKEN
    except ImportError:
        pass

os.makedirs(OUTPUT_DIR, exist_ok=True)
client = genai.Client(api_key=GEMINI_API_KEY)

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

def extract_highlights(detail, promo):
    """ให้ AI สกัดจุดเด่นจาก raw detail"""
    prompt = (
        f"จากรายละเอียดสินค้านี้:\n{detail}\n\n"
        f"สกัดออกมาเป็น bullet points ภาษาไทยสั้นๆ 3-5 จุดเด่น "
        f"เน้นประโยชน์ที่คนซื้อสนใจ ห้ามใส่ข้อมูลราคาหรือโปรโมชั่น "
        f"ตอบแค่ bullet points เท่านั้น"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            highlights = resp.text.strip()
            break
        except Exception as e:
            print(f"[{model}] highlights failed: {str(e)[:80]}")
    else:
        raise RuntimeError("Highlights generation failed on all models")
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
        f"โครงสร้างคำตอบที่ต้องการ:\n"
        f"✅ ดี: [สรุปจุดดีเด่นๆ ของสินค้า 2-3 บรรทัดสั้นๆ]\n"
        f"⚠️ ข้อเสีย: [สรุปข้อควรระวังหรือข้อเสียอย่างจริงใจ 1-2 บรรทัด]\n"
        f"💡 คุ้มไหม: [สรุปสั้นๆ ว่าคุ้มค่าเหมาะกับใคร]\n\n"
        f"เขียนให้น่าอ่าน สั้นกระชับ เป็นกันเอง ท้ายโพสต์ใส่แฮชแท็ก 2-3 อัน\n"
        f"ห้ามใส่ markdown ** ตัวหนา และตอบเฉพาะตัวโพสต์รีวิวเท่านั้น"
    )
    for model in TEXT_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            caption = resp.text.strip()
            lines = caption.splitlines()
            while lines and (
                re.search(r'^(ได้เลย|นี่คือ|แน่นอน|โพสต์รีวิว|ครับ|ค่ะ|---)', lines[0].strip(), re.IGNORECASE)
                or lines[0].strip() in ("", "---")
            ):
                lines.pop(0)
            caption = "\n".join(lines).strip()
            caption += f"{promo_line}\n\n👉 Shopee → {shopee}{lazada_line}"
            return caption
        except Exception as e:
            print(f"[{model}] caption generation failed: {e}")
    raise RuntimeError("Caption generation failed on all models")

def post_to_page(img_path, caption):
    print("Posting to Facebook Page...")
    with open(img_path, "rb") as f:
        resp = requests.post(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
            data={"access_token": PAGE_ACCESS_TOKEN, "caption": caption, "published": "true"},
            files={"source": ("review.png", f, "image/png")}
        )
    result = resp.json()
    if "id" in result:
        post_id = result.get("post_id") or result["id"]
        print(f"Page Posted! ID: {post_id}")
        print(f"https://www.facebook.com/{post_id}")
        return post_id
    else:
        print(f"FB Error: {result}")
        raise SystemExit(1)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run without posting or marking as done")
    args = parser.parse_args()

    product, wb, ws = load_next_product()
    if not product:
        print("ไม่มีสินค้าที่ต้องโพส (ครบแล้วหรือยังไม่ได้เพิ่ม)")
        raise SystemExit(0)

    print(f"Product #{product['no']}: {product['detail'][:60]}...")

    promo_clean = clean_promo(product["promo"])
    highlights  = extract_highlights(product["detail"], promo_clean)
    print(f"Highlights:\n{highlights}\n")

    line1, line2 = generate_hook(product["detail"], highlights)
    print(f"Hook generated: {line1} | {line2}")

    product_img = download_image(product["image_url"])
    
    # PIL Overlay
    try:
        review_img = add_overlay(product_img, line1, line2, ACCENT_COLOR)
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
        print(f"Dry run complete. Local image path: {review_img}")
    else:
        post_to_page(review_img, caption)
        if os.path.exists(review_img):
            os.unlink(review_img)
        mark_posted(wb, ws, product["row"])
