# overlay_utils.py â€” PIL text overlay for Facebook bot images

import os
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Kanit-Bold.ttf")

_LEADING_VOWELS  = set('เแโใไ')
_COMBINING_CHARS = set('่้๊๋์ิีึืุูัํ็')


def _wrap_text(draw, text, font, max_width):
    """แบ่ง text เป็นหลาย line ให้พอดีกับ max_width (รองรับภาษาไทยที่ไม่มี space)"""
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return [text]
    if '\u200b' in text or '\\u200b' in text:
        text = text.replace('\\u200b', '\u200b')
        tokens = text.split('\u200b')
        lines, current = [], ""
        for token in tokens:
            test = current + token
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                    current = token
                else:
                    current = token
        if current:
            lines.append(current)
        return lines

    if " " in text.strip():
        lines = _wrap_words(draw, text, font, max_width)
        if getattr(font, "size", 99) <= 75:
            new_lines = []
            for l in lines:
                if draw.textbbox((0, 0), l, font=font)[2] > max_width:
                    new_lines.extend(_wrap_text(draw, l, font, max_width))
                else:
                    new_lines.append(l)
            lines = new_lines
        return lines
    if getattr(font, "size", 99) > 75:
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


def _apply_bottom_gradient(img, start_y, end_y, max_alpha=230):
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(start_y, end_y):
        t = (y - start_y) / (end_y - start_y)
        alpha = int(max_alpha * t)
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

def add_overlay(img_path, line1, line2, accent_color, out_path=None):
    """
    Overlays text directly on the image with a smooth black gradient at the bottom.
    No solid black bar is appended, maximizing image visual space (Matichon Style).
    """
    W, H = 1080, 1080
    
    if img_path and os.path.exists(img_path):
        img = Image.open(img_path).convert("RGB")
        img = _remove_black_bars(img)
        w, h = img.size
        # Crop to square
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
        img = img.resize((W, H), Image.LANCZOS)
    else:
        # Fallback to solid dark background
        img = Image.new("RGB", (W, H), (15, 15, 20))

    # Apply bottom gradient overlay (from y=650 to y=1080)
    start_y = 650
    img = _apply_bottom_gradient(img, start_y, H)

    draw = ImageDraw.Draw(img)
    PAD_X = 60
    PAD_Y = 40
    max_w = W - PAD_X * 2  # 960px
    text_zone_h = H - start_y - PAD_Y * 2  # 350px
    BLOCK_GAP = 12

    # Start size fitting proportionally (line2 is ~70% of line1 size)
    # 110px starting size allows extremely large headlines!
    size1 = 110
    size2 = 76 if line2 else 0

    while size1 >= 40:
        font1 = ImageFont.truetype(FONT_PATH, size1)
        font2 = ImageFont.truetype(FONT_PATH, size2) if line2 else None

        # Wrap lines for line1
        lines1 = _wrap_text(draw, line1, font1, max_w)
        lines1 = _balance_wrap(draw, lines1, font1, max_w)
        lh1 = draw.textbbox((0, 0), "ก A", font=font1)[3]
        gap1 = max(6, size1 // 8)
        total_h1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)

        # Wrap lines for line2
        if line2:
            lines2 = _wrap_text(draw, line2, font2, max_w)
            lines2 = _balance_wrap(draw, lines2, font2, max_w)
            lh2 = draw.textbbox((0, 0), "ก A", font=font2)[3]
            gap2 = max(6, size2 // 8)
            total_h2 = lh2 * len(lines2) + gap2 * (len(lines2) - 1)
            total_h = total_h1 + BLOCK_GAP + total_h2
        else:
            total_h = total_h1
            total_h2 = 0

        # Check if text fits inside boundaries
        width_ok = all(draw.textbbox((0, 0), l, font=font1)[2] <= max_w for l in lines1)
        if line2:
            width_ok = width_ok and all(draw.textbbox((0, 0), l, font=font2)[2] <= max_w for l in lines2)

        if total_h <= text_zone_h and width_ok:
            break

        # Decrement size proportionally
        size1 -= 4
        if line2:
            size2 = max(24, int(size1 * 0.7))

    y_start = start_y + (H - start_y - total_h) // 2

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
        base     = img_path.rsplit(".", 1)[0] if img_path else "overlay"
        out_path = base + "_overlay.jpg"

    img.save(out_path, "JPEG", quality=92)
    return out_path
