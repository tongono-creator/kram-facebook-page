# overlay_utils.py — PIL text overlay for Facebook bot images

import os
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Kanit-Bold.ttf")


def _fit_font(draw, text, max_width, start=90, min_size=28):
    size = start
    while size >= min_size:
        font = ImageFont.truetype(FONT_PATH, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font, size
        size -= 2
    return ImageFont.truetype(FONT_PATH, min_size), min_size


def add_overlay(img_path, line1, line2, accent_color, out_path=None):
    """
    วาง text 2 บรรทัดทับรูป:
      line1 — สี accent_color (hook หลัก)
      line2 — สีขาว (เสริม/คำถาม)
    คืน path รูปใหม่
    """
    img = Image.open(img_path).convert("RGB")
    w, h = img.size

    # Crop เป็น square แล้ว resize 1080x1080
    size = min(w, h)
    left = (w - size) // 2
    top  = (h - size) // 2
    img  = img.crop((left, top, left + size, top + size))
    img  = img.resize((1080, 1080), Image.LANCZOS)
    W, H = 1080, 1080

    # Dark gradient ล่าง 45%
    grad_h   = int(H * 0.45)
    gradient = Image.new("RGBA", (W, grad_h), (0, 0, 0, 0))
    gd       = ImageDraw.Draw(gradient)
    for i in range(grad_h):
        alpha = int(220 * (i / grad_h))
        gd.rectangle([(0, i), (W, i + 1)], fill=(0, 0, 0, alpha))
    img_rgba = img.convert("RGBA")
    img_rgba.paste(gradient, (0, H - grad_h), gradient)
    img = img_rgba.convert("RGB")

    draw = ImageDraw.Draw(img)
    PAD   = 55
    max_w = W - PAD * 2
    GAP   = 14

    font1, sz1 = _fit_font(draw, line1, max_w, start=88)
    font2, _   = _fit_font(draw, line2, max_w, start=int(sz1 * 0.68)) if line2 else (None, 0)

    h1 = draw.textbbox((0, 0), line1, font=font1)[3]
    h2 = draw.textbbox((0, 0), line2, font=font2)[3] if line2 and font2 else 0
    total_h = h1 + (GAP + h2 if line2 else 0)

    y = H - PAD - total_h

    # Line 1 — accent color + shadow
    b1 = draw.textbbox((0, 0), line1, font=font1)
    x1 = (W - (b1[2] - b1[0])) // 2
    draw.text((x1 + 3, y + 3), line1, font=font1, fill=(0, 0, 0))
    draw.text((x1,     y    ), line1, font=font1, fill=accent_color)
    y += h1 + GAP

    # Line 2 — white + shadow
    if line2 and font2:
        b2 = draw.textbbox((0, 0), line2, font=font2)
        x2 = (W - (b2[2] - b2[0])) // 2
        draw.text((x2 + 2, y + 2), line2, font=font2, fill=(0, 0, 0))
        draw.text((x2,     y    ), line2, font=font2, fill=(255, 255, 255))

    if not out_path:
        base = img_path.rsplit(".", 1)[0]
        out_path = base + "_overlay.jpg"

    img.save(out_path, "JPEG", quality=92)
    return out_path
