# overlay_utils.py â€” PIL text overlay for Facebook bot images

import os
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Kanit-Bold.ttf")

_LEADING_VOWELS  = set('เแโใไ')
_COMBINING_CHARS = set('่้๊๋์ิีึืุูัํ็')


def _wrap_text(draw, text, font, max_width):
    """à¹à¸šà¹ˆà¸‡ text à¹€à¸›à¹‡à¸™à¸«à¸¥à¸²à¸¢ line à¹ƒà¸«à¹‰à¸žà¸­à¸”à¸µà¸à¸±à¸š max_width (à¸£à¸­à¸‡à¸£à¸±à¸šà¸ à¸²à¸©à¸²à¹„à¸—à¸¢à¸—à¸µà¹ˆà¹„à¸¡à¹ˆà¸¡à¸µ space)"""
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return [text]
    if " " in text.strip():
        return _wrap_words(draw, text, font, max_width)
    if getattr(font, "size", 99) > 42:
        return [text]

    lines = []
    current = ""
    for char in text:
        test = current + char
        fits = draw.textbbox((0, 0), test, font=font)[2] <= max_width
        if fits or char in _COMBINING_CHARS:
            current = test
        else:
            if current:
                if current[-1] in _LEADING_VOWELS:
                    orphan  = current[-1]
                    current = current[:-1]
                    if current:
                        lines.append(current)
                    current = orphan + char
                else:
                    lines.append(current)
                    current = char
            else:
                current = char
    if current:
        lines.append(current)
    return lines or [text]


def _wrap_words(draw, text, font, max_width):
    words = [w for w in text.split(" ") if w]
    if not words:
        return [text]
    lines, current = [], ""
    for word in words:
        test = word if not current else current + " " + word
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _fit_wrapped(draw, text, max_width, max_total_h, start=88, min_size=24):
    """à¸«à¸² font size + wrapped lines à¸—à¸µà¹ˆà¸žà¸­à¸”à¸µà¸à¸±à¸š max_total_h"""
    size = start
    while size >= min_size:
        font  = ImageFont.truetype(FONT_PATH, size)
        lines = _wrap_text(draw, text, font, max_width)
        lines = _balance_wrap(draw, lines, font, max_width)  # à¸›à¹‰à¸­à¸‡à¸à¸±à¸™ orphan
        line_h = draw.textbbox((0, 0), "à¸A", font=font)[3]
        gap    = max(6, size // 8)
        total  = line_h * len(lines) + gap * (len(lines) - 1)
        width_ok = all(draw.textbbox((0, 0), l, font=font)[2] <= max_width for l in lines)
        if total <= max_total_h and width_ok:
            return font, size, lines, line_h, gap
        size -= 2
    font   = ImageFont.truetype(FONT_PATH, min_size)
    lines  = _wrap_text(draw, text, font, max_width)
    lines  = _balance_wrap(draw, lines, font, max_width)
    line_h = draw.textbbox((0, 0), "à¸A", font=font)[3]
    gap    = max(6, min_size // 8)
    return font, min_size, lines, line_h, gap


def _balance_wrap(draw, lines, font, max_width, min_ratio=0.42):
    """à¸–à¹‰à¸² line à¸ªà¸¸à¸”à¸—à¹‰à¸²à¸¢à¸ªà¸±à¹‰à¸™à¹€à¸à¸´à¸™ (orphan) â€” merge 2 à¸šà¸£à¸£à¸—à¸±à¸”à¸ªà¸¸à¸”à¸—à¹‰à¸²à¸¢à¹à¸¥à¹‰à¸§ re-wrap à¹ƒà¸«à¹‰à¸ªà¸¡à¸”à¸¸à¸¥"""
    if len(lines) <= 1:
        return lines
    last_text = lines[-1].strip()
    last_w    = draw.textbbox((0, 0), last_text, font=font)[2]
    prev_w    = draw.textbbox((0, 0), lines[-2], font=font)[2]
    # trigger à¸–à¹‰à¸²: pixel ratio à¸•à¹ˆà¸³ à¸«à¸£à¸·à¸­ char à¸™à¹‰à¸­à¸¢à¸¡à¸²à¸ (à¹€à¸¥à¸‚à¹€à¸”à¸µà¹ˆà¸¢à¸§ %, 0, à¸šà¸²à¸— à¸¯à¸¥à¸¯)
    is_orphan = (last_w < prev_w * min_ratio) or (len(last_text) <= 4)
    if not is_orphan:
        return lines  # à¸ªà¸¡à¸”à¸¸à¸¥à¹à¸¥à¹‰à¸§
    # merge 2 à¸šà¸£à¸£à¸—à¸±à¸”à¸ªà¸¸à¸”à¸—à¹‰à¸²à¸¢ â†’ re-wrap à¸”à¹‰à¸§à¸¢ target_w à¸—à¸µà¹ˆà¹à¸„à¸šà¸¥à¸‡
    merged   = lines[-2] + " " + lines[-1]
    total_w  = draw.textbbox((0, 0), merged, font=font)[2]
    target_w = min(max_width, int(total_w * 0.55))  # à¸—à¸³à¹ƒà¸«à¹‰à¹à¸•à¸à¹€à¸›à¹‡à¸™ ~2 à¸šà¸£à¸£à¸—à¸±à¸”à¸—à¸µà¹ˆà¹€à¸—à¹ˆà¸²à¹† à¸à¸±à¸™
    rebalanced = _wrap_text(draw, merged, font, target_w)
    # à¸•à¸£à¸§à¸ˆà¸§à¹ˆà¸²à¸—à¸¸à¸ line à¹„à¸¡à¹ˆà¹€à¸à¸´à¸™ max_width (à¹„à¸¡à¹ˆ overflow)
    if all(draw.textbbox((0, 0), l, font=font)[2] <= max_width for l in rebalanced):
        return lines[:-2] + rebalanced
    return lines  # rebalance à¹„à¸¡à¹ˆà¹„à¸”à¹‰ â€” à¸„à¸·à¸™à¸„à¹ˆà¸²à¹€à¸”à¸´à¸¡


def _draw_lines(draw, lines, font, line_h, gap, y_start, W, fill, shadow=(0, 0, 0)):
    """à¸§à¸²à¸” wrapped lines à¸à¸¶à¹ˆà¸‡à¸à¸¥à¸²à¸‡ à¸žà¸£à¹‰à¸­à¸¡ 8-direction outline (à¸­à¹ˆà¸²à¸™à¹„à¸”à¹‰à¸—à¸¸à¸à¸žà¸·à¹‰à¸™à¸«à¸¥à¸±à¸‡)"""
    y = y_start
    for line in lines:
        bw = draw.textbbox((0, 0), line, font=font)[2]
        x  = (W - bw) // 2
        # 8-direction outline â€” à¸—à¸³à¹ƒà¸«à¹‰à¸­à¹ˆà¸²à¸™à¹„à¸”à¹‰à¹à¸¡à¹‰à¸žà¸·à¹‰à¸™à¸«à¸¥à¸±à¸‡à¸ªà¸µà¹ƒà¸à¸¥à¹‰à¹€à¸„à¸µà¸¢à¸‡à¸•à¸±à¸§à¸­à¸±à¸à¸©à¸£
        for dx, dy in [(-3,-3),(-3,0),(-3,3),(0,-3),(0,3),(3,-3),(3,0),(3,3)]:
            draw.text((x + dx, y + dy), line, font=font, fill=shadow)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + gap
    return y  # y à¸«à¸¥à¸±à¸‡à¸šà¸£à¸£à¸—à¸±à¸”à¸ªà¸¸à¸”à¸—à¹‰à¸²à¸¢


def _remove_black_bars(img, threshold=20):
    """Remove solid black pillarbox/letterbox borders from image"""
    gray = img.convert("L")
    mask = gray.point(lambda p: 255 if p > threshold else 0)
    bbox = mask.getbbox()
    if bbox and (bbox[0] > 5 or bbox[1] > 5 or
                 img.width - bbox[2] > 5 or img.height - bbox[3] > 5):
        return img.crop(bbox)
    return img


def add_overlay(img_path, line1, line2, accent_color, out_path=None):
    """
    à¸§à¸²à¸‡ text 2 à¸šà¸£à¸£à¸—à¸±à¸” (à¸žà¸£à¹‰à¸­à¸¡ word-wrap) à¸—à¸±à¸šà¸£à¸¹à¸›:
      line1 â€” à¸ªà¸µ accent_color (hook à¸«à¸¥à¸±à¸)
      line2 â€” à¸ªà¸µà¸‚à¸²à¸§ (à¹€à¸ªà¸£à¸´à¸¡/à¸„à¸³à¸–à¸²à¸¡)
    à¸„à¸·à¸™ path à¸£à¸¹à¸›à¹ƒà¸«à¸¡à¹ˆ
    """
    img = Image.open(img_path).convert("RGB")
    img = _remove_black_bars(img)
    w, h = img.size

    # Crop à¹€à¸›à¹‡à¸™ square à¹à¸¥à¹‰à¸§ resize 1080x1080
    size = min(w, h)
    left = (w - size) // 2
    top  = (h - size) // 2
    img  = img.crop((left, top, left + size, top + size))
    img  = img.resize((1080, 1080), Image.LANCZOS)
    W, H = 1080, 1080

    # Dark gradient à¸¥à¹ˆà¸²à¸‡ 45%
    BAR_H    = 260
    img_rgba = img.convert("RGBA")
    bar      = Image.new("RGBA", (W, BAR_H), (0, 0, 0, 255))
    img_rgba.paste(bar, (0, H - BAR_H))
    img      = img_rgba.convert("RGB")

    draw  = ImageDraw.Draw(img)
    PAD   = 44          # à¸£à¸°à¸¢à¸°à¸«à¹ˆà¸²à¸‡à¸‚à¸­à¸š left/right/bottom
    max_w = W - PAD * 2  # à¸„à¸§à¸²à¸¡à¸à¸§à¹‰à¸²à¸‡à¸ªà¸¹à¸‡à¸ªà¸¸à¸”à¸‚à¸­à¸‡ text

    # à¸žà¸·à¹‰à¸™à¸—à¸µà¹ˆà¸—à¸±à¹‰à¸‡à¸«à¸¡à¸”à¸ªà¸³à¸«à¸£à¸±à¸š text (à¸­à¸¢à¸¹à¹ˆà¹ƒà¸™ gradient zone)
    text_zone_h = BAR_H - PAD * 2  # à¹€à¸§à¹‰à¸™ 20px à¸šà¸™ gradient
    BLOCK_GAP   = 14  # à¸Šà¹ˆà¸­à¸‡à¸§à¹ˆà¸²à¸‡à¸£à¸°à¸«à¸§à¹ˆà¸²à¸‡ line1 block à¸à¸±à¸š line2 block

    # à¹à¸šà¹ˆà¸‡à¸žà¸·à¹‰à¸™à¸—à¸µà¹ˆ: line1 à¹„à¸”à¹‰ ~58%, line2 à¹„à¸”à¹‰ ~42%
    h1_budget = int(text_zone_h * 0.58)
    h2_budget = int(text_zone_h * 0.42) - BLOCK_GAP

    # Fit line1
    font1, sz1, lines1, lh1, gap1 = _fit_wrapped(draw, line1, max_w, h1_budget, start=88)
    total_h1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)

    # Fit line2
    if line2:
        font2, sz2, lines2, lh2, gap2 = _fit_wrapped(
            draw, line2, max_w, h2_budget, start=max(24, sz1 - 20)
        )
        total_h2 = lh2 * len(lines2) + gap2 * (len(lines2) - 1)
    else:
        total_h2 = 0

    total_h = total_h1 + (BLOCK_GAP + total_h2 if line2 else 0)
    bar_top = H - BAR_H
    y_start = bar_top + (BAR_H - total_h) // 2

    # Draw line1 — accent color
    _draw_lines(draw, lines1, font1, lh1, gap1, y_start, W, fill=accent_color)

    # Draw line2 — white (pixel-exact gap: BLOCK_GAP px between bottom of line1 and top of line2)
    if line2:
        n1 = len(lines1)
        b1 = draw.textbbox((0, 0), lines1[-1], font=font1)
        pixel_bottom1 = y_start + lh1 * (n1 - 1) + gap1 * (n1 - 1) + b1[3]
        b2 = draw.textbbox((0, 0), lines2[0], font=font2)
        y2 = pixel_bottom1 + BLOCK_GAP - b2[1]
        _draw_lines(draw, lines2, font2, lh2, gap2, y2, W, fill=(255, 255, 255))

    if not out_path:
        base     = img_path.rsplit(".", 1)[0]
        out_path = base + "_overlay.jpg"

    img.save(out_path, "JPEG", quality=92)
    return out_path
