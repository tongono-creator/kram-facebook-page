"""render_card.py : CATDUMB-style review & news card renderer (self-contained per repo).

Usage:
    from card.render_card import render_review_card, render_news_card
    out = render_review_card(photo_path, line1, line2, out_path)
    out_news = render_news_card(photo_path, line1, line2, out_path)
"""
import os, json, base64, mimetypes

ROOT     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "catdumb.html")

FONTS = {
    "Kanit":   "fonts/Kanit-Bold.ttf",
    "Itim":    "fonts/Itim-Regular.ttf",
    "Sarabun": "fonts/Sarabun-ExtraBold.ttf",
}

# Per-page theme — border/badge ใช้สีประจำเพจ (เอกลักษณ์เพจ)
THEME = {
    "watermark":   "กรามค้าง",
    "accent":      "#4DD6FF",
    "badge_color": "#ffffff",
    "params": {
        "border_color": "#00BFFF", "badge_bg": "#00BFFF", "badge_pos": "left",
        "frame_radius": 36, "img_w": 1080, "img_h": 1350,
        "photo_h": "78%", "grad_h": "62%", "text_rise": 340,
        "text_size": 78,
    },
}


def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


ECOMMERCE_TEMPLATE = os.path.join(ROOT, "ecommerce.html")


def _data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{_b64(path)}"


def _build_html(data, template_path=TEMPLATE):
    faces = []
    for fam, rel in FONTS.items():
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            faces.append(
                f"@font-face{{font-family:'{fam}';src:url(data:font/ttf;base64,"
                f"{_b64(p)}) format('truetype');font-weight:normal;font-style:normal;}}"
            )
    data = dict(data)
    valid_photos = []
    for p in data.get("photos", []):
        if p and os.path.exists(p):
            valid_photos.append(_data_uri(p if os.path.isabs(p) else os.path.join(os.getcwd(), p)))
    if valid_photos:
        data["photos"] = valid_photos

    tpl = open(template_path, encoding="utf-8").read()
    tpl = tpl.replace("/*FONT_FACE*/", "\n".join(faces))
    tpl = tpl.replace("/*__INJECT_DATA__*/",
                      "window.__DATA__ = " + json.dumps(data, ensure_ascii=False) + ";")
    return tpl


def render(data, out_path, template_path=TEMPLATE):
    from playwright.sync_api import sync_playwright
    html = _build_html(data, template_path=template_path)
    w = int(str(data.get("params", {}).get("img_w", 1080)).replace("px", ""))
    h = int(str(data.get("params", {}).get("img_h", 1350)).replace("px", ""))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        page.wait_for_function("window.__READY__ === true", timeout=15000)
        page.wait_for_timeout(200)
        page.locator("#canvas").screenshot(path=out_path)
        browser.close()
    return out_path


def render_review_card(photo_path, line1, line2, out_path, price=None, price_sub=None,
                       chips=None, is_mall=False, badge_text=None, *, platform="facebook",
                       price_verified=False, width=1080, height=1080):
    """Photo-led sales path. Legacy claim arguments do not imply verification."""
    from .sales_card import render_sales_card
    return render_sales_card(photo_path, line1, line2, out_path, theme=THEME,
        platform=platform, badge_text=badge_text, price=price,
        price_verified=price_verified, width=width, height=height)


def render_news_card(photo_path, line1, line2, out_path, badge_text=None):
    lines = []
    if line1:
        lines.append(f"*{line1}*")
    if line2:
        lines.append(line2)
        
    watermark = badge_text if badge_text else THEME.get("watermark", "")
    data = {
        "photos": [photo_path] if photo_path and os.path.exists(photo_path) else [],
        "lines": lines,
        "watermark": watermark,
        "accent": THEME["accent"],
        "badge_color": THEME["badge_color"],
        "params": dict(THEME["params"]),
    }
    return render(data, out_path)
