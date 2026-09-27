"""Offline, photo-led sales cards. No posting, AI calls, or implied promotions."""
import base64
import hashlib
import json
import re
import uuid
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def _photos(paths):
    if isinstance(paths, (str, Path)):
        paths = [paths]
    result, seen = [], set()
    for item in paths or []:
        path = Path(item).resolve()
        raw = path.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Sales image exceeds 15 MB')
        with Image.open(path) as im:
            im.verify()
            mime = Image.MIME.get(im.format, 'image/png')
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in seen:
            seen.add(digest)
            result.append('data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii'))
        if len(result) == 4:
            break
    if not result:
        raise ValueError('At least one valid product photo is required')
    return result


def build_sales_data(photos, title, subtitle='', *, brand='', accent='#ffe36d',
                     platform='facebook', badge_text=None, price=None,
                     price_verified=False, width=1080, height=1080):
    if platform not in ('facebook', 'x', 'threads'):
        raise ValueError('Unsupported sales platform')
    if (width, height) not in ((1080,1080), (1080,1350)):
        raise ValueError('Supported card sizes: 1080 square or 1080 x 1350')
    title = re.sub(r'\s+', ' ', str(title or '')).strip()
    if not title:
        raise ValueError('A product title is required')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', accent):
        raise ValueError('Accent must be a six-digit hex color')
    if platform == 'threads':
        brand = '@tongono21'
        accent = '#e9dfc9'
    elif platform == 'x':
        brand = 'Jaw Dropped'
        accent = '#f4ee7b'
    if badge_text is not None:
        brand = str(badge_text)
    prepared = _photos(photos)
    return dict(photos=prepared, layout=f'photos-{len(prepared)}', title=title,
                subtitle=re.sub(r'\s+', ' ', str(subtitle or '')).strip(),
                brand=brand, accent=accent, platform=platform,
                price=str(price).strip() if price_verified and price is not None else '',
                width=width, height=height)


def build_html(data, root=ROOT):
    root = Path(root)
    faces = []
    for family, filename in (('Kanit','Kanit-Bold.ttf'), ('Sarabun','Sarabun-ExtraBold.ttf')):
        font = root/'fonts'/filename
        if not font.is_file():
            raise FileNotFoundError(f'Required card font missing: {filename}')
        encoded = base64.b64encode(font.read_bytes()).decode('ascii')
        faces.append(f"@font-face{{font-family:{family};src:url(data:font/ttf;base64,{encoded}) format('truetype');font-weight:700;}}")
    payload = json.dumps(data, ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return (root/'sales_card.html').read_text(encoding='utf-8').replace('/*FONTS*/','\n'.join(faces)).replace('/*DATA*/', 'const data = '+payload+';')


def render_sales_card(photos, title, subtitle, out_path, *, theme=None,
                      platform='facebook', badge_text=None, price=None,
                      price_verified=False, width=1080, height=1080):
    from playwright.sync_api import sync_playwright
    theme = theme or {}
    data = build_sales_data(photos,title,subtitle,brand=theme.get('watermark',''),
        accent=theme.get('accent','#ffe36d'),platform=platform,badge_text=badge_text,
        price=price,price_verified=price_verified,width=width,height=height)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
            page.route('http://**/*', lambda route: route.abort())
            page.route('https://**/*', lambda route: route.abort())
            page.set_content(build_html(data),wait_until='load')
            page.wait_for_function('window.__READY__ === true || Boolean(window.__ERROR__)',timeout=20000)
            error = page.evaluate('window.__ERROR__ || null')
            if error:
                raise ValueError('Sales card render rejected: '+str(error))
            page.locator('#canvas').screenshot(path=str(out))
            qc = page.evaluate('window.__QC__')
            out.with_suffix(out.suffix+'.qc.json').write_text(json.dumps(qc,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            browser.close()
    return str(out)


def sales_title(detail):
    """Use the supplied product heading, not a generated promise or testimonial."""
    title = str(detail or '').splitlines()[0] if str(detail or '').strip() else ''
    title = re.sub(r'【[^】]*】|\[[^\]]*\]', '', title).split('|')[0].strip()
    title = re.split(r'ราคา\s*[:฿]?\s*\d|฿\s*\d', title, maxsplit=1)[0].strip()
    # Keep a heading manageable without cutting a Thai combining mark.
    if len(title) > 85:
        prefix=title[:82]
        boundary=prefix.rfind(' ')
        if boundary > 35:
            prefix=prefix[:boundary]
        title=prefix.rstrip()+'…'
    return title or 'รายละเอียดสินค้า'


def download_sales_photos(urls, output_dir, *, request_get=None):
    """Use up to four distinct images already supplied in a product's gallery."""
    import requests
    from urllib.parse import urlparse
    request_get = request_get or requests.get
    candidates = urls if isinstance(urls,(list,tuple)) else re.split(r'\s+',str(urls or '').strip())
    candidates=list(dict.fromkeys(str(u).strip() for u in candidates if str(u).strip()))[:4]
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    paths, seen = [],set()
    try:
        for url in candidates:
            parsed=urlparse(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Product image URLs must be HTTPS without credentials')
            response=request_get(url,timeout=20,stream=True,headers={'User-Agent':'Mozilla/5.0'})
            try:
                response.raise_for_status()
                raw=bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    raw.extend(chunk)
                    if len(raw)>MAX_IMAGE_BYTES:
                        raise ValueError('Product image exceeds 15 MB')
            finally:
                response.close()
            digest=hashlib.sha256(raw).hexdigest()
            if digest in seen:
                continue
            path=output_dir/f'sales_source_{uuid.uuid4().hex}.img'
            path.write_bytes(raw)
            paths.append(str(path))
            with Image.open(path) as im:
                im.verify()
            seen.add(digest)
        if not paths:
            raise ValueError('Product gallery has no valid images')
        return paths
    except Exception:
        for path in paths:
            Path(path).unlink(missing_ok=True)
        raise
