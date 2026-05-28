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
            # column H=promo_message, I=promo_url, J=promo_active, K=expiry_date, L=picture_url
            promo_msg    = row[7]  if len(row) > 7  else None
            promo_url    = row[8]  if len(row) > 8  else None
            promo_active = row[9]  if len(row) > 9  else None
            expiry_raw   = row[10] if len(row) > 10 else None
            picture_url  = row[11] if len(row) > 11 else None

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

            # promo — column H-L, active=yes + ยังไม่หมดอายุ
            promo_ok = str(promo_active or "").strip().lower() == "yes"
            if promo_ok and expiry_raw:
                try:
                    from datetime import date as _date
                    if hasattr(expiry_raw, "date"):
                        exp = expiry_raw.date()
                    else:
                        exp = datetime.strptime(str(expiry_raw).strip()[:10], "%Y-%m-%d").date()
                    if today > exp:
                        promo_ok = False
                        print(f"Promo expired ({exp}): {str(promo_msg or '')[:40]}")
                except Exception:
                    pass  # parse ไม่ได้ → ไม่ block

            if promo_msg and promo_ok:
                promos.append({
                    "message":     str(promo_msg).strip(),
                    "url":         str(promo_url or "").strip(),
                    "picture_url": str(picture_url or "").strip(),
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
# Templates will be dynamically selected and structured in get_food_comment()

# ─── Shopee / Lazada fallback comment templates (3-Step: Hook -> Story -> CTA) ───────────────────────────
SHOPEE_INTROS = [
    "🛒 {hook}\n✨ {desc}\n👉 มีโปรเด็ดลดราคาอยู่นะ สนใจกดตะกร้าสั่งซื้อด่วนเลย{ending} → {url}",
    "🔥 {hook}\n✨ {desc}\n👉 ของมันต้องมี คุ้มราคาขนาดนี้รีบกดตะกร้าเลย มีโปรดีลดเยอะมาก{ending} → {url}",
    "💡 {hook}\n✨ {desc}\n👉 ชี้เป้าตัวช่วยดีๆ ราคาคุ้มค่าจัดโปรลดหนักอยู่ กดตะกร้าจัดได้เลย{ending} → {url}",
]

LAZADA_INTROS = [
    "🛍️ {hook}\n✨ {desc}\n👉 มีโปรเด็ดลดราคาอยู่นะ สนใจกดตะกร้าสั่งซื้อด่วนเลย{ending} → {url}",
    "🔥 {hook}\n✨ {desc}\n👉 ของมันต้องมี คุ้มราคาขนาดนี้รีบกดตะกร้าเลย มีโปรดีลดเยอะมาก{ending} → {url}",
    "💡 {hook}\n✨ {desc}\n👉 ชี้เป้าตัวช่วยดีๆ ราคาคุ้มค่าจัดโปรลดหนักอยู่ กดตะกร้าจัดได้เลย{ending} → {url}",
]

PRODUCT_HOOKS = [
    "เห้ย ตัวนี้เด็ดจริง! คนรีวิวหลักร้อย คะแนนเต็มห้าดาว",
    "บอกลาปัญหาเดิมๆ ไปได้เลย ตัวนี้เอาอยู่จริง",
    "ของมันต้องมีในงบประหยัด สารพัดประโยชน์มาก",
    "ไอเทมลับที่ทุกคนตามหา รีบตำก่อนของหมด",
    "ใช้แล้วชีวิตดีขึ้น 300% แนะนำสุดๆ เลยตัวนี้",
    "ขายดีอันดับต้นๆ ในหมวดนี้ รีวิวปังทุกช่องทาง",
    "ใครไม่มีคือพลาดมาก ตอบโจทย์สุดๆ เลยชิ้นนี้",
    "การันตีของแท้ 100% ส่งไว ได้ของชัวร์",
]

PROMO_INTROS = [
    "🔥 โปรโมชั่นพิเศษ! {name}\nรีบคว้าก่อนหมด → {url}",
    "⚡ Flash Deal วันนี้เท่านั้น {name}\nกดซื้อเลย → {url}",
    "🎯 ดีลเด็ด {name}\nราคาพิเศษจำกัดเวลา → {url}",
    "💥 โปรแรง {name}\nอย่าพลาด → {url}",
    "🛒 ส่วนลดพิเศษ {name}\nก่อนโปรหมด → {url}",
]

# ─── Public API ───────────────────────────────────────────────────
def get_standard_comments():
    """comment เว็บ shopee-ranking (หมุน variations)"""
    return [_rotate(WEBSITE_VARS)]

def get_persona():
    """ตรวจจับว่ากำลังรันอยู่ในโฟลเดอร์ของเพจไหนเพื่อเลือกบุคลิกภาพที่ถูกต้อง"""
    path = os.path.abspath(__file__).replace("\\", "/")
    if "chowchow" in path:
        return "chowchow"
    elif "somtam" in path:
        return "somtam"
    elif "kram" in path:
        return "kram"
    elif "x-bot" in path:
        return "xbot"
    else:
        return "rocket"

def generate_comment_with_ai(p, platform, persona):
    """ใช้ Gemini-2.5-flash เขียนคอมเมนต์ 3 ขั้นตอนสไตล์แอดมินตามเพจ"""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None

    # กำหนดบุคลิกตามเพจ
    if persona == "chowchow":
        persona_inst = "น้องหมา Chow Chow เพศผู้ (ชื่อแอดมินน้องตูบ) เล่าเรื่องราวแสนซน ขี้อ้อน และตรงไปตรงมา มีคำลงท้ายภาษาตูบตัวผู้เสมอ เช่น ฮะ, ครับ หรือมีเสียงร้อง โฮ่ง บ้าง แทนตัวว่า ผม หรือ น้องตูบ"
    elif persona == "somtam":
        persona_inst = "ผู้หญิงที่เป็นกันเอง น่ารัก ตลก และตรงไปตรงมา (เพจชื่อพริก 10 เม็ด) มีคำลงท้ายภาษาผู้หญิงเสมอ เช่น ค่ะ/คะ แทนตัวว่า หนู หรือ เรา"
    else: # kram, xbot, rocket (ผู้ชาย)
        persona_inst = "ผู้ชาย สุภาพและเป็นกันเอง ลงท้ายด้วยครับ/ผม หรือพี่"

    name = p.get("name", "สินค้าแนะนำ")
    desc = p.get("desc", "").strip()

    prompt = (
        f"คุณคือแอดมินเพจโซเชียลมีเดียที่เป็น: {persona_inst}\n\n"
        f"ช่วยเขียนคอมเมนต์แนะนำสินค้าเพื่อโปรโมทลิงก์แอฟฟิลิเอต (Affiliate) บน {platform} โดยใช้เทคนิค 3 ขั้นตอนในการเขียน:\n"
        f"1. เปิดให้น่าสนใจ (Hook): ประโยคเปิดหัวสั้นๆ กระชับ น่าสนใจ ดึงดูดให้อยากอ่านต่อ\n"
        f"2. เล่าให้เห็นภาพ (Vivid Storytelling): บรรยายให้คนอ่านเห็นภาพการใช้งานจริง หรือประโยชน์เด่นๆ ของสินค้า\n"
        f"3. ปิดจบต้องบอกว่า 'ควรทำอะไร' (Call to Action): บอกให้กดสั่งซื้อในตะกร้า หรือย้ำว่ามีโปรเด็ด/ลดราคาพิเศษอยู่ บังคับมีคำลงท้ายตามบุคลิกภาพของคุณ\n\n"
        f"รายละเอียดสินค้า:\n"
        f"- ชื่อสินค้า: {name}\n"
        f"- ข้อมูลเด่น: {desc}\n\n"
        f"กฎการร่างข้อความ:\n"
        f"- ห้ามใส่ลิงก์เด็ดขาด (ลิงก์จะถูกนำไปต่อท้ายเอง)\n"
        f"- ความยาวรวมไม่เกิน 2-3 บรรทัด (สั้น กระชับ คล้ายสไตล์คุยกันใต้โพสต์)\n"
        f"- ห้ามใช้ markdown เช่น ตัวหนา ** หรืออัญประกาศ\n"
        f"- ตอบเฉพาะตัวข้อความภาษาไทยเท่านั้น"
    )

    try:
        from google import genai
        client = genai.Client(api_key=api_key, http_options={'timeout': 90.0})
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        text = resp.text.strip()
        # Clean potential echoes
        text = re.sub(r'^(คอมเมนต์|Comment|ข้อความ|คำอธิบาย)[:\-\s\.]+', '', text, flags=re.IGNORECASE).strip()
        text = text.strip('"\'“”‘’')
        return text
    except Exception as e:
        print(f"AI Comment generation failed: {e}")
        return None

def get_food_comment():
    """comment Shopee Food หมุนเวียนทุกร้าน ตามหลัก 3 ขั้นตอน"""
    _, food_entries, _ = _load_excel()
    raw = _rotate(food_entries, extra_salt=3)
    if not raw:
        return None
    name, url = _parse_food(raw)
    
    persona = get_persona()
    if persona == "chowchow":
        ending = "ฮะ โฮ่ง!"
    elif persona == "somtam":
        ending = "ค่ะ"
    else:
        ending = "ครับ"

    food_templates = [
        "🍜 หิวตอนดึกแบบนี้ต้องจัดแล้ว! {name} กลิ่นหอมๆ รสชาติเข้มข้นถึงใจแน่นอน\n👉 มีโปรเด็ดลดราคาอยู่นะ กดตะกร้าสั่งผ่าน Shopee Food ได้เลย{ending} → {url}",
        "🍱 แนะนำร้านนี้เลย {name} รสเด็ด เมนูเด่น จัดเต็มคำ กินกี่ทีก็ไม่เบื่อ\n👉 กดสั่งในตะกร้าด่วน มีโปรโมชั่นสุดพิเศษรออยู่นะ{ending} → {url}",
        "🔖 หิวแบบนี้จะพลาดได้ไง! {name} อาหารสดใหม่ รสชาติกลมกล่อมฟินทุกคำ\n👉 กดสั่งทางนี้เลย มีโปรลดจุกๆ วันนี้เท่านั้นนะ{ending} → {url}",
        "🛵 เมนูนี้ชวนน้ำลายสอเลย! {name} อร่อยร้อนๆ คุ้มค่าสมราคาพร้อมส่งทันที\n👉 อย่ารอช้า กดตะกร้าสั่งได้เลย มีโปรส่งฟรีอยู่นะ{ending} → {url}",
    ]
    
    template = random.choice(food_templates)
    return template.format(name=name, url=url, ending=ending)

def get_promo_comment():
    """comment โปรโมชั่น — ใช้ message จาก Excel โดยตรง (รองรับ picture_url)"""
    _, _, promos = _load_excel()
    if not promos:
        return None
    p = random.choice(promos)
    msg = p["message"].strip()
    if not msg:
        print("Promo skipped: empty message")
        return None
    if p.get("url"):
        msg += f"\n{p['url']}"
    pic = p.get("picture_url", "").strip()
    # ตรวจว่าเป็น URL จริง ไม่ใช่ชื่อตัวแปรหรือ placeholder
    if not pic.startswith("http"):
        pic = ""
    return {"message": msg, "picture_url": pic}

def select_product_with_ai(products, caption=None, img_path=None):
    """ใช้ Gemini เพื่อวิเคราะห์ความเชื่อมโยงของโพสต์กับสินค้าสปอนเซอร์"""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("AI Product Selector: No API key found. Falling back to random selection.")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options={'timeout': 90.0})
        
        # จัดเตรียมรายการสินค้าที่มีในระบบ
        product_list_str = ""
        for idx, p in enumerate(products):
            product_list_str += f"[{idx}] Name: {p.get('name', '')}, Desc: {p.get('desc', '')}\n"

        prompt = (
            "คุณคือผู้ช่วยระบบ AI Product Selector สำหรับหน้าเพจโซเชียลมีเดียในไทย\n"
            "กรุณาวิเคราะห์ภาพถ่าย และ/หรือ ข้อความแคปชั่นของโพสต์นี้ เพื่อจับคู่เลือกสินค้าสปอนเซอร์ (Affiliate Product) ที่เหมาะสมและเนียนที่สุดจากรายการด้านล่าง:\n"
        )
        if caption:
            prompt += f"ข้อความแคปชั่นโพสต์:\n\"\"\"\n{caption}\n\"\"\"\n\n"

        prompt += (
            "และนี่คือรายการสินค้าสปอนเซอร์ที่มีในระบบ:\n"
            f"{product_list_str}\n"
            "กฎการเลือกสินค้า:\n"
            "- วิเคราะห์โพสต์/รูปภาพเพื่อเลือกสินค้าที่เกี่ยวข้องกันมากที่สุด เช่น โพสต์เรื่องสัตว์เลี้ยงควรคู่กับสินค้าสัตว์เลี้ยง, โพสต์มนุษย์ออฟฟิศ/ปวดหลัง/ทำงานหนักควรคู่กับเบาะรองนั่ง/แผ่นแปะแก้ปวด/แว่นสายตา/ลูทีนบำรุงสายตา, โพสต์อาหารคาวหรือกินเผ็ดร้อนควรคู่กับยาลดกรดหรืออาหารแก้เผ็ด\n"
            "- ให้เลือกดัชนีของสินค้ามาเพียงชิ้นเดียวเท่านั้น\n"
            "- ตอบกลับเป็นดัชนีของสินค้าในเครื่องหมายวงเล็บเหลี่ยมเท่านั้น เช่น [3] (ห้ามเขียนบรรยายความรู้สึกหรือเหตุผล ห้ามมีข้อความอื่นปน)\n"
            "- หากวิเคราะห์แล้วไม่มีสินค้าใดเหมาะสมหรือใกล้เคียงเลย ให้ตอบว่า [None]"
        )

        contents = []
        if img_path and os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f:
                    img_data = f.read()
                ext = os.path.splitext(img_path)[1].lower()
                mime_type = "image/jpeg"
                if ext == ".png":
                    mime_type = "image/png"
                elif ext == ".webp":
                    mime_type = "image/webp"
                elif ext == ".gif":
                    mime_type = "image/gif"
                contents.append(types.Part.from_bytes(data=img_data, mime_type=mime_type))
            except Exception as img_err:
                print(f"AI Product Selector image read error: {img_err}")

        contents.append(prompt)

        # เรียกใช้ Gemini-2.5-flash (เร็วและประหยัด)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents
        )

        result = resp.text.strip()
        print(f"AI Product Selector response: {result}")

        match = re.search(r'\[(\d+)\]', result)
        if match:
            idx = int(match.group(1))
            if 0 <= idx < len(products):
                return products[idx]
        elif "[None]" in result or "None" in result:
            print("AI Product Selector: Decided no product is relevant.")
    except Exception as e:
        print(f"AI Product Selector error: {e}")

    return None

def get_product_comments(caption=None, img_path=None):
    """comments สินค้าหมุนเวียน แยก Shopee / Lazada (ใช้ AI วิเคราะห์และเลือก)"""
    products, _, _ = _load_excel()
    active = [p for p in products if p["shopee"] and "xxx" not in p["shopee"]]
    if not active:
        return []
    
    selected_p = None
    if caption or img_path:
        selected_p = select_product_with_ai(active, caption=caption, img_path=img_path)
        
    if not selected_p:
        selected_p = random.choice(active)
        print("AI Selector: Fallback to random product.")
    else:
        print(f"AI Selector: Selected product -> {selected_p['name']}")

    p = selected_p
    persona = get_persona()
    
    comments = []
    
    # กำหนดคำลงท้ายสำหรับกรณี Fallback Template
    if persona == "chowchow":
        ending = "ฮะ โฮ่ง!"
    elif persona == "somtam":
        ending = "ค่ะ"
    else:
        ending = "ครับ"

    for platform in ["Shopee", "Lazada"]:
        url_key = platform.lower()
        url = p.get(url_key)
        if url and "xxx" not in url:
            # 1. ลองใช้ AI เขียนแบบ 3 ขั้นตอนก่อน
            ai_comment = generate_comment_with_ai(p, platform, persona)
            if ai_comment:
                comments.append(f"{ai_comment}\n👉 {platform} → {url}")
            else:
                # 2. หาก AI ล้มเหลว หรือไม่มี Key ให้ใช้ Fallback Template
                hook = random.choice(PRODUCT_HOOKS)
                desc = p.get("desc", "").strip()
                if not desc:
                    desc = f"ตัวนี้เป็น {p.get('name', 'สินค้าแนะนำ')} ยอดฮิต ใช้งานง่ายและตอบโจทย์ชีวิตประจำวันมากๆ"
                
                template = random.choice(SHOPEE_INTROS if platform == "Shopee" else LAZADA_INTROS)
                comments.append(template.format(hook=hook, desc=desc, ending=ending, url=url))
                
    return comments

def get_all_comments(caption=None, img_path=None):
    """รวม comments — promo มาก่อนเสมอ ที่เหลือสุ่มลำดับ"""
    promo_pool = []
    rest_pool  = []

    # promo — ใส่เสมอถ้ามี (การันตี comment อันดับ 1)
    promo = get_promo_comment()
    if promo:
        promo_pool.append(promo)

    # website comment — ใส่เสมอ (การันตี minimum 2 comments)
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
        products = get_product_comments(caption=caption, img_path=img_path)
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
