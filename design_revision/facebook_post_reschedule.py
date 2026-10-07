"""Optional Root-signed schedule-only correction for known unpublished photo posts."""
import argparse
import base64
import json
import os
import re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import facebook_card_update as shared


def photo_post(post):
    attachments=post.get('attachments',{}).get('data',[])
    if len(attachments)!=1 or attachments[0].get('type')!='photo':
        raise shared.UpdateError('only_single_photo_posts_allowed_videos_never_touched')


def verify_plan(plan,key,channel,root,now=None,allow_elapsed=False):
    fields={'action','channel','page_id','page_name','post_id','reviewed_at','before',
            'after_schedule','inventory_sha256','root_monthly_plan_confirmed'}
    if set(plan)!={'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'),dict) or set(plan['payload'])!=fields:
        raise shared.UpdateError('invalid_reschedule_plan_schema')
    payload=plan['payload'];digest=shared.sha(shared.canonical(payload))
    if (payload['action']!='reschedule_unpublished_same_photo_post' or payload['channel']!=key or
        channel.get('platform')!='facebook' or payload['page_id']!=str(channel['page_id']) or
        payload['page_name']!=channel.get('page_name',channel.get('name'))):
        raise shared.UpdateError('reschedule_page_identity_mismatch')
    current=now or datetime.now(timezone.utc)
    try:
        checked=datetime.fromisoformat(payload['reviewed_at'])
        if checked.tzinfo is None or checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(minutes=30)):raise ValueError()
        if plan['payload_sha256']!=digest:raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True),digest.encode())
    except Exception:raise shared.UpdateError('invalid_or_stale_root_reschedule_signature') from None
    before=payload['before']
    if (not isinstance(before,dict) or set(before)!={'post_id','is_published','schedule','message_sha256','attachment_ids'} or
        before['post_id']!=payload['post_id'] or before['is_published'] is not False or
        not isinstance(before['schedule'],dict) or set(before['schedule'])!={'present','value'} or
        before['schedule']['present'] is not True or not isinstance(before['schedule']['value'],int) or
        isinstance(before['schedule']['value'],bool) or len(before.get('attachment_ids',[]))!=1 or
        not all(isinstance(x,str) and x.isdecimal() for x in before['attachment_ids']) or
        not isinstance(before['message_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',before['message_sha256'])):
        raise shared.UpdateError('exact_unpublished_scheduled_before_required')
    after=payload['after_schedule']
    if (not isinstance(after,dict) or set(after)!={'present','value'} or after['present'] is not True or
        not isinstance(after['value'],int) or isinstance(after['value'],bool) or after==before['schedule']):
        raise shared.UpdateError('different_explicit_after_schedule_required')
    if not allow_elapsed and not current.timestamp()+600<=after['value']<=current.timestamp()+60*86400:
        raise shared.UpdateError('after_schedule_outside_local_review_window_10min_to_60days')
    # This window is a local safety policy, not a claim about Meta's API maximum.
    inventory=Path(root)/'design_revision/inventory.json'
    if not inventory.exists() or shared.sha(shared.canonical(shared.read(inventory)))!=payload['inventory_sha256']:
        raise shared.UpdateError('reviewed_known_photo_inventory_changed')
    if not any(r.get('post_id')==payload['post_id'] and r.get('channel')==key and
               r.get('kind') in ['root_signed_native_release','existing_rocket_morning_card'] for r in shared.read(inventory)):
        raise shared.UpdateError('post_not_a_known_image_card_never_reschedule_video')
    if payload['root_monthly_plan_confirmed'] is not True:raise shared.UpdateError('root_monthly_quota_and_date_review_required')
    return payload,digest


def reschedule(payload,digest,channel,root,api,mode='audit',sync=None):
    if mode not in ['audit','apply','reconcile']:raise shared.UpdateError('invalid_mode')
    if mode=='audit':return _reschedule(payload,digest,channel,root,api,mode,sync)
    with shared.lock(root):return _reschedule(payload,digest,channel,root,api,mode,sync)


def _reschedule(payload,digest,channel,root,api,mode,sync):
    root=Path(root).resolve();shared.identity(api,channel)
    post=api.post(payload['post_id']);photo_post(post)
    current=shared.snapshot(post,payload['page_id'])
    if current['is_published']:raise shared.UpdateError('published_post_cannot_be_rescheduled')
    path=root/'design_revision/reschedule_ledger.json';ledger=shared.read(path) if path.exists() else {}
    record=ledger.get(payload['post_id'],{})
    if record and record.get('plan_sha256')!=digest:raise shared.UpdateError('existing_reschedule_plan_held')
    desired={**payload['before'],'schedule':payload['after_schedule']}
    def save(state,**values):
        record.update(state=state,plan_sha256=digest,post_id=payload['post_id'],updated_at=datetime.now(timezone.utc).isoformat(),**values)
        ledger[payload['post_id']]=record
        try:
            shared.atomic(path,ledger)
            if sync:sync(root,[path])
        except Exception:raise shared.UpdateError('reschedule_ledger_persistence_failed') from None
    if current==desired:
        if mode!='audit':save('verified_reconciled',after=current)
        return {'status':'verified_reconciled','post_id':payload['post_id'],'after_schedule':payload['after_schedule'],'external_writes_this_run':0}
    if mode=='reconcile' or record:
        return {'status':'held_reschedule_reconcile_required','post_id':payload['post_id'],'state':record.get('state'),'external_writes_this_run':0}
    if current!=payload['before']:raise shared.UpdateError('live_before_changed_schedule_only_write_refused')
    if mode=='audit':return {'status':'verified_reschedule_preview','post_id':payload['post_id'],'before':current,'after_schedule':payload['after_schedule'],'external_writes_this_run':0}
    if payload['after_schedule']['value']<datetime.now(timezone.utc).timestamp()+600:
        raise shared.UpdateError('after_schedule_now_too_near_or_elapsed')
    save('reserved')
    # Reservation Git sync may take time. Re-read publication/content/photo before POST.
    latest=api.post(payload['post_id']);photo_post(latest)
    if shared.snapshot(latest,payload['page_id'])!=payload['before']:
        raise shared.UpdateError('live_before_changed_after_reservation_no_write')
    if payload['after_schedule']['value']<datetime.now(timezone.utc).timestamp()+600:
        raise shared.UpdateError('after_schedule_elapsed_during_durable_reservation_no_write')
    try:
        response=api.request('POST',payload['post_id'],data={'scheduled_publish_time':str(payload['after_schedule']['value'])})
        if response.get('success') is not True:raise shared.UpdateError('reschedule_ack_unavailable',ambiguous=True)
    except shared.UpdateError as error:
        save('unknown' if error.ambiguous else 'failed',error=error.details);raise
    try:
        post=api.post(payload['post_id']);photo_post(post)
        after=shared.snapshot(post,payload['page_id'])
        if after!=desired:raise shared.UpdateError('schedule_content_or_photo_readback_mismatch')
    except shared.UpdateError as error:
        save('unknown',error=error.details);raise
    save('verified',after=after)
    return {'status':'verified','post_id':payload['post_id'],'after_schedule':payload['after_schedule'],'external_writes_this_run':1}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--mode',choices=['audit','apply','reconcile'],default='audit')
    parser.add_argument('--git-state',action='store_true');args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=(root/args.plan).resolve()
        if not path.is_relative_to((root/'design_revision/plans').resolve()):raise shared.UpdateError('plan_outside_reviewed_directory')
        payload,digest=verify_plan(shared.read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
        result=reschedule(payload,digest,channel,root,shared.Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),args.mode,shared.git_sync if args.git_state else None)
        print(json.dumps(result,ensure_ascii=False))
    except shared.UpdateError as error:print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception:print(json.dumps({'status':'held','error':{'reason':'invalid_local_reschedule_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
