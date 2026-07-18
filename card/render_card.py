"""render_card.py : CATDUMB-style review card renderer (self-contained per repo).

Adapted from image-text-overlay skill's render_catdumb.py — assets live in this
same folder so it runs identically on a local machine and a GitHub Actions runner.

Usage (from review.py):
    from card.render_card import render_review_card
    out = render_review_card(photo_path, line1, line2, out_path)
"""
import os, json, base64, mimetypes

ROOT     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "catdumb.html")

FONTS = {
    "Kanit":   "fonts/Kanit-Bold.ttf",
    "Itim":    "fonts/Itim-Regular.ttf",
    "Sarabun": "fonts/Sarabun-ExtraBold.ttf",
}

# Per-page theme — override via env PAGE_THEME if ever needed
THEME = {
    "watermark":   "กรามค้าง",
    "accent":      "#00BFFF",
    "badge_color": "#ffffff",
    "params": {
        "border_color": "#16213e", "badge_bg": "#16213e", "badge_pos": "left",
        "frame_radius": 36, "img_w": 1080, "img_h": 1350,
        "photo_h": "82%", "grad_h": "60%", "text_rise": 340,
        "text_size": 64,
    },
}


def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{_b64(path)}"


def _build_html(data):
    faces = []
    for fam, rel in FONTS.items():
        p = os.path.join(ROOT, rel)
        faces.append(
            f"@font-face{{font-family:'{fam}';src:url(data:font/ttf;base64,"
            f"{_b64(p)}) format('truetype');font-weight:normal;font-style:normal;}}"
        )
    data = dict(data)
    data["photos"] = [_data_uri(p if os.path.isabs(p) else os.path.join(os.getcwd(), p))
                      for p in data.get("photos", [])]
    tpl = open(TEMPLATE, encoding="utf-8").read()
    tpl = tpl.replace("/*FONT_FACE*/", "\n".join(faces))
    tpl = tpl.replace("/*__INJECT_DATA__*/",
                      "window.__DATA__ = " + json.dumps(data, ensure_ascii=False) + ";")
    return tpl


def render(data, out_path):
    from playwright.sync_api import sync_playwright
    html = _build_html(data)
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


def render_review_card(photo_path, line1, line2, out_path):
    """Build the standard review card: line1 accent-colored, line2 white."""
    lines = []
    if line1:
        lines.append(f"*{line1}*")
    if line2:
        lines.append(line2)
    data = {
        "photos": [photo_path],
        "lines": lines,
        "watermark": THEME["watermark"],
        "accent": THEME["accent"],
        "badge_color": THEME["badge_color"],
        "params": dict(THEME["params"]),
    }
    return render(data, out_path)
