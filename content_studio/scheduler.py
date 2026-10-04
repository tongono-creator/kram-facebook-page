"""Release only root-reviewed packages; default dry-run never writes remotely."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
import studio

class ScheduleError(RuntimeError):
    pass

class ApiError(ScheduleError):
    def __init__(self, method, status=0):
        self.method, self.status = method, status
        super().__init__(f'Facebook {method} failed (HTTP {status or "unavailable"})')

class FacebookApi:
    def __init__(self, channel):
        token = os.getenv(channel.get('token_env', 'PAGE_ACCESS_TOKEN'))
        if not token:
            raise ScheduleError('Configured token environment variable is missing')
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer ' + token
        self.page_id = str(channel['page_id'])

    def request(self, method, path, **kwargs):
        # Pagination uses cursors, never Facebook's next URL containing a token.
        try:
            response = self.session.request(method, 'https://graph.facebook.com/v25.0/' + path,
                                            timeout=(15, 90), **kwargs)
        except requests.RequestException:
            raise ApiError(method) from None
        if not 200 <= response.status_code < 300:
            raise ApiError(method, response.status_code)
        try:
            result = response.json()
        except ValueError:
            raise ApiError(method, response.status_code) from None
        if not isinstance(result, dict) or result.get('error'):
            raise ApiError(method, response.status_code)
        return result

    def identity(self):
        return self.request('GET', 'me', params={'fields': 'id,name'})

    def followers(self):
        try:
            return self.request('GET', self.page_id, params={'fields': 'followers_count'}).get('followers_count')
        except ApiError:
            return None

    def posts(self, published=False):
        edge = 'published_posts' if published else 'scheduled_posts'
        params = {'fields': 'id,message,scheduled_publish_time,created_time,attachments{target,subattachments{target}}', 'limit': 100}
        seen = set()
        while True:
            result = self.request('GET', f'{self.page_id}/{edge}', params=params)
            if not isinstance(result.get('data'), list):
                raise ScheduleError('Queue response missing data; refusing incomplete readback')
            yield from result.get('data', [])
            paging = result.get('paging', {})
            cursor = paging.get('cursors', {}).get('after') if paging.get('next') else None
            if not cursor:
                break
            if cursor in seen:
                raise ScheduleError('Pagination cursor repeated; refusing incomplete readback')
            seen.add(cursor)
            params['after'] = cursor

    def schedule(self, package, caption, timestamp):
        with (Path(package)/'card.png').open('rb') as photo:
            return self.request('POST', f'{self.page_id}/photos',
                data={'message': caption, 'published': 'false', 'unpublished_content_type': 'SCHEDULED',
                      'scheduled_publish_time': str(timestamp)}, files={'source': ('card.png', photo, 'image/png')})

def atomic_json(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

@contextmanager
def ledger_lock(root):
    path = root/'content_studio_ledger.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ScheduleError('Scheduler lock exists; inspect interrupted run before clearing') from None
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)

class GitStateSync:
    """Commit only explicit state paths; push durable reservation before POST."""
    def __init__(self, root, branch=None):
        self.root = Path(root)
        self.branch = branch or os.getenv('STUDIO_STATE_BRANCH')
        if not self.branch:
            raise ScheduleError('STUDIO_STATE_BRANCH required for git state sync')

    def git(self, *args, allow_failure=False):
        result = subprocess.run(['git', *args], cwd=self.root, capture_output=True, text=True)
        if result.returncode and not allow_failure:
            raise ScheduleError('Git state operation failed; remote response withheld')
        return result

    def __call__(self, paths):
        names = [str(Path(p).relative_to(self.root)).replace('\\', '/') for p in paths]
        staged = self.git('diff', '--cached', '--name-only').stdout.splitlines()
        if any(name not in names for name in staged):
            raise ScheduleError('Unrelated staged files; use a dedicated clean checkout')
        self.git('add', '--', *names)
        if self.git('diff', '--cached', '--quiet', allow_failure=True).returncode:
            self.git('commit', '-m', 'Record reviewed content scheduling state', '--', *names)
        for _ in range(3):
            if not self.git('push', 'origin', f'HEAD:refs/heads/{self.branch}', allow_failure=True).returncode:
                return
            self.git('fetch', 'origin', self.branch)
            self.git('rebase', f'origin/{self.branch}')
        raise ScheduleError('Reservation/state push failed; inspect ledger before any retry')

def attachment_ids(post):
    found = set()
    def walk(value):
        if isinstance(value, dict):
            target = value.get('target')
            if isinstance(target, dict) and target.get('id'):
                found.add(str(target['id']))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(post.get('attachments', {}))
    return found

def timestamp(post):
    try:
        return int(post.get('scheduled_publish_time', 0))
    except (ValueError, TypeError):
        return 0


class Scheduler:
    def __init__(self, repo_root, channel, api=None, sync=None):
        self.root, self.channel = Path(repo_root).resolve(), channel
        self.api, self.sync = api, sync
        self.path = self.root/'content_studio_ledger.json'
        self.mapping = self.root/'affiliate_post_products.json'
        self.ledger = studio.read_json(self.path) if self.path.exists() else {}
        if channel.get('platform') != 'facebook' or channel.get('enabled') is not True:
            raise ScheduleError('Only enabled Facebook channels use this adapter')

    def save(self, package_id, status, **fields):
        if self.path.exists():
            self.ledger = studio.read_json(self.path)  # retain records merged during Git synchronization
        self.ledger[package_id] = {**self.ledger.get(package_id, {}), **fields,
                                  'status': status, 'updated_at': datetime.now(timezone.utc).isoformat()}
        atomic_json(self.path, self.ledger)
        if self.sync:
            self.sync([self.path])

    def remember(self, plan, post):
        product = studio.read_json(Path(plan['package_dir'])/'affiliate.json')
        data = studio.read_json(self.mapping) if self.mapping.exists() else {}
        entries = data.setdefault('facebook', {})
        ids = {str(post['id']), str(post['id']).rsplit('_', 1)[-1], *attachment_ids(post)}
        if self.ledger.get(plan['id'], {}).get('photo_id'):
            ids.add(str(self.ledger[plan['id']]['photo_id']))
        for identifier in ids:
            selected = {'name': product['name'], 'url': product['url'], 'comment': product['comment']}
            if identifier in entries and entries[identifier] not in (selected, {'name':product['name'],'url':product['url']}):
                raise ScheduleError('Affiliate mapping conflict; existing product preserved')
            entries[identifier] = selected
        atomic_json(self.mapping, data)
        if self.sync:
            self.sync([self.mapping, self.path])

    def match(self, plan, caption, posts, published=False):
        prior = self.ledger.get(plan['id'], {})
        slot = int(studio.aware(plan['scheduled_at']).timestamp())
        matches = []
        for post in posts:
            if post.get('message') != caption:
                continue
            # A published post without original schedule cannot prove the reserved slot.
            if timestamp(post) != slot:
                if not published or not prior.get('post_id') or not prior.get('photo_id'):
                    continue
                try:
                    if abs(int(studio.aware(post['created_time']).timestamp())-slot)>1800:
                        continue
                except (KeyError, studio.GateError):
                    continue
            if prior.get('post_id') and str(post.get('id')) != str(prior['post_id']):
                continue
            photos = attachment_ids(post)
            if not photos or (prior.get('photo_id') and str(prior['photo_id']) not in photos):
                continue
            matches.append(post)
        if len(matches)>1:
            raise ScheduleError('Multiple matching posts; manual reconciliation required')
        return matches[0] if matches else None

    def _run(self, plans, publish, live_preview):
        if not publish and not live_preview:
            return [{'id': p['id'], 'status': 'dry_run', 'scheduled_at': p['scheduled_at']} for p in plans]
        self.api = self.api or FacebookApi(self.channel)
        identity = self.api.identity()
        if str(identity.get('id')) != str(self.channel['page_id']) or identity.get('name') != self.channel.get('page_name', self.channel.get('name')):
            raise ScheduleError('Token identity does not match configured page id and name')
        scheduled = list(self.api.posts())
        published = None
        results = []
        for plan in plans:
            caption = (Path(plan['package_dir'])/'caption.txt').read_text(encoding='utf-8').strip()
            prior = self.ledger.get(plan['id'])
            if prior and prior.get('package_sha256') != plan['package_sha256']:
                raise ScheduleError('Reserved package changed; inspect remote queue manually')
            match = self.match(plan, caption, scheduled) if prior else None
            if prior and not match:
                published = published if published is not None else list(self.api.posts(published=True))
                match = self.match(plan, caption, published, published=True)
            if match:
                if publish:
                    self.remember(plan, match)
                    self.save(plan['id'], 'verified', package_sha256=plan['package_sha256'], post_id=match['id'])
                results.append({'id': plan['id'], 'status': 'reconciled', 'post_id': match['id']})
                continue
            if prior:
                results.append({'id': plan['id'], 'status': 'held', 'reason': 'prior_reservation_requires_reconciliation'})
                continue
            slot = int(studio.aware(plan['scheduled_at']).timestamp())
            for record in self.ledger.values():
                if record.get('page_id')==plan['page_id'] and record.get('product_id')==plan['product_id'] and record.get('scheduled_at'):
                    if abs(slot-int(studio.aware(record['scheduled_at']).timestamp())) < 7*86400:
                        raise ScheduleError('Product cooldown conflicts with earlier reserved package')
            if any(timestamp(post)==slot for post in scheduled):
                raise ScheduleError('A different live post occupies this scheduled slot')
            if not publish:
                results.append({'id': plan['id'], 'status': 'live_preview'})
                continue
            studio.verify_approval(plan['package_dir'], self.channel)
            if studio.digest_package(plan['package_dir']) != plan['package_sha256']:
                raise ScheduleError('Package changed while preparing release')
            self.save(plan['id'], 'publishing', package_sha256=plan['package_sha256'],
                      page_id=plan['page_id'], scheduled_at=plan['scheduled_at'], product_id=plan['product_id'])
            try:
                response = self.api.schedule(plan['package_dir'], caption, slot)
            except ApiError as exc:
                rejected = 400 <= exc.status < 500 and exc.status not in (408,409,429)
                self.save(plan['id'], 'failed' if rejected else 'unknown')
                raise
            except Exception:
                self.save(plan['id'], 'unknown')
                raise ScheduleError('Write outcome unknown; reconcile before retry') from None
            photo_id, post_id = response.get('id'), response.get('post_id')
            self.save(plan['id'], 'publishing', photo_id=photo_id, post_id=post_id)
            if not photo_id or not post_id:
                self.save(plan['id'], 'unknown')
                raise ScheduleError('Photo response incomplete; reconcile before retry')
            # Store mapping immediately even if readback fails, then verify live photo and slot.
            self.remember(plan, {'id': post_id, 'attachments': {'target': {'id': photo_id}}})
            scheduled = list(self.api.posts())
            match = self.match(plan, caption, scheduled)
            if not match:
                self.save(plan['id'], 'unknown')
                raise ScheduleError('Scheduled photo readback not verified; never retry blindly')
            self.save(plan['id'], 'verified')
            results.append({'id': plan['id'], 'status': 'verified', 'post_id': post_id})
        return results

    def run(self, package_dirs, publish=False, live_preview=False):
        for directory in package_dirs:
            raw = studio.read_json(Path(directory)/'manifest.json')
            studio.verify_approval(directory, self.channel, allow_elapsed=raw.get('id') in self.ledger)
        plans = studio.build_plan(package_dirs, {self.channel['channel_key']: self.channel}, allow_elapsed=True)
        if publish:
            with ledger_lock(self.root):
                # Reload under the lock so two processes cannot reserve the same package.
                self.ledger = studio.read_json(self.path) if self.path.exists() else {}
                return self._run(plans, publish, live_preview)
        return self._run(plans, publish, live_preview)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', required=True)
    parser.add_argument('--channel', required=True)
    parser.add_argument('--channels', default=str(studio.ROOT/'channels.json'))
    parser.add_argument('--packages', nargs='+')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true')
    modes.add_argument('--publish', action='store_true')
    parser.add_argument('--live-preview', action='store_true')
    parser.add_argument('--git-state', action='store_true')
    parser.add_argument('--audit', action='store_true', help='Read-only live identity, full queue count and optional followers')
    args = parser.parse_args(argv)
    channel = studio.read_json(args.channels).get(args.channel)
    if not channel:
        raise ScheduleError('Unknown configured channel')
    if channel.get('repo_root') and Path(channel['repo_root']).resolve() != Path(args.repo_root).resolve():
        raise ScheduleError('Repository does not match configured channel')
    if channel.get('repository_slug'):
        origin = subprocess.run(['git','remote','get-url','origin'],cwd=args.repo_root,capture_output=True,text=True)
        remote = origin.stdout.strip()
        parsed = urlparse(remote)
        slug = remote.removeprefix('git@github.com:') if remote.startswith('git@github.com:') else parsed.path.lstrip('/') if parsed.hostname=='github.com' else ''
        if origin.returncode or slug.removesuffix('.git').casefold()!=channel['repository_slug'].casefold():
            raise ScheduleError('Git origin does not match the configured repository')
    if args.audit:
        if args.publish:
            raise ScheduleError('Audit cannot publish')
        scheduler = Scheduler(args.repo_root, channel)
        api = FacebookApi(channel)
        identity = api.identity()
        if str(identity.get('id'))!=str(channel['page_id']) or identity.get('name')!=channel.get('page_name',channel.get('name')):
            raise ScheduleError('Audit token belongs to a different page')
        print(json.dumps({'channel':args.channel,'identity':identity,'scheduled_count':len(list(api.posts())),
                          'followers_count':api.followers(),'checked_at':datetime.now(timezone.utc).isoformat()},ensure_ascii=False))
        return 0
    if not args.packages:
        raise ScheduleError('--packages required outside audit mode')
    sync = GitStateSync(args.repo_root) if args.git_state and args.publish else None
    result = Scheduler(args.repo_root, channel, sync=sync).run(args.packages, args.publish, args.live_preview)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if any(row['status']=='held' for row in result) else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ScheduleError, studio.GateError) as exc:
        raise SystemExit(f'Scheduler held this release: {exc}') from None
