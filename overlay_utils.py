# overlay_utils.py — PIL text overlay for Facebook bot images with calibrated news_card layout

import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BRAND_COLOR = (11, 47, 29)
DEFAULT_WATERMARK = "กรามค้าง SHORTS"

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Sarabun-ExtraBold.ttf")
if not os.path.exists(FONT_PATH):
    FONT_PATH = os.path.join(os.path.dirname(__file__), "Sarabun-ExtraBold.ttf")

_LEADING_VOWELS  = set('เแโใไ')
_COMBINING_CHARS = set('่้๊๋์ิีึืุูัํ็')
_UPPER_VOWELS    = set('ัิีึื็ํ')
_TONE_MARKS      = set('่้๊๋์')
_TAIL_CONSONANTS = {
    'ป': 'บ',
    'ฝ': 'ผ',
    'ฟ': 'พ',
    'ฬ': 'ล'
}

_cluster_re = re.compile(r'.[ัิ-ฺ็-๎]*')

def _draw_cluster_text(draw, text, x_start, y_start, font, fill, shadow_color=None, shadow_width=3, shift_factor=0.25):
    clusters = _cluster_re.findall(text)
    current_x = x_start
    size = font.size
    y_shift = int(size * shift_factor)
    
    offsets = [(-shadow_width, -shadow_width), (-shadow_width, 0), (-shadow_width, shadow_width),
               (0, -shadow_width), (0, shadow_width),
               (shadow_width, -shadow_width), (shadow_width, 0), (shadow_width, shadow_width)]
    
    for cluster in clusters:
        has_upper = any(c in _UPPER_VOWELS for c in cluster)
        has_tone = any(c in _TONE_MARKS for c in cluster)
        advance = draw.textlength(cluster, font=font)
        
        if has_upper and has_tone:
            base_parts = [c for c in cluster if c not in _TONE_MARKS]
            tone_parts = [c for c in cluster if c in _TONE_MARKS]
            
            base_str = "".join(base_parts)
            tone_str = "".join(tone_parts)
            
            consonant = base_str[0]
            measure_consonant = _TAIL_CONSONANTS.get(consonant, consonant)
            
            c_bbox = draw.textbbox((0, 0), measure_consonant, font=font)
            t_bbox = draw.textbbox((0, 0), tone_str, font=font)
            
            c_center = (c_bbox[0] + c_bbox[2]) / 2.0
            t_center = (t_bbox[0] + t_bbox[2]) / 2.0
            
            if shadow_color:
                for dx, dy in offsets:
                    draw.text((current_x + dx, y_start + dy), base_str, font=font, fill=shadow_color)
            draw.text((current_x, y_start), base_str, font=font, fill=fill)
            
            draw_x = current_x + (c_center - t_center)
            if shadow_color:
                for dx, dy in offsets:
                    draw.text((draw_x + dx, y_start - y_shift + dy), tone_str, font=font, fill=shadow_color)
            draw.text((draw_x, y_start - y_shift), tone_str, font=font, fill=fill)
        else:
            if shadow_color:
                for dx, dy in offsets:
                    draw.text((current_x + dx, y_start + dy), cluster, font=font, fill=shadow_color)
            draw.text((current_x, y_start), cluster, font=font, fill=fill)
            
        current_x += advance

def _draw_lines_shaping(draw, lines, font, line_h, gap, y_start, W, fill, shadow=(0, 0, 0)):
    y = y_start
    for line in lines:
        clean_line = line.replace('​', '').replace('\u200b', '')
        bw = draw.textbbox((0, 0), clean_line, font=font)[2]
        x  = (W - bw) // 2
        
        shadow_color = shadow if (shadow and (len(shadow) < 4 or shadow[3] > 0)) else None
        _draw_cluster_text(draw, clean_line, x, y, font, fill, shadow_color=shadow_color, shadow_width=3)
        y += line_h + gap
    return y

def _wrap_text(draw, text, font, max_width):
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return [text]
    if '​' in text or '\u200b' in text:
        text = text.replace('\u200b', '​')
        tokens = text.split('​')
        lines, current = [], ""
        for token in tokens:
            test = current + '​' + token if current else token
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

def _balance_wrap(draw, lines, font, max_width, min_ratio=0.42):
    if len(lines) <= 1:
        return lines
    last_text = lines[-1].strip()
    last_w    = draw.textbbox((0, 0), last_text, font=font)[2]
    prev_w    = draw.textbbox((0, 0), lines[-2], font=font)[2]
    is_orphan = (last_w < prev_w * min_ratio) or (len(last_text) <= 4)
    if not is_orphan:
        return lines
    merged   = lines[-2] + "​" + lines[-1]
    total_w  = draw.textbbox((0, 0), merged, font=font)[2]
    target_w = min(max_width, int(total_w * 0.55))
    rebalanced = _wrap_text(draw, merged, font, target_w)
    if all(draw.textbbox((0, 0), l, font=font)[2] <= max_width for l in rebalanced):
        return lines[:-2] + rebalanced
    return lines

def _fit_wrapped_font(draw, text, max_width, max_total_h, font_path, start=88, min_size=24):
    size = start
    while size >= min_size:
        font  = ImageFont.truetype(font_path, size)
        lines = _wrap_text(draw, text, font, max_width)
        lines = _balance_wrap(draw, lines, font, max_width)
        line_h = draw.textbbox((0, 0), "ก A", font=font)[3]
        gap    = int(size * 0.48)
        total  = line_h * len(lines) + gap * (len(lines) - 1)
        width_ok = all(draw.textbbox((0, 0), l, font=font)[2] <= max_width for l in lines)
        if total <= max_total_h and width_ok:
            return font, size, lines, line_h, gap
        size -= 2
    font   = ImageFont.truetype(font_path, min_size)
    lines  = _wrap_text(draw, text, font, max_width)
    lines  = _balance_wrap(draw, lines, font, max_width)
    line_h = draw.textbbox((0, 0), "ก A", font=font)[3]
    gap    = int(min_size * 0.48)
    return font, min_size, lines, line_h, gap

def _fit_wrapped(draw, text, max_width, max_total_h, start=88, min_size=24):
    return _fit_wrapped_font(draw, text, max_width, max_total_h, FONT_PATH, start, min_size)

def _draw_lines(draw, lines, font, line_h, gap, y_start, W, fill, shadow=(0, 0, 0)):
    y = y_start
    for line in lines:
        clean_line = line.replace('​', '').replace('\u200b', '')
        bw = draw.textbbox((0, 0), clean_line, font=font)[2]
        x  = (W - bw) // 2
        if shadow and (len(shadow) < 4 or shadow[3] > 0):
            for dx, dy in [(-3,-3),(-3,0),(-3,3),(0,-3),(0,3),(3,-3),(3,0),(3,3)]:
                draw.text((x + dx, y + dy), clean_line, font=font, fill=shadow)
        draw.text((x, y), clean_line, font=font, fill=fill)
        y += line_h + gap
    return y

def _remove_black_bars(img, threshold=20):
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
    W, H = img.size
    bw, bh = 180, 180
    ss = 4
    ss_w, ss_h = bw * ss, bh * ss
    badge_img = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge_img, "RGBA")
    
    if isinstance(accent_color, str):
        if accent_color.startswith("#"):
            accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        else:
            accent_rgb = (255, 69, 0)
    else:
        accent_rgb = accent_color
    fill_color = (*accent_rgb, 255)
    
    draw.ellipse([0, 0, ss_w, ss_h], fill=fill_color)
    draw.ellipse([8, 8, ss_w - 8, ss_h - 8], outline=(255, 255, 255, 255), width=8)
    
    font_size = 40 * ss
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
    bx, by = 40, 40
    
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

def _draw_top_right_badge(img, text, accent_color, W=1080, H=1080):
    temp_img = Image.new("RGBA", (100, 100))
    temp_draw = ImageDraw.Draw(temp_img)
    font_size = 22
    font = ImageFont.truetype(FONT_PATH, font_size)
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    pad_x, pad_y = 28, 16
    bw = tw + pad_x * 2
    bh = th + pad_y * 2
    
    ss = 4
    ss_w, ss_h = bw * ss, bh * ss
    ss_r = 16 * ss
    
    badge = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    
    if isinstance(accent_color, str):
        if accent_color.startswith("#"):
            accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        else:
            accent_rgb = (0, 191, 255)
    else:
        accent_rgb = accent_color
    
    draw.rectangle([0, 0, ss_w, ss_h - ss_r], fill=(*accent_rgb, 255))
    draw.rectangle([ss_r, ss_h - ss_r, ss_w, ss_h], fill=(*accent_rgb, 255))
    draw.ellipse([0, ss_h - 2 * ss_r, 2 * ss_r, ss_h], fill=(*accent_rgb, 255))
    
    ss_font = ImageFont.truetype(FONT_PATH, font_size * ss)
    ss_bbox = draw.textbbox((0, 0), text, font=ss_font)
    ss_tw = ss_bbox[2] - ss_bbox[0]
    ss_th = ss_bbox[3] - ss_bbox[1]
    
    tx = (ss_w - ss_tw) // 2 - ss_bbox[0]
    ty = (ss_h - ss_th) // 2 - ss_bbox[1]
    
    draw.text((tx, ty), text, font=ss_font, fill=(255, 255, 255, 255))
    
    badge = badge.resize((bw, bh), Image.Resampling.LANCZOS)
    img_rgba = img.convert("RGBA")
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_layer.paste(badge, (W - bw, 0))
    
    return Image.alpha_composite(img_rgba, badge_layer).convert("RGB")

def _draw_bottom_right_badge(img, text, text_color, border_w, font_path, W=1080, H=1080):
    temp_img = Image.new("RGBA", (100, 100))
    temp_draw = ImageDraw.Draw(temp_img)
    font_size = 17
    font = ImageFont.truetype(font_path, font_size)
    
    tw = temp_draw.textbbox((0, 0), text, font=font)[2]
    th = temp_draw.textbbox((0, 0), "ก A", font=font)[3]
    
    pad_x, pad_y = 22, 12
    bw = tw + pad_x * 2
    bh = th + pad_y * 2
    
    ss = 4
    ss_w, ss_h = bw * ss, bh * ss
    ss_r = 12 * ss
    
    badge = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    
    badge_bg = (255, 255, 255, 255)
    draw.rectangle([ss_r, 0, ss_w, ss_h], fill=badge_bg)
    draw.rectangle([0, ss_r, ss_r, ss_h], fill=badge_bg)
    draw.ellipse([0, 0, 2 * ss_r, 2 * ss_r], fill=badge_bg)
    
    ss_font = ImageFont.truetype(font_path, font_size * ss)
    ss_lh = draw.textbbox((0, 0), "ก A", font=ss_font)[3]
    
    tx = pad_x * ss
    ty = (ss_h - ss_lh) // 2
    
    # Dynamic outline if text color is too bright on white background
    r, g, b = text_color
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    if brightness > 180:
        badge_shadow = (0, 0, 0, 100)
    else:
        badge_shadow = None
        
    _draw_cluster_text(draw, text, tx, ty, ss_font, (*text_color, 255), shadow_color=badge_shadow, shadow_width=2, shift_factor=0.25)
    
    badge = badge.resize((bw, bh), Image.Resampling.LANCZOS)
    img_rgba = img.convert("RGBA")
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_layer.paste(badge, (W - bw - border_w, H - bh - border_w))
    
    return Image.alpha_composite(img_rgba, badge_layer).convert("RGB")


def _draw_top_left_brand_badge(img, logo_path, watermark, brand_color, border_w, font_path, W=1080, H=1080):
    temp_img = Image.new("RGBA", (100, 100))
    temp_draw = ImageDraw.Draw(temp_img)
    font_size = 22
    font = ImageFont.truetype(font_path, font_size)
    
    bbox = temp_draw.textbbox((0, 0), watermark, font=font)
    tw = bbox[2] - bbox[0]
    th = temp_draw.textbbox((0, 0), "ก A", font=font)[3]
    
    logo_size = 36
    pad_x, pad_y = 20, 10
    
    has_logo = logo_path and os.path.exists(logo_path)
    if has_logo:
        bw = pad_x * 2 + logo_size + 12 + tw
    else:
        bw = pad_x * 2 + tw
        
    bh = max(logo_size, th) + pad_y * 2
    
    ss = 4
    ss_w, ss_h = bw * ss, bh * ss
    ss_r = 16 * ss
    
    badge = Image.new("RGBA", (ss_w, ss_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    
    badge_bg = (255, 255, 255, 255)
    draw.rectangle([0, 0, ss_w - ss_r, ss_h], fill=badge_bg)
    draw.rectangle([ss_w - ss_r, 0, ss_w, ss_h - ss_r], fill=badge_bg)
    draw.ellipse([ss_w - 2 * ss_r, ss_h - 2 * ss_r, ss_w, ss_h], fill=badge_bg)
    
    tx = pad_x * ss
    if has_logo:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            mask = Image.new("L", logo.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, logo.size[0], logo.size[1]], fill=255)
            logo_circle = Image.new("RGBA", logo.size, (0, 0, 0, 0))
            logo_circle.paste(logo, (0, 0), mask)
            
            logo_circle = logo_circle.resize((logo_size * ss, logo_size * ss), Image.Resampling.LANCZOS)
            ly = (ss_h - logo_size * ss) // 2
            badge.paste(logo_circle, (pad_x * ss, ly), logo_circle)
            tx = (pad_x + logo_size + 12) * ss
        except Exception as e:
            print("Error drawing logo on badge:", e)
            
    ss_font = ImageFont.truetype(font_path, font_size * ss)
    ss_lh = draw.textbbox((0, 0), "ก A", font=ss_font)[3]
    ty = (ss_h - ss_lh) // 2
    
    draw.text((tx, ty), watermark, font=ss_font, fill=(*brand_color, 255))
    
    badge_resized = badge.resize((bw, bh), Image.Resampling.LANCZOS)
    img_rgba = img.convert("RGBA")
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_layer.paste(badge_resized, (0, 0))
    
    return Image.alpha_composite(img_rgba, badge_layer).convert("RGB")

def add_overlay(img_path, line1, line2, accent_color=None, out_path=None, font_name=None, style="news_card", badge_text=None, watermark=None):
    """Delegates overlay rendering directly to Playwright HTML/CSS card renderer (card/render_card.py)."""
    if not out_path:
        base = img_path.rsplit(".", 1)[0] if (img_path and "." in img_path) else "overlay"
        out_path = base + "_card.png"
    try:
        from card.render_card import render_news_card
        return render_news_card(img_path, line1, line2, out_path, badge_text=watermark or badge_text)
    except Exception as card_err:
        print(f"[Overlay Delegate Warning] HTML card render failed ({card_err}), using legacy PIL...")

