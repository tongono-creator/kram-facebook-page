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
    
    _draw_cluster_text(draw, text, tx, ty, ss_font, (*text_color, 255), shadow_color=None, shift_factor=0.25)
    
    badge = badge.resize((bw, bh), Image.Resampling.LANCZOS)
    img_rgba = img.convert("RGBA")
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_layer.paste(badge, (W - bw - border_w, H - bh - border_w))
    
    return Image.alpha_composite(img_rgba, badge_layer).convert("RGB")

def add_overlay(img_path, line1, line2, accent_color, out_path=None, font_name=None, style="news_card", badge_text=None, watermark=None):
    """
    Overlays text directly on the image.
    Supports:
      - "news_card": Upgraded style with centered foreground photo card, border, bottom-right white badge.
      - "premium_card": Tilted card overlay.
      - "gradient": Dark gradient with white text.
    """
    global FONT_PATH
    
    if watermark in (None, "คราม Kram", "Chow Chow", "Rocket 21", "พริก 10 เม็ด", "X Bot", "???? Kram", "???? 10 ????"):
        watermark = DEFAULT_WATERMARK

    W, H = 1080, 1080
    
    if img_path and os.path.exists(img_path):
        img = Image.open(img_path).convert("RGB")
        img = _remove_black_bars(img)
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
        img = img.resize((W, H), Image.LANCZOS)
    else:
        img = Image.new("RGB", (W, H), (15, 15, 20))

    if style == "news_card":
        current_font_path = FONT_PATH
        if font_name:
            current_font_path = os.path.join(os.path.dirname(__file__), "fonts", font_name)
            if not os.path.exists(current_font_path):
                current_font_path = os.path.join(os.path.dirname(__file__), font_name)
        if not os.path.exists(current_font_path):
            current_font_path = os.path.join(os.path.dirname(__file__), "fonts", "Sarabun-ExtraBold.ttf")
        if not os.path.exists(current_font_path):
            current_font_path = FONT_PATH
            
        border_w = 16
        
        # 1. Background Blur & Dimming
        bg_blur = img.copy().filter(ImageFilter.GaussianBlur(35))
        dark_mask = Image.new("RGBA", (W, H), (0, 0, 0, 130))
        bg_blur = Image.alpha_composite(bg_blur.convert("RGBA"), dark_mask).convert("RGB")
        img = bg_blur
        
        # 2. Foreground Photo Card (centered in the top area [50, 630])
        if img_path and os.path.exists(img_path):
            try:
                orig = Image.open(img_path).convert("RGB")
                orig = _remove_black_bars(orig)
                ow, oh = orig.size
                aspect = ow / oh
                
                mw, mh = 980, 580
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
                iy = 50 + (580 - ih) // 2
                
                shadow_layer = _draw_soft_shadow((W, H), [ix, iy, ix + iw, iy + ih], cr, blur_radius=12)
                img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
                
                img_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                img_layer.paste(orig_resized, (ix, iy), mask_img.convert("L"))
                img = Image.alpha_composite(img, img_layer).convert("RGB")
                
                border_card = _draw_supersampled_card((iw, ih), cr, (0, 0, 0, 0), border_color=(255, 255, 255, 180), border_width=3)
                border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                border_layer.paste(border_card, (ix, iy))
                img = Image.alpha_composite(img.convert("RGBA"), border_layer).convert("RGB")
            except Exception as e_img:
                print(f"Error drawing foreground card: {e_img}")
            
        # 3. Bottom Gradient
        by = 640
        bh = H - by - border_w
        img = _apply_bottom_gradient(img, by, H - border_w, max_alpha=245)
        
        draw_ctx = ImageDraw.Draw(img)
        E_margin = 10
        max_w = W - 2 * E_margin - 2 * border_w
        
        if accent_color:
            if isinstance(accent_color, str):
                if accent_color.startswith("#"):
                    accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                else:
                    accent_rgb = BRAND_COLOR
            else:
                accent_rgb = accent_color
        else:
            accent_rgb = BRAND_COLOR
            
        headline_color = (255, 230, 0)
        
        if line2:
            font1, size1, lines1, lh1, gap1 = _fit_wrapped_font(draw_ctx, line1, max_w, 150, current_font_path, start=68, min_size=32)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            
            font2, size2, lines2, lh2, gap2_dyn = _fit_wrapped_font(draw_ctx, line2, max_w, bh - 150 - 10, current_font_path, start=40, min_size=24)
            gap2 = 20
            h_text2 = lh2 * len(lines2) + gap2 * (len(lines2) - 1)
            
            gap_between_lines = 20
            total_text_h = h_text1 + gap_between_lines + h_text2
            
            bottom_margin = 30
            y_start = H - border_w - bottom_margin - total_text_h
            
            _draw_lines_shaping(draw_ctx, lines1, font1, lh1, gap1, y_start, W, fill=headline_color, shadow=(0, 0, 0, 220))
            
            y_start_desc = y_start + h_text1 + gap_between_lines
            _draw_lines_shaping(draw_ctx, lines2, font2, lh2, gap2, y_start_desc, W, fill=(255, 255, 255, 255), shadow=(0, 0, 0, 220))
        else:
            font1, size1, lines1, lh1, gap1 = _fit_wrapped_font(draw_ctx, line1, max_w, bh - 40, current_font_path, start=68, min_size=32)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            
            bottom_margin = 30
            y_start1 = H - border_w - bottom_margin - h_text1
            
            _draw_lines_shaping(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=headline_color, shadow=(0, 0, 0, 220))
            
        img = _draw_bottom_right_badge(img, watermark, BRAND_COLOR, border_w, current_font_path)
        
        draw_border = ImageDraw.Draw(img)
        draw_border.rectangle([0, 0, W, border_w], fill=(*BRAND_COLOR, 255))
        draw_border.rectangle([0, H - border_w, W, H], fill=(*BRAND_COLOR, 255))
        draw_border.rectangle([0, 0, border_w, H], fill=(*BRAND_COLOR, 255))
        draw_border.rectangle([W - border_w, 0, W, H], fill=(*BRAND_COLOR, 255))

    elif style == "premium_card":
        draw = ImageDraw.Draw(img)
        bw = 980
        bx = (W - bw) // 2
        
        if line2:
            header_h = 100
            body_h = 220
            card_h = header_h + body_h
            by = 700
            cr = 24
            
            if isinstance(accent_color, str):
                if accent_color.startswith("#"):
                    accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                else:
                    accent_rgb = BRAND_COLOR
            else:
                accent_rgb = accent_color
                
            header_color = (*accent_rgb, 255)
            body_color = (255, 255, 255, 242)
            
            card_img = Image.new("RGBA", (bw, card_h), (0, 0, 0, 0))
            header_panel = _draw_supersampled_card((bw, header_h + cr), cr, header_color)
            card_img.paste(header_panel.crop((0, 0, bw, header_h)), (0, 0))
            
            body_panel = _draw_supersampled_card((bw, body_h + cr), cr, body_color)
            card_img.paste(body_panel.crop((0, cr, bw, body_h + cr)), (0, header_h))
            
            shadow_layer = _draw_soft_shadow((W, H), [bx, by, bx + bw, by + card_h], cr)
            img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
            
            card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            card_layer.paste(card_img, (bx, by))
            img = Image.alpha_composite(img, card_layer).convert("RGB")
            
            draw_ctx = ImageDraw.Draw(img)
            font1, size1, lines1, lh1, gap1 = _fit_wrapped(draw_ctx, line1, bw - 60, header_h - 20, start=48, min_size=24)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            y_start1 = by + (header_h - h_text1) // 2
            
            r, g, b = accent_rgb
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            h_text_fill = (40, 40, 40) if brightness > 128 else (255, 255, 255)
            
            _draw_lines(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=h_text_fill, shadow=None)
            
            font2, size2, lines2, lh2, gap2 = _fit_wrapped(draw_ctx, line2, bw - 60, body_h - 40, start=44, min_size=22)
            h_text2 = lh2 * len(lines2) + gap2 * (len(lines2) - 1)
            y_start2 = by + header_h + (body_h - h_text2) // 2
            
            _draw_lines(draw_ctx, lines2, font2, lh2, gap2, y_start2, W, fill=(40, 40, 40), shadow=None)
        else:
            card_h = 240
            by = 780
            cr = 24
            body_color = (255, 255, 255, 242)
            
            shadow_layer = _draw_soft_shadow((W, H), [bx, by, bx + bw, by + card_h], cr)
            img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
            
            card_img = _draw_supersampled_card((bw, card_h), cr, body_color)
            card_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            card_layer.paste(card_img, (bx, by))
            img = Image.alpha_composite(img, card_layer).convert("RGB")
            
            draw_ctx = ImageDraw.Draw(img)
            font1, size1, lines1, lh1, gap1 = _fit_wrapped(draw_ctx, line1, bw - 60, card_h - 40, start=54, min_size=24)
            h_text1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            y_start1 = by + (card_h - h_text1) // 2
            
            _draw_lines(draw_ctx, lines1, font1, lh1, gap1, y_start1, W, fill=(40, 40, 40), shadow=None)
            
    else:
        # gradient style
        start_y = 650
        img = _apply_bottom_gradient(img, start_y, H)
        draw = ImageDraw.Draw(img)
        PAD_X = 60
        PAD_Y = 40
        max_w = W - PAD_X * 2
        text_zone_h = H - start_y - PAD_Y * 2
        BLOCK_GAP = 12
        
        size1 = 110
        size2 = 76 if line2 else 0
        
        if isinstance(accent_color, str):
            if accent_color.startswith("#"):
                accent_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
            else:
                accent_rgb = BRAND_COLOR
        else:
            accent_rgb = accent_color
            
        while size1 >= 40:
            font1 = ImageFont.truetype(FONT_PATH, size1)
            font2 = ImageFont.truetype(FONT_PATH, size2) if line2 else None
            
            lines1 = _wrap_text(draw, line1, font1, max_w)
            lines1 = _balance_wrap(draw, lines1, font1, max_w)
            lh1 = draw.textbbox((0, 0), "ก A", font=font1)[3]
            gap1 = max(6, size1 // 8)
            total_h1 = lh1 * len(lines1) + gap1 * (len(lines1) - 1)
            
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
                
            width_ok = all(draw.textbbox((0, 0), l, font=font1)[2] <= max_w for l in lines1)
            if line2:
                width_ok = width_ok and all(draw.textbbox((0, 0), l, font=font2)[2] <= max_w for l in lines2)
                
            if total_h <= text_zone_h and width_ok:
                break
                
            size1 -= 4
            if line2:
                size2 = max(24, int(size1 * 0.7))
                
        y_start = start_y + (H - start_y - total_h) // 2
        _draw_lines(draw, lines1, font1, lh1, gap1, y_start, W, fill=accent_rgb, shadow=(0, 0, 0))
        
        if line2:
            n1 = len(lines1)
            b1 = draw.textbbox((0, 0), lines1[-1], font=font1)
            pixel_bottom1 = y_start + lh1 * (n1 - 1) + gap1 * (n1 - 1) + b1[3]
            b2 = draw.textbbox((0, 0), lines2[0], font=font2)
            y2 = pixel_bottom1 + BLOCK_GAP - b2[1]
            _draw_lines(draw, lines2, font2, lh2, gap2, y2, W, fill=(255, 255, 255), shadow=(0, 0, 0))

    if badge_text:
        img = _draw_discount_badge(img, badge_text, accent_color)
    if watermark:
        if style == "news_card":
            pass # Pinned in bottom-right already
        else:
            img = _draw_watermark_capsule(img, watermark, accent_color)

    img = img.convert("RGB")
    if not out_path:
        base = img_path.rsplit(".", 1)[0] if img_path else "overlay"
        out_path = base + "_overlay.jpg"
        
    img.save(out_path, "JPEG", quality=92)
    return out_path
