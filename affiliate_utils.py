# affiliate_utils.py — อ่าน product/food links จาก affiliate_products.xlsx
import os, re, random
from datetime import datetime, timezone, timedelta

WEBSITE_URL = "https://shopee-ranking.vercel.app/"
EXCEL_PATH  = os.path.join(os.path.dirname(__file__), "affiliate_products.xlsx")

BKK = timezone(timedelta(hours=7))

def _now_bkk():
    return datetime.now(BKK)

def _rotate(items, extra_salt=0):
    """สุ่มเลือกจาก list — ไม่ซ้ำกันระหว่างโพส"""
    if not items:
        return None
    return random.choice(items)

# ─── อ่าน Excel ──────────────────────────────────────────────────
def _load_excel():
    try:
        import openpyxl
        wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
        ws = wb.active
        products, food_entries, promos = [], [], []
        today = _now_bkk().date()

        for row in ws.iter_rows(min_row=2, values_only=True):
            if len(row) < 5:
                continue
            no, name, shopee, lazada, active = row[0], row[1], row[2], row[3], row[4]
            desc     = row[5] if len(row) > 5 else ""
            food_raw = row[6] if len(row) > 6 else None
            # column H=promo_name, I=promo_url, J=promo_active, K=expiry_date
            promo_name   = row[7]  if len(row) > 7  else None
            promo_url    = row[8]  if len(row) > 8  else None
            promo_active = row[9]  if len(row) > 9  else None
            expiry_raw   = row[10] if len(row) > 10 else None

            # product rows (ต้องมี active=yes)
            if str(active).strip().lower() == "yes":
                products.append({
                    "name":   str(name or "").strip(),
                    "shopee": str(shopee or "").strip(),
                    "lazada": str(lazada or "").strip(),
                    "desc":   str(desc or "").strip(),
                })

            # food links — เก็บทุก row ที่มีค่า column G
            if food_raw:
                food_entries.append(str(food_raw).strip())

            # promo links — column H-K, เช็ค expiry อัตโนมัติ
            if (promo_name and promo_url
                    and str(promo_active or "").strip().lower() == "yes"):
                expired = False
                if expiry_raw:
                    try:
                        if hasattr(expiry_raw, "date"):
                            exp_date = expiry_raw.date()
                        else:
                            from datetime import date
                            exp_date = date.fromisoformat(str(expiry_raw).strip()[:10])
                        expired = today > exp_date
                    except Exception:
                        pass
                if not expired:
                    promos.append({
                        "name": str(promo_name).strip(),
                        "url":  str(promo_url).strip(),
                    })

        return products, food_entries, promos
    except Exception as e:
        print(f"Excel read error: {e}")
        return [], [], []

def _parse_food(raw):
    """แยก shop_name + url จาก 'ลองเข้ามาดู ShopName ที่ Shopee! https://...'"""
    url_match = re.search(r'https://\S+', raw)
    url = url_match.group(0) if url_match else raw
    name_match = re.search(r'ลองเข้ามาดู\s+(.+?)\s+ที่ Shopee', raw)
    name = name_match.group(1).strip() if name_match else "ร้านอาหาร"
    return name, url

# ─── Website comment variations ──────────────────────────────────
WEBSITE_VARS = [
    f"🔥 อยากรู้ว่าสินค้าไหนขายดีที่สุดบน Shopee?\nดูอันดับได้เลย → {WEBSITE_URL}",
    f"📊 เช็คของขายดีก่อนซื้อ ประหยัดได้เยอะ → {WEBSITE_URL}",
    f"🏆 ของขายดีอันดับ 1 บน Shopee วันนี้คืออะไร? → {WEBSITE_URL}",
    f"💡 ก่อนซื้อของออนไลน์ดูอันดับก่อนนะ → {WEBSITE_URL}",
    f"🛒 คนไทยกำลังซื้ออะไรกันเยอะที่สุด? → {WEBSITE_URL}",
    f"✅ เปรียบเทียบราคา เช็คอันดับขายดีก่อนตัดสินใจ → {WEBSITE_URL}",
]

# ─── Food comment variations ─────────────────────────────────────
FOOD_INTROS = [
    "🍜 หิวแล้วสั่งเลย! {name}\nส่งถึงบ้าน → {url}",
    "🍱 แนะนำร้านนี้เลย {name}\nสั่งผ่าน Shopee Food → {url}",
    "🔖 โปรเด็ดวันนี้! {name}\nคลิกสั่งได้เลย → {url}",
    "🛵 อยากกิน {name} ไหม?\nสั่งง่ายๆ → {url}",
    "🍔 มื้อนี้ลอง {name} ดูไหม?\nส่งถึงที่ → {url}",
    "⭐ {name} ร้านนี้ดีมาก\nสั่งผ่าน Shopee Food → {url}",
]

# ─── Shopee product comment variations ───────────────────────────
SHOPEE_INTROS = [
    "🛒 {name}{desc}\nซื้อได้บน Shopee → {url}",
    "🔥 ถ้ากำลังมองหา {name} อยู่{desc}\nที่นี่เลย → {url}",
    "💡 {name}{desc}\nราคาดีบน Shopee → {url}",
    "✅ {name}{desc}\nลองดูก่อนตัดสินใจ Shopee → {url}",
    "👀 {name}{desc}\nน่าสนใจมาก Shopee → {url}",
]

LAZADA_INTROS = [
    "🛍️ {name}{desc}\nซื้อได้บน Lazada → {url}",
    "🔥 ถ้ากำลังมองหา {name} อยู่{desc}\nที่นี่เลย → {url}",
    "💡 {name}{desc}\nราคาดีบน Lazada → {url}",
    "✅ {name}{desc}\nลองดูก่อนตัดสินใจ Lazada → {url}",
    "👀 {name}{desc}\nน่าสนใจมาก Lazada → {url}",
]

# ─── Public API ───────────────────────────────────────────────────
def get_standard_comments():
    """comment เว็บ shopee-ranking (หมุน variations)"""
    return [_rotate(WEBSITE_VARS)]

def get_food_comment():
    """comment Shopee Food หมุนเวียนทุกร้าน"""
    _, food_entries, _ = _load_excel()
    raw = _rotate(food_entries, extra_salt=3)
    if not raw:
        return None
    name, url = _parse_food(raw)
    template = _rotate(FOOD_INTROS, extra_salt=5)
    return template.format(name=name, url=url)

PRODUCT_HOOKS = [
    "ของดีราคาคุ้ม หมดแล้วหมดเลย",
    "คนซื้อเยอะมาก รีวิวดีทุกอัน",
    "ตัวนี้ใช้แล้วติดใจเลย",
    "ราคานี้หาที่ไหนไม่ได้แล้ว",
    "bestseller ขายดีอันดับต้นๆ",
    "ลูกค้าให้คะแนน 4.9/5",
    "ของแท้ 100% ส่งไวมาก",
    "คุ้มมากถ้าตอนนี้",
]

PROMO_INTROS = [
    "🔥 โปรโมชั่นพิเศษ! {name}\nรีบคว้าก่อนหมด → {url}",
    "⚡ Flash Deal วันนี้เท่านั้น {name}\nกดซื้อเลย → {url}",
    "🎯 ดีลเด็ด {name}\nราคาพิเศษจำกัดเวลา → {url}",
    "💥 โปรแรง {name}\nอย่าพลาด → {url}",
    "🛒 ส่วนลดพิเศษ {name}\nก่อนโปรหมด → {url}",
]

def get_promo_comment():
    """comment โปรโมชั่น — เช็ค expiry อัตโนมัติ"""
    _, _, promos = _load_excel()
    if not promos:
        return None
    p = random.choice(promos)
    template = random.choice(PROMO_INTROS)
    return template.format(name=p["name"], url=p["url"])

def get_product_comments():
    """comments สินค้าหมุนเวียน แยก Shopee / Lazada"""
    products, _, _ = _load_excel()
    active = [p for p in products if p["shopee"] and "xxx" not in p["shopee"]]
    if not active:
        return []
    p = random.choice(active)
    hook = random.choice(PRODUCT_HOOKS)
    vi = random.randrange(len(SHOPEE_INTROS))
    desc_line = f"\n✨ {hook}"
    comments = []
    if p.get("shopee") and "xxx" not in p["shopee"]:
        comments.append(SHOPEE_INTROS[vi].format(name=p["name"] or "สินค้าแนะนำ", desc=desc_line, url=p["shopee"]))
    if p.get("lazada") and "xxx" not in p["lazada"]:
        comments.append(LAZADA_INTROS[vi].format(name=p["name"] or "สินค้าแนะนำ", desc=desc_line, url=p["lazada"]))
    return comments

def get_all_comments():
    """รวม comments — promo มาก่อนเสมอ ที่เหลือสุ่มลำดับ"""
    promo_pool = []
    rest_pool  = []

    # promo — ถ้ามีโปรที่ยังไม่หมดอายุ ใส่ก่อนเป็นอันดับ 1 เสมอ (โอกาส 95%)
    if random.random() < 0.95:
        promo = get_promo_comment()
        if promo:
            promo_pool.append(promo)

    # website comment — โอกาส 85%
    if random.random() < 0.85:
        web = _rotate(WEBSITE_VARS)
        if web:
            rest_pool.append(web)

    # food comment — โอกาส 60%
    if random.random() < 0.60:
        food = get_food_comment()
        if food:
            rest_pool.append(food)

    # product comments — โอกาส 70%
    if random.random() < 0.70:
        products = get_product_comments()
        if len(products) == 2 and random.random() < 0.40:
            rest_pool.append(random.choice(products))
        else:
            rest_pool.extend(products)

    # สุ่มลำดับเฉพาะส่วนที่เหลือ
    random.shuffle(rest_pool)

    # รวม: promo ก่อน → ที่เหลือตามหลัง
    pool = promo_pool + rest_pool

    # backup ถ้าว่างทั้งหมด
    if not pool:
        web = _rotate(WEBSITE_VARS)
        if web:
            pool.append(web)

    return pool
