# overlay_utils.py â€” PIL text overlay for Facebook bot images

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Sarabun-ExtraBold.ttf")

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
    # à¸•à¸£à¸§à¸ˆà¸§à¹ˆà¸²à¸—à¸¸à¸  line à¹„à¸¡à¹ˆà¹€à¸ à¸´à¸™ max_width (à¹„à¸¡à¹ˆ overflow)
    if all(draw.textbbox((0, 0), l, font=font)[2] <= max_width for l in rebalanced):
        return lines[:-2] + rebalanced
    return lines  # rebalance à¹„à¸¡à¹ˆà¹„à¸”à¹‰ â€” à¸„à¸·à¸™à¸„à¹ˆà¸²à¹€à¸”à¸´à¸¡


def _draw_lines(draw, lines, font, line_h, gap, y_start, W, fill, shadow=(0, 0, 0)):
    """วาด wrapped lines กึ่งกลาง พร้อม 8-direction outline (อ่านได้ทุกพื้นหลัง)"""
    y = y_start
    for line in lines:
        clean_line = line.replace('\u200b', '').replace('\\u200b', '')
        bw = draw.textbbox((0, 0), clean_line, font=font)[2]
        x  = (W - bw) // 2
        # 8-direction outline — ทำให้อ่านได้แม้พื้นหลังสีใกล้เคียงตัวอักษร
        if shadow and (len(shadow) < 4 or shadow[3] > 0):
            for dx, dy in [(-3,-3),(-3,0),(-3,3),(0,-3),(0,3),(3,-3),(3,0),(3,3)]:
                draw.text((x + dx, y + dy), clean_line, font=font, fill=shadow)
        draw.text((x, y), clean_line, font=font, fill=fill)
        y += line_h + gap
    return y  # y หลังบรรทัดสุดท้าย


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

def _draw_soft_shadow(image_size, box_coords, radius, shadow_color=(0, 0, 0), shadow_alpha=80, shadow_offset=(0, 8), blur_radius=16):
    """Draw a soft drop shadow using Gaussian blur on an alpha mask layer"""
    shadow_layer = Image.new("RGBA", image_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow_layer, "RGBA")
    
    x1, y1, x2, y2 = box_coords
    dx, dy = shadow_offset
    s_rect = [x1 + dx, y1 + dy, x2 + dx, y2 + dy]
    
    fill_rgba = (*shadow_color, int(shadow_alpha))
    try:
        draw.rounded_rectangle(s_rect, radius=radius, fill=fill_rgba)
    except Exception:
        draw.rectangle(s_rect, fill=fill_rgba)
        
    if blur_radius > 0:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
    return shadow_layer


def _draw_supersampled_card(card_size, radius, fill_color, border_color=None, border_width=0, ss=4):
    """Draw a card with high-res supersampling to ensure perfectly smooth anti-aliased corners"""
    w, h = card_size
    ss_w, ss_h = w * ss, h * ss
    ss_radius = radius * ss
    ss_border_width = border_width * ss
    
    ss_img = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ss_img, "RGBA")
    
    rect = [0, 0, ss_w, ss_h]
    try:
        draw.rounded_rectangle(rect, radius=ss_radius, fill=fill_color)
        if border_color and ss_border_width > 0:
            draw.rounded_rectangle(rect, radius=ss_radius, outline=border_color, width=ss_border_width)
    except Exception:
        draw.rectangle(rect, fill=fill_color)
        if border_color and ss_border_width > 0:
            draw.rectangle(rect, outline=border_color, width=ss_border_width)
            
    return ss_img.resize((w, h), Image.Resampling.LANCZOS)


def _draw_discount_badge(img, text, accent_color):
    """
    Draws a tilted, circular e-commerce sticker/badge in the top-right corner of the image.
    Uses 4x supersampling to ensure clean, smooth anti-aliased corners and text.
    """
    W, H = img.size
    # Size of the badge: 180x180 px
    bw = 180
    bh = 180
    
    # Supersampled dimensions
    ss = 4
    ss_w, ss_h = bw * ss, bh * ss
    
    badge_img = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge_img, "RGBA")
    
    # 1. Circle color: Convert accent_color to RGB tuple
    if isinstance(accent_color, str):
        if accent_color.startswith("#"):
            accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        else:
            accent_rgb = (255, 69, 0) # Fallback to red-orange
    else:
        accent_rgb = accent_color
        
    fill_color = (*accent_rgb, 255)
    
    # Draw circle on supersampled canvas
    draw.ellipse([0, 0, ss_w, ss_h], fill=fill_color)
    # Add a thin white border
    draw.ellipse([8, 8, ss_w - 8, ss_h - 8], outline=(255, 255, 255, 255), width=8)
    
    # 2. Draw text
    font_size = 40 * ss # Start with size 160
    
    lines = []
    if " " in text:
        lines = [w.strip() for w in text.split(" ") if w.strip()]
    elif len(text) > 4:
        if text.startswith("ลด") and len(text) > 2:
            lines = ["ลด", text[2:]]
        else:
            lines = [text]
    else:
        lines = [text]
        
    while font_size >= 12 * ss:
        font = ImageFont.truetype(FONT_PATH, font_size)
        lh = draw.textbbox((0, 0), "ก A", font=font)[3]
        gap = 4 * ss
        total_h = lh * len(lines) + gap * (len(lines) - 1)
        
        width_ok = all(draw.textbbox((0, 0), l, font=font)[2] <= (bw - 30) * ss for l in lines)
        if total_h <= (bh - 30) * ss and width_ok:
            break
        font_size -= 4 * ss
        
    font = ImageFont.truetype(FONT_PATH, font_size)
    lh = draw.textbbox((0, 0), "ก A", font=font)[3]
    gap = 4 * ss
    total_h = lh * len(lines) + gap * (len(lines) - 1)
    
    y = (ss_h - total_h) // 2
    for line in lines:
        tw = draw.textbbox((0, 0), line, font=font)[2]
        x = (ss_w - tw) // 2
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 60))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += lh + gap
        
    badge_img = badge_img.resize((bw, bh), Image.Resampling.LANCZOS)
    badge_img = badge_img.rotate(10, resample=Image.Resampling.BICUBIC, expand=True)
    
    bw_new, bh_new = badge_img.size
    bx = W - bw_new - 40
    by = 40
    
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_alpha = badge_img.split()[3]
    shadow_mask = Image.new("RGBA", badge_img.size, (0, 0, 0, 80))
    shadow_mask.putalpha(badge_alpha)
    shadow_layer.paste(shadow_mask, (bx + 4, by + 8))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=8))
    
    img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_layer.paste(badge_img, (bx, by))
    img = Image.alpha_composite(img, badge_layer)
    
    return img


def _draw_watermark_capsule(img, text, accent_color):
    """
    Draws a small, elegant branding watermark capsule in the top-left corner.
    """
    W, H = img.size
    
    temp_img = Image.new("RGBA", (100, 100))
    temp_draw = ImageDraw.Draw(temp_img)
    
    font_size = 20
    font = ImageFont.truetype(FONT_PATH, font_size)
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    pad_x = 20
    pad_y = 10
    
    bw = tw + pad_x * 2
    bh = th + pad_y * 2
    
    bx = 40
    by = 40
    
    ss = 4
    ss_w, ss_h = bw * ss, bh * ss
    ss_cr = (bh // 2) * ss
    
    capsule_img = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(capsule_img, "RGBA")
    
    draw.rounded_rectangle([0, 0, ss_w, ss_h], radius=ss_cr, fill=(15, 15, 20, 190))
    
    if isinstance(accent_color, str):
        if accent_color.startswith("#"):
            accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        else:
            accent_rgb = (0, 191, 255)
    else:
        accent_rgb = accent_color
        
    draw.rounded_rectangle([0, 0, ss_w, ss_h], radius=ss_cr, outline=(*accent_rgb, 200), width=2 * ss)
    
    ss_font = ImageFont.truetype(FONT_PATH, font_size * ss)
    ss_bbox = draw.textbbox((0, 0), text, font=ss_font)
    ss_tw = ss_bbox[2] - ss_bbox[0]
    ss_th = ss_bbox[3] - ss_bbox[1]
    
    tx = (ss_w - ss_tw) // 2 - ss_bbox[0]
    ty = (ss_h - ss_th) // 2 - ss_bbox[1]
    
    draw.text((tx, ty), text, font=ss_font, fill=(255, 255, 255, 240))
    
    capsule_img = capsule_img.resize((bw, bh), Image.Resampling.LANCZOS)
    
    capsule_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    capsule_layer.paste(capsule_img, (bx, by))
    img = Image.alpha_composite(img.convert("RGBA"), capsule_layer)
    
    return img


def add_overlay(img_path, line1, line2, accent_color, out_path=None, font_name=None, style="premium_card", badge_text=None, watermark="คราม Kram"):
    """
    Overlays text directly on the image.
    Supports two styles:
      - "gradient": Matichon Style bottom dark gradient overlay.
      - "premium_card": Modern rounded card sticker at the bottom with soft drop shadow.
    """
    global FONT_PATH
    if font_name:
        FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", font_name)

    W, H = 1080, 1080
    
    # 1. Prepare Base Image
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

    if style == "news_card":
        # 🌟 NEWS CARD STYLE (Catdumb/Modern News Infographic Style) 🌟
        # Use Kanit-Bold.ttf for a modern, punchy look
        FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Kanit-Bold.ttf")
        draw = ImageDraw.Draw(img)
        
        # 1. Background Blur & Dimming
        bg_blur = img.copy().filter(ImageFilter.GaussianBlur(35))
        dark_mask = Image.new("RGBA", (W, H), (0, 0, 0, 150))
        bg_blur = Image.alpha_composite(bg_blur.convert("RGBA"), dark_mask).convert("RGB")
        img = bg_blur
        
        # 2. Foreground Photo Card (centered in the top area [60, 620])
        if img_path and os.path.exists(img_path):
            try:
                orig = Image.open(img_path).convert("RGB")
                orig = _remove_black_bars(orig)
                ow, oh = orig.size
                aspect = ow / oh
                
                mw, mh = 980, 560
                if aspect > mw / mh:
                    iw = mw
                    ih = int(mw / aspect)
                else:
                    ih = mh
                    iw = int(mh * aspect)
                
                orig_resized = orig.resize((iw, ih), Image.Resampling.LANCZOS)
                
                cr = 28
                mask_img = _draw_supersampled_card((iw, ih), cr, (255, 255, 255, 255))
                
                ix = (W - iw) // 2
                iy = 60 + (560 - ih) // 2
                
                shadow_layer = _draw_soft_shadow((W, H), [ix, iy, ix + iw, iy + ih], cr, blur_radius=12)
                img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
                
                img_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                img_layer.paste(orig_resized, (ix, iy), mask_img.convert("L"))
                img = Image.alpha_composite(img, img_layer).convert("RGB")
                
                # Draw a thin white border around the photo card
                border_card = _draw_supersampled_card((iw, ih), cr, (0, 0, 0, 0), border_color=(255, 255, 255, 180), border_width=3)
                border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                border_layer.paste(border_card, (ix, iy))
                img = Image.alpha_composite(img.convert("RGBA"), border_layer).convert("RGB")
            except Exception as e_img:
                print(f"Error drawing foreground card: {e_img}")
            
        # 3. Bottom Full-Width Solid Black Banner
        by = 680
        bh = H - by # 400
        
        if isinstance(accent_color, str):
            accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        else:
            accent_rgb = accent_color
            
        draw_ctx = ImageDraw.Draw(img)
        draw_ctx.rectangle([0, by, W, H], fill=(10, 10, 12))
        draw_ctx.rectangle([0, by, W, by + 6], fill=(*accent_rgb, 255))
        
        # 4. Draw Text
        max_w = W - 120 # 960px text width
        
        if line2:
            font1, size1, lines1, lh1, gap1 = _fit_wrapped(draw_ctx, line1, max_w, 100, start=48, min_size=24)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            y_start1 = by + 25 + (100 - h_text1) // 2
            
            _draw_lines(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=(*accent_rgb, 255), shadow=None)
            
            font2, size2, lines2, lh2, gap2 = _fit_wrapped(draw_ctx, line2, max_w, bh - 100 - 50, start=38, min_size=20)
            h_text2 = lh2 * len(lines2) + gap2 * (len(lines2) - 1)
            y_start2 = by + 125 + (bh - 100 - 50 - h_text2) // 2
            
            _draw_lines(draw_ctx, lines2, font2, lh2, gap2, y_start2, W, fill=(255, 255, 255), shadow=None)
        else:
            font1, size1, lines1, lh1, gap1 = _fit_wrapped(draw_ctx, line1, max_w, bh - 50, start=46, min_size=24)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            y_start1 = by + (bh - h_text1) // 2
            
            _draw_lines(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=(255, 255, 255), shadow=None)

    elif style == "premium_card":
        # ── PREMIUM CARD STYLE ───────────────────────────────────────────────
        draw = ImageDraw.Draw(img)
        
        # Dimensions & Coordinates
        bw = 980
        bx = (W - bw) // 2 # 50
        
        # Check text structure
        if line2:
            # Two-panel card (colored header, white body)
            header_h = 100
            body_h = 220
            card_h = header_h + body_h
            by = 700
            cr = 24
            
            # Prepare header (colored) and body (white) colors
            if isinstance(accent_color, str):
                accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
            else:
                accent_rgb = accent_color
                
            header_color = (*accent_rgb, 255)
            body_color = (255, 255, 255, 242) # 95% white
            
            # Render supersampled card parts
            card_img = Image.new("RGBA", (bw, card_h), (0, 0, 0, 0))
            
            # Header panel (top rounded)
            header_panel = _draw_supersampled_card((bw, header_h + cr), cr, header_color)
            card_img.paste(header_panel.crop((0, 0, bw, header_h)), (0, 0))
            
            # Body panel (bottom rounded)
            body_panel = _draw_supersampled_card((bw, body_h + cr), cr, body_color)
            card_img.paste(body_panel.crop((0, cr, bw, body_h + cr)), (0, header_h))
            
            # Draw shadow layer
            shadow_layer = _draw_soft_shadow((W, H), [bx, by, bx + bw, by + card_h], cr)
            img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
            
            # Composite card onto image
            card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            card_layer.paste(card_img, (bx, by))
            img = Image.alpha_composite(img, card_layer).convert("RGB")
            
            # Draw Text
            draw_ctx = ImageDraw.Draw(img)
            
            # Fit line1 in header
            font1, size1, lines1, lh1, gap1 = _fit_wrapped(draw_ctx, line1, bw - 60, header_h - 20, start=48, min_size=24)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            y_start1 = by + (header_h - h_text1) // 2
            
            # Contrast text color for header
            r, g, b = accent_rgb
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            h_text_fill = (40, 40, 40) if brightness > 128 else (255, 255, 255)
            
            _draw_lines(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=h_text_fill, shadow=None)
            
            # Fit line2 in body
            font2, size2, lines2, lh2, gap2 = _fit_wrapped(draw_ctx, line2, bw - 60, body_h - 40, start=44, min_size=22)
            h_text2 = lh2 * len(lines2) + gap2 * (len(lines2) - 1)
            y_start2 = by + header_h + (body_h - h_text2) // 2
            
            _draw_lines(draw_ctx, lines2, font2, lh2, gap2, y_start2, W, fill=(40, 40, 40), shadow=None)
            
        else:
            # Single-panel card (white body)
            card_h = 240
            by = 780
            cr = 24
            body_color = (255, 255, 255, 242)
            
            # Draw shadow layer
            shadow_layer = _draw_soft_shadow((W, H), [bx, by, bx + bw, by + card_h], cr)
            img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
            
            # Render and composite card
            card_img = _draw_supersampled_card((bw, card_h), cr, body_color)
            card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            card_layer.paste(card_img, (bx, by))
            img = Image.alpha_composite(img, card_layer).convert("RGB")
            
            # Draw Text
            draw_ctx = ImageDraw.Draw(img)
            
            # Fit line1 in card
            font1, size1, lines1, lh1, gap1 = _fit_wrapped(draw_ctx, line1, bw - 60, card_h - 40, start=54, min_size=24)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            y_start1 = by + (card_h - h_text1) // 2
            
            _draw_lines(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=(40, 40, 40), shadow=None)
            
    else:
        # ── CLASSIC GRADIENT STYLE ───────────────────────────────────────────
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
        _draw_lines(draw, lines1, font1, lh1, gap1, y_start, W, fill=accent_color, shadow=(0, 0, 0))

        # Draw line2 — white
        if line2:
            n1 = len(lines1)
            b1 = draw.textbbox((0, 0), lines1[-1], font=font1)
            pixel_bottom1 = y_start + lh1 * (n1 - 1) + gap1 * (n1 - 1) + b1[3]
            b2 = draw.textbbox((0, 0), lines2[0], font=font2)
            y2 = pixel_bottom1 + BLOCK_GAP - b2[1]
            _draw_lines(draw, lines2, font2, lh2, gap2, y2, W, fill=(255, 255, 255), shadow=(0, 0, 0))

    # ── BADGES & WATERMARKS ───────────────────────────────────────────────
    if badge_text:
        img = _draw_discount_badge(img, badge_text, accent_color)
    if watermark:
        img = _draw_watermark_capsule(img, watermark, accent_color)
    # ──────────────────────────────────────────────────────────────────────

    img = img.convert("RGB")

    if not out_path:
        base     = img_path.rsplit(".", 1)[0] if img_path else "overlay"
        out_path = base + "_overlay.jpg"

    img.save(out_path, "JPEG", quality=92)
    return out_path
