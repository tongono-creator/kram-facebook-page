"""Root-signed same-post card corrections; audit/reconcile are GET-only."""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from cryptography.hazmat.primitives.serialization import load_pem_public_key


class UpdateError(Exception):
    def __init__(self, reason, status=None, code=None, ambiguous=False, photo_id=None):
        self.details = {'reason': reason}
        if isinstance(status, int): self.details['http_status'] = status
        if isinstance(code, int): self.details['api_error_code'] = code
        if photo_id and str(photo_id).isdecimal(): self.details['unpersisted_photo_id'] = str(photo_id)
        self.ambiguous = ambiguous
        super().__init__(reason)


def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
def sha(value): return hashlib.sha256(value).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name+'.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def attachment_ids(value):
    result = set()
    def walk(item):
        if isinstance(item, dict):
            if isinstance(item.get('target'), dict) and str(item['target'].get('id','')).isdecimal():
                result.add(str(item['target']['id']))
            for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
    walk(value); return sorted(result)


def snapshot(post, page_id):
    if (not str(post.get('id','')).startswith(page_id+'_') or
        str(post.get('from',{}).get('id')) != page_id or not isinstance(post.get('is_published'),bool)):
        raise UpdateError('post_identity_or_publication_state_unavailable')
    if not isinstance(post.get('message',''),str): raise UpdateError('caption_unavailable')
    present = 'scheduled_publish_time' in post
    slot = post.get('scheduled_publish_time')
    if present and (not isinstance(slot,int) or isinstance(slot,bool)): raise UpdateError('invalid_live_schedule')
    ids = attachment_ids(post.get('attachments',{}))
    if len(ids)!=1: raise UpdateError('single_exact_photo_target_required')
    return {'post_id':post['id'], 'is_published':post['is_published'],
            'schedule':{'present':present,'value':slot if present else None},
            'message_sha256':sha(post.get('message','').encode()), 'attachment_ids':ids}


class Facebook:
    def __init__(self, token, session=None):
        if not isinstance(token,str) or not token: raise UpdateError('missing_page_access_token')
        self.session = session or requests.Session()
        self.session.headers['Authorization'] = 'Bearer '+token

    def request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, 'https://graph.facebook.com/v25.0/'+path,
                                            timeout=(10,60), **kwargs)
        except requests.RequestException:
            raise UpdateError('request_failed', ambiguous=method=='POST') from None
        try: body = response.json()
        except ValueError: raise UpdateError('non_json_response', response.status_code, ambiguous=method=='POST') from None
        error = body.get('error',{}) if isinstance(body,dict) else {}
        if not isinstance(body,dict) or not response.ok or error:
            raise UpdateError('graph_request_rejected',response.status_code,error.get('code'),
                              ambiguous=method=='POST' and (response.status_code>=500 or response.status_code==429))
        return body

    def identity(self): return self.request('GET','me',params={'fields':'id,name'})
    def post(self, post_id):
        return self.request('GET',post_id,params={'fields':'id,from{id},message,is_published,scheduled_publish_time,attachments{type,target,subattachments{type,target}}'})
    def photo(self, photo_id): return self.request('GET',photo_id,params={'fields':'id,from{id}'})
    def upload(self, page_id, path):
        with Path(path).open('rb') as handle:
            return self.request('POST',page_id+'/photos',data={'published':'false'},
                                files={'source':('card.png',handle,'image/png')})
    def replace(self, post_id, photo_id, message):
        # Meta SDK Post.api_update defines attached_media and message. No publish/time/delete fields.
        return self.request('POST',post_id,data={'message':message,
                            'attached_media':json.dumps([{'media_fbid':photo_id}])})


def identity(api, channel):
    value = api.identity()
    if str(value.get('id'))!=str(channel['page_id']) or value.get('name')!=channel.get('page_name',channel.get('name')):
        raise UpdateError('exact_page_identity_mismatch')


def verify_plan(plan, channel_key, channel, root, now=None, allow_elapsed=False):
    fields = {'action','channel','page_id','page_name','post_id','reviewed_at','before','card_path','card_sha256',
              'mobile_path','mobile_sha256','message_after','caption_disclosure_confirmed','root_visual_confirmed'}
    if set(plan)!= {'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'),dict) or set(plan['payload'])!=fields:
        raise UpdateError('invalid_plan_schema')
    payload = plan['payload']; digest = sha(canonical(payload))
    if (payload['action']!='replace_same_post_card' or payload['channel']!=channel_key or channel.get('platform')!='facebook'
        or payload['page_id']!=str(channel['page_id']) or payload['page_name']!=channel.get('page_name',channel.get('name'))
        or not re.fullmatch(re.escape(payload['page_id'])+r'_[0-9]+',str(payload['post_id']))):
        raise UpdateError('signed_page_identity_mismatch')
    try:
        checked = datetime.fromisoformat(payload['reviewed_at'])
        if checked.tzinfo is None: raise ValueError()
        current = now or datetime.now(timezone.utc)
        if checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(minutes=30)): raise ValueError()
        if plan['payload_sha256']!=digest: raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True),digest.encode())
    except Exception: raise UpdateError('invalid_or_stale_root_signature') from None
    if payload['caption_disclosure_confirmed'] is not True or payload['root_visual_confirmed'] is not True:
        raise UpdateError('root_caption_and_full_mobile_review_required')
    message = payload['message_after']
    if not isinstance(message,str) or not message.strip() or not re.search(r'\bAI\b|ปัญญาประดิษฐ์',message,re.I):
        raise UpdateError('caption_must_retain_ai_explanation')
    before = payload['before']
    if (not isinstance(before,dict) or set(before)!={'post_id','is_published','schedule','message_sha256','attachment_ids'}
        or before['post_id']!=payload['post_id'] or not isinstance(before['is_published'],bool)
        or not re.fullmatch(r'[0-9a-f]{64}',str(before['message_sha256']))
        or not isinstance(before['attachment_ids'],list) or len(before['attachment_ids'])!=1
        or any(not isinstance(x,str) or not x.isdecimal() for x in before['attachment_ids'])
        or not isinstance(before['schedule'],dict) or set(before['schedule'])!={'present','value'}
        or not isinstance(before['schedule']['present'],bool)
        or (before['schedule']['present'] and (not isinstance(before['schedule']['value'],int) or isinstance(before['schedule']['value'],bool)))
        or (not before['schedule']['present'] and before['schedule']['value'] is not None)):
        raise UpdateError('invalid_exact_before_snapshot')
    for kind in ['card','mobile']:
        path = (Path(root)/payload[kind+'_path']).resolve()
        if (not path.is_relative_to((Path(root)/'design_revision/revisions').resolve()) or not path.is_file()
            or sha(path.read_bytes())!=payload[kind+'_sha256']): raise UpdateError('corrected_asset_missing_or_changed')
    return payload, digest


@contextmanager
def lock(root):
    path = Path(root)/'design_revision/mutation.lock'; path.parent.mkdir(parents=True,exist_ok=True)
    try: fd = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError: raise UpdateError('mutation_locked_inspect_prior_run') from None
    try:
        os.write(fd,b'Root same-post correction\n'); os.fsync(fd); os.close(fd); yield
    finally: path.unlink(missing_ok=True)


def git_sync(root, paths):
    def git(*args, allow=False):
        result = subprocess.run(['git',*args],cwd=root,capture_output=True,text=True)
        if result.returncode and not allow: raise UpdateError('durable_git_state_failed')
        return result
    names = [Path(p).relative_to(root).as_posix() for p in paths]
    if any(x not in names for x in git('diff','--cached','--name-only').stdout.splitlines()):
        raise UpdateError('unrelated_staged_files')
    git('add','--',*names)
    if git('diff','--cached','--quiet',allow=True).returncode: git('commit','-m','Record Root same-post media correction state','--',*names)
    for _ in range(3):
        if not git('push','origin','HEAD:refs/heads/main',allow=True).returncode: return
        git('fetch','origin','main'); git('rebase','origin/main')
    raise UpdateError('durable_git_state_push_failed')


def verify_repository(root, channel):
    result = subprocess.run(['git','remote','get-url','origin'],cwd=root,capture_output=True,text=True)
    slug = channel.get('repository_slug','')
    if result.returncode or not slug or not any(result.stdout.strip().removesuffix('.git')==prefix+slug
                                              for prefix in ['https://github.com/','git@github.com:']):
        raise UpdateError('repository_identity_mismatch')


def correct(payload, digest, channel, root, api, mode='audit', sync=None):
    if mode not in ['audit','apply','reconcile']: raise UpdateError('invalid_mode')
    if mode=='audit': return _correct(payload,digest,channel,root,api,mode,sync)
    with lock(root): return _correct(payload,digest,channel,root,api,mode,sync)


def _correct(payload, digest, channel, root, api, mode, sync):
    root = Path(root).resolve(); identity(api,channel)
    post = api.post(payload['post_id']); current = snapshot(post,payload['page_id'])
    path = root/'design_revision/ledger.json'; ledger = read(path) if path.exists() else {}
    record = ledger.get(payload['post_id'],{})
    if record and record.get('plan_sha256')!=digest: raise UpdateError('existing_plan_held_no_automatic_replacement')
    def save(state, **values):
        record.update(state=state,plan_sha256=digest,post_id=payload['post_id'],updated_at=datetime.now(timezone.utc).isoformat(),**values)
        ledger[payload['post_id']] = record
        try:
            atomic(path,ledger)
            if sync: sync(root,[path])
        except Exception: raise UpdateError('ledger_persistence_failed',photo_id=record.get('photo_id')) from None
    photo_id = record.get('photo_id')
    desired = {**payload['before'],'message_sha256':sha(payload['message_after'].encode()),'attachment_ids':[photo_id]}
    if photo_id and current==desired:
        if mode!='audit': save('verified_reconciled')
        return {'status':'verified_reconciled','post_id':payload['post_id'],'photo_id':photo_id,'external_writes_this_run':0}
    if mode=='reconcile' or record.get('state') in ['reserved_upload','reserved_update','unknown_upload','unknown_update','failed_upload','failed_update','verified','verified_reconciled']:
        return {'status':'held_reconcile_required','post_id':payload['post_id'],'state':record.get('state'),'external_writes_this_run':0}
    if current!=payload['before']: raise UpdateError('live_before_changed_no_write')
    if re.search(r'สมมติ|fiction',post.get('message',''),re.I) and not re.search(r'สมมติ|fiction',payload['message_after'],re.I):
        raise UpdateError('fiction_explanation_removed')
    if mode=='audit': return {'status':'verified_correction_preview','post_id':payload['post_id'],'before':current,'external_writes_this_run':0}
    writes = 0
    if not photo_id:
        save('reserved_upload')
        for kind in ['card','mobile']:
            if sha((root/payload[kind+'_path']).read_bytes())!=payload[kind+'_sha256']:
                raise UpdateError('corrected_asset_changed_after_durable_reservation')
        try:
            response = api.upload(payload['page_id'],root/payload['card_path']); writes+=1
            photo_id = str(response.get('id',''))
            if not photo_id.isdecimal(): raise UpdateError('upload_id_unavailable',ambiguous=True)
        except UpdateError as error:
            save('unknown_upload' if error.ambiguous else 'failed_upload',error=error.details); raise
        save('uploaded',photo_id=photo_id)
    photo = api.photo(photo_id)
    if str(photo.get('id'))!=photo_id or str(photo.get('from',{}).get('id'))!=payload['page_id']:
        raise UpdateError('uploaded_photo_owner_unverified_no_post_update')
    # Re-read immediately before same-ID mutation; never overwrite edits made during upload.
    if snapshot(api.post(payload['post_id']),payload['page_id'])!=payload['before']:
        raise UpdateError('live_before_changed_after_upload_no_post_update')
    save('reserved_update')
    try:
        response = api.replace(payload['post_id'],photo_id,payload['message_after']); writes+=1
        if response.get('success') is not True: raise UpdateError('update_acknowledgment_unavailable',ambiguous=True)
    except UpdateError as error:
        save('unknown_update' if error.ambiguous else 'failed_update',error=error.details); raise
    try:
        after = snapshot(api.post(payload['post_id']),payload['page_id'])
        expected = {**payload['before'],'message_sha256':sha(payload['message_after'].encode()),'attachment_ids':[photo_id]}
        if after!=expected: raise UpdateError('same_post_attachment_caption_or_schedule_readback_mismatch')
    except UpdateError as error:
        save('unknown_update',error=error.details); raise
    save('verified',after=after)
    return {'status':'verified','post_id':payload['post_id'],'photo_id':photo_id,'external_writes_this_run':writes}


def audit_inventory(api, channel, inventory):
    identity(api,channel); records=[]
    for known in inventory:
        try:
            post = api.post(known['post_id']); snap = snapshot(post,str(channel['page_id']))
            records.append({**known,'status':'audited','live':snap,'message':post.get('message',''),
                'expected_caption_matches':snap['message_sha256']==known.get('caption_sha256')})
        except UpdateError as error: records.append({**known,'status':'held','error':error.details})
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'page_id':channel['page_id'],
            'page_name':channel.get('page_name',channel.get('name')),'records':records,'external_writes':0}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--mode',choices=['audit','apply','reconcile'],default='audit')
    parser.add_argument('--plan',type=Path);parser.add_argument('--git-state',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    try:
        channel=read(root/'design_revision/channels.json')[args.channel]
        verify_repository(root,channel)
        api=Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN')))
        if args.plan:
            path=(root/args.plan).resolve()
            if not path.is_relative_to((root/'design_revision/plans').resolve()): raise UpdateError('plan_path_outside_reviewed_directory')
            payload,digest=verify_plan(read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
            result=correct(payload,digest,channel,root,api,args.mode,git_sync if args.git_state else None)
        else:
            if args.mode!='audit': raise UpdateError('signed_plan_required')
            inventory=[r for r in read(root/'design_revision/inventory.json') if r['channel']==args.channel]
            result=audit_inventory(api,channel,inventory)
        print(json.dumps(result,ensure_ascii=False))
    except UpdateError as error: print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception: print(json.dumps({'status':'held','error':{'reason':'invalid_local_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
