# overlay_utils.py — PIL text overlay for Facebook bot images

import os
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Kanit-Bold.ttf")


def _wrap_text(draw, text, font, max_width):
    """แบ่ง text เป็นหลาย line ให้พอดีกับ max_width (รองรับภาษาไทยที่ไม่มี space)"""
    lines = []
    current = ""
    for char in text:
        test = current + char
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or [text]


def _fit_wrapped(draw, text, max_width, max_total_h, start=88, min_size=24):
    """หา font size + wrapped lines ที่พอดีกับ max_total_h"""
    size = start
    while size >= min_size:
        font  = ImageFont.truetype(FONT_PATH, size)
        lines = _wrap_text(draw, text, font, max_width)
        lines = _balance_wrap(draw, lines, font, max_width)  # ป้องกัน orphan
        line_h = draw.textbbox((0, 0), "กA", font=font)[3]
        gap    = max(6, size // 8)
        total  = line_h * len(lines) + gap * (len(lines) - 1)
        if total <= max_total_h:
            return font, size, lines, line_h, gap
        size -= 2
    font   = ImageFont.truetype(FONT_PATH, min_size)
    lines  = _wrap_text(draw, text, font, max_width)
    lines  = _balance_wrap(draw, lines, font, max_width)
    line_h = draw.textbbox((0, 0), "กA", font=font)[3]
    gap    = max(6, min_size // 8)
    return font, min_size, lines, line_h, gap


def _balance_wrap(draw, lines, font, max_width, min_ratio=0.42):
    """ถ้า line สุดท้ายสั้นเกิน (orphan) — merge 2 บรรทัดสุดท้ายแล้ว re-wrap ให้สมดุล"""
    if len(lines) <= 1:
        return lines
    last_text = lines[-1].strip()
    last_w    = draw.textbbox((0, 0), last_text, font=font)[2]
    prev_w    = draw.textbbox((0, 0), lines[-2], font=font)[2]
    # trigger ถ้า: pixel ratio ต่ำ หรือ char น้อยมาก (เลขเดี่ยว %, 0, บาท ฯลฯ)
    is_orphan = (last_w < prev_w * min_ratio) or (len(last_text) <= 3)
    if not is_orphan:
        return lines  # สมดุลแล้ว
    # merge 2 บรรทัดสุดท้าย → re-wrap ด้วย target_w ที่แคบลง
    merged   = lines[-2] + lines[-1]
    total_w  = draw.textbbox((0, 0), merged, font=font)[2]
    target_w = min(max_width, int(total_w * 0.55))  # ทำให้แตกเป็น ~2 บรรทัดที่เท่าๆ กัน
    rebalanced = _wrap_text(draw, merged, font, target_w)
    # ตรวจว่าทุก line ไม่เกิน max_width (ไม่ overflow)
    if all(draw.textbbox((0, 0), l, font=font)[2] <= max_width for l in rebalanced):
        return lines[:-2] + rebalanced
    return lines  # rebalance ไม่ได้ — คืนค่าเดิม


def _draw_lines(draw, lines, font, line_h, gap, y_start, W, fill, shadow=(0, 0, 0)):
    """วาด wrapped lines กึ่งกลาง พร้อม 8-direction outline (อ่านได้ทุกพื้นหลัง)"""
    y = y_start
    for line in lines:
        bw = draw.textbbox((0, 0), line, font=font)[2]
        x  = (W - bw) // 2
        # 8-direction outline — ทำให้อ่านได้แม้พื้นหลังสีใกล้เคียงตัวอักษร
        for dx, dy in [(-3,-3),(-3,0),(-3,3),(0,-3),(0,3),(3,-3),(3,0),(3,3)]:
            draw.text((x + dx, y + dy), line, font=font, fill=shadow)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + gap
    return y  # y หลังบรรทัดสุดท้าย


def add_overlay(img_path, line1, line2, accent_color, out_path=None):
    """
    วาง text 2 บรรทัด (พร้อม word-wrap) ทับรูป:
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

    draw  = ImageDraw.Draw(img)
    PAD   = 55          # ระยะห่างขอบ left/right/bottom
    max_w = W - PAD * 2  # ความกว้างสูงสุดของ text

    # พื้นที่ทั้งหมดสำหรับ text (อยู่ใน gradient zone)
    text_zone_h = grad_h - PAD - 20  # เว้น 20px บน gradient
    BLOCK_GAP   = 16  # ช่องว่างระหว่าง line1 block กับ line2 block

    # แบ่งพื้นที่: line1 ได้ ~58%, line2 ได้ ~42%
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
    y_start = H - PAD - total_h

    # Draw line1 — accent color
    y_after1 = _draw_lines(draw, lines1, font1, lh1, gap1, y_start, W, fill=accent_color)

    # Draw line2 — white
    if line2:
        _draw_lines(draw, lines2, font2, lh2, gap2, y_after1 + BLOCK_GAP, W, fill=(255, 255, 255))

    if not out_path:
        base     = img_path.rsplit(".", 1)[0]
        out_path = base + "_overlay.jpg"

    img.save(out_path, "JPEG", quality=92)
    return out_path
