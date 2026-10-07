"""Opt-in optional-affiliate gate; isolated from the deployed studio.py.

This validates recorded evidence; human visual/source review remains mandatory.
Live channels additionally require an Ed25519 signature made by the local editor.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
FILES = ('manifest.json', 'caption.txt', 'card.png', 'affiliate.json', 'evidence.json')
CHECKS = ('full_image_seen', 'mobile_seen', 'thai_readable', 'subject_correct', 'source_checked', 'affiliate_checked')
# Keep this signed review key stable; it means readable in channel.language.
DISCLOSURE = 'ลิงก์ Affiliate — เพจอาจได้รับค่าคอมมิชชันจากการซื้อผ่านลิงก์นี้'

class GateError(ValueError):
    pass

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise GateError(f'Unreadable package file: {Path(path).name}') from exc

def aware(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('timezone missing')
        return result
    except (ValueError, TypeError) as exc:
        raise GateError('Timestamp must include timezone') from exc

def digest_package(package_dir):
    package = Path(package_dir)
    digest = hashlib.sha256()
    for name in FILES:
        try:
            data = (package / name).read_bytes()
        except OSError as exc:
            raise GateError(f'Missing required file: {name}') from exc
        digest.update(name.encode() + b'\0' + struct.pack('>Q', len(data)) + data)
    return digest.hexdigest()

def is_shopee(value):
    parsed = urlparse(str(value))
    host = (parsed.hostname or '').lower().rstrip('.')
    return parsed.scheme == 'https' and not parsed.username and any(host == x or host.endswith('.'+x) for x in ('shopee.co.th', 'shopee.com', 'shope.ee'))

def validate_package(package_dir, channel_config, now=None, allow_elapsed=False):
    package = Path(package_dir)
    digest_package(package)
    manifest = read_json(package/'manifest.json')
    affiliate = read_json(package/'affiliate.json')
    evidence = read_json(package/'evidence.json')
    if not isinstance(manifest, dict) or not isinstance(affiliate, dict) or not isinstance(evidence, dict):
        raise GateError('Package JSON roots must be objects')
    editorial = manifest.get('affiliate_enabled') is False
    if 'affiliate_enabled' in manifest and type(manifest['affiliate_enabled']) is not bool:
        raise GateError('affiliate_enabled must be an explicit boolean')
    for key in ('id', 'channel_key', 'page_id', 'scheduled_at', 'visual_type', 'status') + (() if editorial else ('product_id',)):
        if not manifest.get(key):
            raise GateError(f'Manifest missing {key}')
    if channel_config.get('enabled', True) is not True:
        raise GateError('Channel is disabled or identity is unresolved')
    for key in ('page_id', 'channel_key'):
        if str(manifest[key]) != str(channel_config.get(key)):
            raise GateError(f'Wrong {key}')
    current = now or datetime.now(timezone.utc)
    slot = aware(manifest['scheduled_at'])
    if slot-current>timedelta(days=75) or (not allow_elapsed and slot-current<timedelta(minutes=15)):
        raise GateError('Schedule outside 15-minute / 75-day release window')
    if channel_config.get('publish_time_local'):
        expected = str(channel_config['publish_time_local'])
        offset = channel_config.get('schedule_utc_offset_minutes')
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', expected) or type(offset) is not int or abs(offset)>840:
            raise GateError('Invalid channel local schedule policy')
        local = slot.astimezone(timezone(timedelta(minutes=offset)))
        if local.strftime('%H:%M') != expected or local.second or local.microsecond:
            raise GateError('Schedule does not match the channel local publication time')
    data = (package/'card.png').read_bytes()
    if len(data)<33 or data[:8]!=b'\x89PNG\r\n\x1a\n' or data[12:16]!=b'IHDR' or struct.unpack('>II',data[16:24])!=(1080,1350):
        raise GateError('Card must be a 1080x1350 PNG')
    caption = (package/'caption.txt').read_text(encoding='utf-8').strip()
    if not caption:
        raise GateError('Empty caption')
    if manifest['visual_type']=='ai_editorial' and 'AI' not in caption:
        raise GateError('AI illustration disclosure missing')
    if editorial:
        if manifest.get('product_id') not in (None, '') or affiliate != {'enabled': False}:
            raise GateError('Editorial package must have no product, URL or affiliate comment')
    else:
        _validate_product(manifest, affiliate, channel_config, current)
    entries = evidence.get('entries')
    if not isinstance(entries, list) or not entries:
        markers = channel_config.get('fiction_markers', [channel_config.get('fiction_marker', 'สมมติ')])
        visible = isinstance(markers, list) and any(isinstance(marker, str) and marker.strip() and marker.casefold() in caption.casefold() for marker in markers)
        if not (evidence.get('fictional') is True and evidence.get('editorial_note') and visible):
            raise GateError('Source evidence is empty')
    else:
        for entry in entries:
            url = urlparse(str(entry.get('url','')))
            host = url.hostname or ''
            if url.scheme != 'https' or not host or host in ('example.com','example.org','example.net') or host.endswith('.example') or not str(entry.get('claim','')).strip():
                raise GateError('Evidence requires an actual source and a specific claim')
            aware(entry.get('checked_at'))
    return manifest


def _validate_product(manifest, affiliate, channel_config, current):
    if manifest['product_id'] != affiliate.get('product_id'):
        raise GateError('Affiliate product does not match manifest')
    if manifest['channel_key'] not in affiliate.get('eligible_channels', []):
        raise GateError('Product not eligible for channel')
    category = affiliate.get('category')
    if category not in channel_config.get('allowed_categories', []):
        raise GateError('Product category not permitted')
    if 'chow' in manifest['channel_key'] and (category in ('cat','cat_food','cat_accessories') or 'แมว' in str(affiliate.get('name',''))):
        raise GateError('Cat product cannot be used on Chow Chow')
    if not affiliate.get('name') or not is_shopee(affiliate.get('url')):
        raise GateError('Affiliate needs a name and real Shopee URL')
    verified = aware(affiliate.get('verified_at'))
    if verified>current+timedelta(minutes=5) or current-verified>timedelta(days=30):
        raise GateError('Product verification is missing, future-dated or stale')
    if affiliate.get('verification_status', 'verified') != 'verified':
        raise GateError('pending_product_missing: destination/variant not verified')
    comment = str(affiliate.get('comment',''))
    links = re.findall(r'https?://[^\s<>]+', comment)
    if links != [affiliate['url']]:
        raise GateError('Comment must contain exactly its approved product URL')
    disclosure = channel_config.get('affiliate_disclosure', DISCLOSURE)
    if not isinstance(disclosure, str) or not disclosure.strip() or disclosure not in comment or affiliate.get('disclosure') != disclosure:
        raise GateError('Affiliate disclosure must appear in the comment')

def _review_payload(review):
    return json.dumps({k:v for k,v in review.items() if k!='signature'}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def approve_package(package_dir, reviewer='root-editor', notes='', checks=None):
    if reviewer!='root-editor':
        raise GateError('Only the root editor can release content')
    if not str(notes).strip() or not all((checks or {}).get(k) is True for k in CHECKS):
        raise GateError('Visual/source/product checks must all be explicitly true')
    review = {'reviewer':reviewer, 'reviewed_at':datetime.now(timezone.utc).isoformat(), 'package_sha256':digest_package(package_dir), 'notes':notes, 'checks':checks}
    key_path = os.getenv('STUDIO_EDITOR_KEY')
    if key_path:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(Path(key_path).read_bytes(), password=None)
        review['signature'] = base64.b64encode(key.sign(_review_payload(review))).decode()
    (Path(package_dir)/'review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return review

def verify_approval(package_dir, channel_config, now=None, allow_elapsed=False):
    manifest = validate_package(package_dir, channel_config, now, allow_elapsed=allow_elapsed)
    review = read_json(Path(package_dir)/'review.json')
    if review.get('reviewer')!='root-editor' or not review.get('notes') or not all(review.get('checks',{}).get(k) is True for k in CHECKS):
        raise GateError('Incomplete root review')
    aware(review.get('reviewed_at'))
    if review.get('package_sha256') != digest_package(package_dir):
        raise GateError('Content changed after review; reinspection required')
    if channel_config.get('require_signature'):
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        try:
            public = load_pem_public_key(channel_config['editor_public_key'].encode())
            public.verify(base64.b64decode(review['signature']), _review_payload(review))
        except Exception as exc:
            raise GateError('Root editor signature invalid or missing') from exc
    return manifest

def build_plan(package_dirs, channels, now=None, allow_elapsed=False):
    plans, slots, ids, remote_ids, products = [], set(), set(), set(), {}
    for directory in package_dirs:
        raw = read_json(Path(directory)/'manifest.json')
        if raw.get('channel_key') not in channels:
            raise GateError('Unknown channel')
        manifest = verify_approval(directory, channels[raw['channel_key']], now, allow_elapsed=allow_elapsed)
        slot = (manifest['page_id'], int(aware(manifest['scheduled_at']).timestamp()))
        remote = manifest.get('post_id') or manifest.get('remote_post_id')
        if slot in slots or manifest['id'] in ids or (remote and remote in remote_ids):
            raise GateError('Duplicate slot, package or remote post ID')
        if manifest.get('affiliate_enabled') is not False:
            prior = products.setdefault(manifest['channel_key'], [])
            for product_id, when in prior:
                if product_id==manifest['product_id'] and abs(aware(manifest['scheduled_at'])-when)<timedelta(days=7):
                    raise GateError('Product cooldown: use a different relevant verified SKU')
            prior.append((manifest['product_id'],aware(manifest['scheduled_at'])))
        slots.add(slot);ids.add(manifest['id'])
        if remote:
            remote_ids.add(remote)
        plans.append({**manifest, 'package_dir':str(Path(directory).resolve()), 'package_sha256':digest_package(directory)})
    return sorted(plans, key=lambda p:p['scheduled_at'])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'plan'])
    parser.add_argument('packages', nargs='+')
    parser.add_argument('--channels', default=str(ROOT/'channels.json'))
    args = parser.parse_args()
    channels = read_json(args.channels)
    if args.command=='plan':
        result = build_plan(args.packages, channels)
    else:
        result = [validate_package(p,channels[read_json(Path(p)/'manifest.json')['channel_key']]) for p in args.packages]
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:
        main()
    except GateError as exc:
        raise SystemExit(str(exc))
