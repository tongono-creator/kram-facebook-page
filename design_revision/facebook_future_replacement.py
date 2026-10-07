"""Future-only two-review image replacement. Default audit; never retry a write.

Uses the existing proven Page /photos scheduling form. The separate cancellation
action uses Meta's Post DELETE node and requires its own fresh Root signature.
This adapter is not deployed. Root must explicitly waive preservation of the ID.
"""
import argparse
import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import facebook_card_update as shared
import facebook_post_reschedule as timing
import studio_optional as gate

MARGIN = 60*60  # Root's local review margin; not an assertion about Meta's limits.
FIELDS = 'id,from{id},message,is_published,scheduled_publish_time,attachments{type,target,subattachments{type,target}}'


class Facebook(shared.Facebook):
    def edge(self, path, params):
        """Full pagination, cursor-only; never log or follow a token-bearing URL."""
        params = dict(params); seen = set(); values = []
        while True:
            body = self.request('GET', path, params=params)
            if not isinstance(body.get('data'), list):
                raise shared.UpdateError('incomplete_edge_readback')
            values.extend(body['data'])
            paging = body.get('paging', {})
            if not isinstance(paging, dict): raise shared.UpdateError('invalid_edge_paging')
            if not paging.get('next'): return values
            cursor = paging.get('cursors', {}).get('after')
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise shared.UpdateError('incomplete_or_repeated_edge_cursor')
            seen.add(cursor); params['after'] = cursor

    def queue(self, page_id):
        return self.edge(page_id+'/scheduled_posts', {'fields':FIELDS, 'limit':100})

    def no_comments(self, object_id):
        # Read every page plus total count. A missing count is a hold, not zero.
        params = {'fields':'id', 'filter':'stream', 'live_filter':'no_filter', 'summary':'true', 'limit':100}
        first = self.request('GET', object_id+'/comments', params=params)
        count = first.get('summary', {}).get('total_count')
        if type(count) is not int or count != 0 or not isinstance(first.get('data'), list) or first['data']:
            raise shared.UpdateError('comments_present_or_unavailable')
        paging = first.get('paging', {})
        if not isinstance(paging, dict): raise shared.UpdateError('comments_paging_unavailable')
        if paging.get('next'):
            # Even an empty first page is not proof that later pages are absent.
            if self.edge(object_id+'/comments', params):
                raise shared.UpdateError('comments_present_or_unavailable')
        return {'object_id':object_id, 'total_count':0, 'all_pages_read':True}

    def create(self, page_id, package, caption, timestamp):
        with (Path(package)/'card.png').open('rb') as photo:
            return self.request('POST', page_id+'/photos',
                data={'message':caption, 'published':'false', 'unpublished_content_type':'SCHEDULED',
                      'scheduled_publish_time':str(timestamp)}, files={'source':('card.png',photo,'image/png')})

    def cancel(self, post_id):
        try:
            return self.request('DELETE', post_id)
        except shared.UpdateError as error:
            # The shared client's ambiguous flag only covers POST. DELETE can
            # also have reached Meta before a timeout, 429, 5xx or bad response.
            if error.details.get('reason') in ('request_failed','non_json_response') or error.details.get('http_status',0)>=500 or error.details.get('http_status') in (408,409,429):
                error.ambiguous = True
            raise


def future_photo(post, page_id, now=None):
    timing.photo_post(post)
    snap = shared.snapshot(post, page_id)
    current = now or datetime.now(timezone.utc)
    if snap['is_published'] or not snap['schedule']['present'] or snap['schedule']['value'] < current.timestamp()+MARGIN:
        raise shared.UpdateError('only_unpublished_image_at_least_60minutes_ahead')
    return snap


def comments_absent(api, snap):
    return [api.no_comments(x) for x in [snap['post_id'], *snap['attachment_ids']]]


def local(root, relative, parent):
    path = (Path(root)/relative).resolve()
    if not path.is_relative_to((Path(root)/parent).resolve()) or not path.exists():
        raise shared.UpdateError('reviewed_path_missing_or_outside_directory')
    return path


def verify_plan(plan, key, channel, root, now=None, allow_elapsed=False):
    base = {'action','channel','page_id','page_name','old_post_id','before','reviewed_at',
            'root_id_change_exception_confirmed'}
    create = {'package_path','package_sha256','mobile_path','mobile_sha256','inventory_sha256',
              'archive_path','archive_sha256','root_history_retention_confirmed','root_old_not_promotional_confirmed',
              'monthly_plan_path','monthly_plan_sha256','root_monthly_plan_confirmed',
              'root_full_mobile_confirmed','root_optional_affiliate_policy_confirmed'}
    cancel = {'create_plan_sha256','new_post_id','new_before','receipt_sha256',
              'root_new_native_post_confirmed','root_mapping_policy_confirmed','root_cancel_old_acknowledged'}
    if set(plan) != {'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'), dict):
        raise shared.UpdateError('invalid_replacement_plan_schema')
    p = plan['payload']; action = p.get('action')
    if action not in ('create_future_image_replacement','cancel_replaced_old_image') or set(p) != base | (create if action.startswith('create') else cancel):
        raise shared.UpdateError('invalid_replacement_plan_schema')
    if (p['channel'] != key or channel.get('platform') != 'facebook' or p['page_id'] != str(channel['page_id']) or
        p['page_name'] != channel.get('page_name',channel.get('name')) or
        not re.fullmatch(re.escape(p['page_id'])+r'_[0-9]+',str(p['old_post_id']))):
        raise shared.UpdateError('replacement_page_identity_mismatch')
    current = now or datetime.now(timezone.utc); digest = shared.sha(shared.canonical(p))
    try:
        checked = gate.aware(p['reviewed_at'])
        if checked > current+timedelta(minutes=5) or (not allow_elapsed and current-checked > timedelta(minutes=30)): raise ValueError()
        if plan['payload_sha256'] != digest: raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True), digest.encode())
    except Exception: raise shared.UpdateError('invalid_or_stale_root_replacement_signature') from None
    booleans = ['root_id_change_exception_confirmed'] + ([x for x in create if x.startswith('root_')] if action.startswith('create') else [x for x in cancel if x.startswith('root_')])
    if any(p[x] is not True for x in booleans): raise shared.UpdateError('explicit_root_replacement_reviews_required')
    before = p['before']
    if not isinstance(before,dict) or before.get('post_id') != p['old_post_id'] or before.get('is_published') is not False:
        raise shared.UpdateError('exact_unpublished_old_snapshot_required')
    # Validate the complete shape by making a synthetic native node from the
    # signed snapshot; this does not certify that the live state still matches.
    if (set(before) != {'post_id','is_published','schedule','message_sha256','attachment_ids'} or
        not re.fullmatch(r'[0-9a-f]{64}',str(before.get('message_sha256'))) or
        not isinstance(before.get('schedule'),dict) or set(before['schedule']) != {'present','value'} or
        before['schedule']['present'] is not True or type(before['schedule']['value']) is not int or
        not isinstance(before.get('attachment_ids'),list) or len(before['attachment_ids']) != 1 or
        not isinstance(before['attachment_ids'][0],str) or not before['attachment_ids'][0].isdecimal()):
        raise shared.UpdateError('invalid_exact_old_snapshot')
    if not allow_elapsed and before['schedule']['value'] < current.timestamp()+MARGIN:
        raise shared.UpdateError('old_schedule_too_near_for_replacement')
    if action.startswith('create'):
        import facebook_surplus_cancel as history
        history.archive_check(p,root)
        monthly = local(root,p['monthly_plan_path'],'design_revision')
        if not monthly.is_file() or shared.sha(shared.canonical(shared.read(monthly)))!=p['monthly_plan_sha256']:
            raise shared.UpdateError('reviewed_monthly_plan_changed')
        inventory = shared.read(Path(root)/'design_revision/inventory.json')
        if shared.sha(shared.canonical(inventory)) != p['inventory_sha256'] or not any(x.get('post_id')==p['old_post_id'] and x.get('channel')==key and x.get('kind') in ('root_signed_native_release','existing_rocket_morning_card') for x in inventory):
            raise shared.UpdateError('reviewed_known_image_inventory_changed')
        package = local(root,p['package_path'],'design_revision/revisions')
        # Existing Rocket create scheduler is disabled. This explicit signed
        # correction path permits its confirmed Facebook identity only here.
        config = {**channel,'enabled':True,'channel_key':key,'require_signature':True}
        try:
            manifest = gate.verify_approval(package,config,current,allow_elapsed=allow_elapsed)
            if gate.digest_package(package) != p['package_sha256']: raise ValueError()
        except Exception: raise shared.UpdateError('corrected_package_missing_changed_or_unreviewed') from None
        mobile = local(root,p['mobile_path'],'design_revision/revisions')
        if not mobile.is_file() or shared.sha(mobile.read_bytes()) != p['mobile_sha256']:
            raise shared.UpdateError('corrected_mobile_changed')
        if manifest.get('affiliate_enabled') is not False:
            # Selected sales need a separate mapping + SubID + worker-policy
            # reservation adapter. Preserve the existing commercial gate.
            raise shared.UpdateError('commercial_replacement_mapping_adapter_not_verified')
        slot = int(gate.aware(manifest['scheduled_at']).timestamp())
        monthly_decision(p,root,slot)
        if not allow_elapsed and not current.timestamp()+MARGIN <= slot <= current.timestamp()+60*86400:
            raise shared.UpdateError('replacement_slot_outside_local_60minute_60day_window')
    else:
        if not re.fullmatch(re.escape(p['page_id'])+r'_[0-9]+',str(p['new_post_id'])) or p['new_post_id']==p['old_post_id']:
            raise shared.UpdateError('distinct_exact_new_post_id_required')
    return p,digest


def package_data(p, root):
    package = local(root,p['package_path'],'design_revision/revisions')
    if gate.digest_package(package) != p['package_sha256']:
        raise shared.UpdateError('corrected_package_changed_before_write')
    mobile = local(root,p['mobile_path'],'design_revision/revisions')
    if shared.sha(mobile.read_bytes())!=p['mobile_sha256']:
        raise shared.UpdateError('corrected_mobile_changed_before_write')
    monthly = local(root,p['monthly_plan_path'],'design_revision')
    if shared.sha(shared.canonical(shared.read(monthly)))!=p['monthly_plan_sha256']:
        raise shared.UpdateError('reviewed_monthly_plan_changed_before_write')
    caption = (package/'caption.txt').read_text(encoding='utf-8').strip()
    slot = int(gate.aware(shared.read(package/'manifest.json')['scheduled_at']).timestamp())
    monthly_decision(p,root,slot)
    return package,caption,slot


def monthly_decision(p,root,slot=None):
    monthly=shared.read(local(root,p['monthly_plan_path'],'design_revision'))
    if shared.sha(shared.canonical(monthly))!=p['monthly_plan_sha256']:
        raise shared.UpdateError('reviewed_monthly_plan_changed')
    operations=monthly.get('operations')
    if not isinstance(operations,list):raise shared.UpdateError('exact_monthly_operations_required')
    rows=[x for x in operations if isinstance(x,dict) and x.get('old_post_id')==p['old_post_id']]
    expected={'action':p['action'],'old_post_id':p['old_post_id'],'before_schedule':p['before']['schedule']['value']}
    if slot is not None:expected['after_schedule']=slot
    if rows!=[expected]:raise shared.UpdateError('exact_monthly_slot_decision_mismatch')


def old_check(api, p, now=None):
    snap = future_photo(api.post(p['old_post_id']),p['page_id'],now)
    if snap != p['before']: raise shared.UpdateError('live_old_snapshot_changed_no_write')
    photo=api.photo(snap['attachment_ids'][0])
    if str(photo.get('id'))!=snap['attachment_ids'][0] or str(photo.get('from',{}).get('id'))!=p['page_id']:
        raise shared.UpdateError('original_photo_owner_unverified')
    absent = comments_absent(api,snap)
    return snap,absent


def new_check(api, p, record):
    new_id = record.get('new_post_id'); photo_id = record.get('photo_id')
    if not new_id or not photo_id: raise shared.UpdateError('new_exact_ids_unknown_reconcile_required')
    after = future_photo(api.post(new_id),p['page_id'])
    expected = {'post_id':new_id,'is_published':False,'schedule':{'present':True,'value':record['slot']},
                'message_sha256':record['caption_sha256'],'attachment_ids':[photo_id]}
    if after != expected: raise shared.UpdateError('new_native_readback_mismatch')
    photo = api.photo(photo_id)
    if str(photo.get('id'))!=photo_id or str(photo.get('from',{}).get('id'))!=p['page_id']:
        raise shared.UpdateError('new_photo_owner_unverified')
    return after


def run(p,digest,channel,root,api,mode='audit',sync=None):
    if mode not in ('audit','apply','reconcile'): raise shared.UpdateError('invalid_mode')
    if mode=='apply' and sync is None: raise shared.UpdateError('durable_git_sync_required_for_replacement')
    if mode=='audit': return _run(p,digest,channel,root,api,mode,sync)
    with shared.lock(root): return _run(p,digest,channel,root,api,mode,sync)


def _run(p,digest,channel,root,api,mode,sync):
    root = Path(root).resolve(); shared.identity(api,channel)
    ledger_path = root/'design_revision/replacement_ledger.json'
    ledger = shared.read(ledger_path) if ledger_path.exists() else {}
    key = p['old_post_id']; record = ledger.get(key,{})
    creating = p['action']=='create_future_image_replacement'
    def save(state,**values):
        record.update(state=state,old_post_id=key,page_id=p['page_id'],updated_at=datetime.now(timezone.utc).isoformat(),**values)
        ledger[key]=record
        try:
            shared.atomic(ledger_path,ledger)
            if sync:
                paths=[ledger_path]
                if creating:
                    import facebook_surplus_cancel as history
                    archive_path,archive=history.archive_check(p,root)
                    paths.extend([archive_path,*[root/x['path'] for x in archive['assets']]])
                sync(root,paths)
        except Exception: raise shared.UpdateError('replacement_ledger_persistence_failed') from None
    if creating:
        if record and record.get('create_plan_sha256') != digest:
            raise shared.UpdateError('existing_replacement_plan_held')
        if record:
            if mode=='reconcile' and record.get('photo_id'):
                queue = api.queue(p['page_id'])
                matches = [x for x in queue if shared.attachment_ids(x.get('attachments',{}))==[record['photo_id']] and x.get('message','') and shared.sha(x['message'].encode())==record['caption_sha256'] and x.get('scheduled_publish_time')==record['slot']]
                if len(matches)==1:
                    candidate = {**record,'new_post_id':matches[0]['id']}
                    after = new_check(api,p,candidate)
                    receipt = {'create_plan_sha256':digest,'old_before':p['before'],'new_after':after}
                    save('new_verified',new_post_id=candidate['new_post_id'],receipt=receipt,receipt_sha256=shared.sha(shared.canonical(receipt)))
                    return {'status':'new_verified','new_post_id':candidate['new_post_id'],'external_writes_this_run':0}
            return {'status':'held_replacement_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
        if mode=='reconcile': return {'status':'held_no_replacement_reservation','external_writes_this_run':0}
        _,absent = old_check(api,p)
        import facebook_surplus_cancel as history
        history.archive_check(p,root)
        package,caption,slot = package_data(p,root)
        queue = api.queue(p['page_id'])
        if not any(x.get('id')==key for x in queue): raise shared.UpdateError('old_not_in_complete_native_queue')
        if any(x.get('id')!=key and x.get('scheduled_publish_time')==slot for x in queue): raise shared.UpdateError('replacement_slot_occupied')
        if any(x.get('page_id')==p['page_id'] and x.get('slot')==slot for x in ledger.values()): raise shared.UpdateError('replacement_slot_already_reserved')
        editorial_ledger=root/'design_revision/editorial_schedule_ledger.json'
        if editorial_ledger.exists() and any(x.get('page_id')==p['page_id'] and x.get('slot')==slot for x in shared.read(editorial_ledger).values()):
            raise shared.UpdateError('editorial_adapter_reserved_replacement_slot')
        if mode=='audit': return {'status':'verified_replacement_preview','old_post_id':key,'slot':slot,'external_writes_this_run':0}
        save('reserved_create',create_plan_sha256=digest,slot=slot,caption_sha256=shared.sha(caption.encode()),before=p['before'],old_no_comments=absent,package_sha256=p['package_sha256'],archive_path=p['archive_path'],archive_sha256=p['archive_sha256'])
        old_check(api,p); package,caption,slot = package_data(p,root)
        if slot < datetime.now(timezone.utc).timestamp()+MARGIN: raise shared.UpdateError('new_slot_elapsed_during_reservation')
        # Recheck the full queue after potentially slow durable push.
        if any(x.get('id')!=key and x.get('scheduled_publish_time')==slot for x in api.queue(p['page_id'])):
            raise shared.UpdateError('replacement_slot_changed_during_reservation')
        try:
            result=api.create(p['page_id'],package,caption,slot)
            photo_id=str(result.get('id',''));new_id=str(result.get('post_id',''))
            if not photo_id.isdecimal(): raise shared.UpdateError('new_photo_id_unavailable',ambiguous=True)
            if new_id and not re.fullmatch(re.escape(p['page_id'])+r'_[0-9]+',new_id): raise shared.UpdateError('new_post_id_unavailable',ambiguous=True)
        except shared.UpdateError as error:
            save('unknown_create' if error.ambiguous else 'failed_create',error=error.details);raise
        save('created_pending_readback',photo_id=photo_id,new_post_id=new_id or None)
        try:
            matches=[x for x in api.queue(p['page_id']) if shared.attachment_ids(x.get('attachments',{}))==[photo_id] and x.get('message')==caption and x.get('scheduled_publish_time')==slot]
            if len(matches)!=1 or (new_id and matches[0]['id']!=new_id): raise shared.UpdateError('new_native_queue_readback_unknown')
            candidate={**record,'new_post_id':matches[0]['id']};after=new_check(api,p,candidate)
            if after['post_id']==key: raise shared.UpdateError('new_post_id_equals_old')
            old_check(api,p)
        except shared.UpdateError as error:
            save('unknown_create',error=error.details);raise
        receipt={'create_plan_sha256':digest,'old_before':p['before'],'new_after':after}
        save('new_verified',new_post_id=after['post_id'],receipt=receipt,receipt_sha256=shared.sha(shared.canonical(receipt)))
        return {'status':'new_verified_old_untouched_second_review_required','old_post_id':key,'new_post_id':after['post_id'],'receipt_sha256':record['receipt_sha256'],'external_writes_this_run':1}
    # A cancellation plan is never accepted until new verification is durable.
    if (not record or record.get('create_plan_sha256')!=p['create_plan_sha256'] or record.get('new_post_id')!=p['new_post_id'] or
        record.get('receipt_sha256')!=p['receipt_sha256'] or shared.sha(shared.canonical(record.get('receipt'))) != p['receipt_sha256'] or
        record.get('receipt',{}).get('old_before')!=p['before'] or record.get('receipt',{}).get('new_after')!=p['new_before']):
        raise shared.UpdateError('second_review_does_not_bind_verified_new_receipt')
    if record.get('cancel_plan_sha256') and record['cancel_plan_sha256']!=digest:
        raise shared.UpdateError('existing_cancel_plan_held')
    import facebook_surplus_cancel as history
    history.archive_check({**p,'archive_path':record.get('archive_path'),'archive_sha256':record.get('archive_sha256')},root)
    after=new_check(api,p,record)
    queue=api.queue(p['page_id']);ids=[x.get('id') for x in queue]
    if p['new_post_id'] not in ids: raise shared.UpdateError('new_not_in_complete_native_queue')
    if mode=='reconcile':
        if record.get('state') in ('cancel_acknowledged','cancel_verified') and key not in ids:
            save('cancel_verified',new_after=after,old_absent_from_complete_queue=True)
            return {'status':'cancel_verified','external_writes_this_run':0,'new_post_id':p['new_post_id']}
        return {'status':'held_cancel_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
    if record.get('state')!='new_verified':
        return {'status':'held_cancel_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
    old_check(api,p)
    if key not in ids: raise shared.UpdateError('old_not_in_complete_native_queue')
    if mode=='audit': return {'status':'verified_cancel_preview','old_post_id':key,'new_post_id':p['new_post_id'],'external_writes_this_run':0}
    save('reserved_cancel',cancel_plan_sha256=digest)
    old_check(api,p);new_check(api,p,record)
    latest_ids=[x.get('id') for x in api.queue(p['page_id'])]
    if key not in latest_ids or p['new_post_id'] not in latest_ids:
        raise shared.UpdateError('old_or_new_queue_changed_during_cancel_reservation')
    try:
        ack=api.cancel(key)
        if ack.get('success') is not True: raise shared.UpdateError('cancel_acknowledgment_unavailable',ambiguous=True)
    except shared.UpdateError as error:
        save('unknown_cancel' if error.ambiguous else 'failed_cancel',error=error.details);raise
    save('cancel_acknowledged')
    try:
        after=new_check(api,p,record)
        ids=[x.get('id') for x in api.queue(p['page_id'])]
        if key in ids or p['new_post_id'] not in ids: raise shared.UpdateError('cancel_full_queue_readback_mismatch')
    except shared.UpdateError as error:
        save('cancel_acknowledged',error=error.details);raise
    save('cancel_verified',new_after=after,old_absent_from_complete_queue=True)
    return {'status':'cancel_verified','old_post_id':key,'new_post_id':p['new_post_id'],'external_writes_this_run':1}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--mode',choices=('audit','apply','reconcile'),default='audit')
    parser.add_argument('--git-state',action='store_true');args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=local(root,args.plan,'design_revision/plans')
        p,digest=verify_plan(shared.read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
        result=run(p,digest,channel,root,Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),args.mode,shared.git_sync if args.git_state else None)
        print(json.dumps(result,ensure_ascii=False))
    except shared.UpdateError as error: print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception: print(json.dumps({'status':'held','error':{'reason':'invalid_local_replacement_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
