"""Separate Root-signed cancellation of an intentionally empty future image slot.

Preserve the original caption/assets/native proof locally. No replacement is
required for an intentionally reduced calendar. No retries and no published,
video or comment-bearing posts. Not deployed; CLI defaults to read-only audit.
"""
import argparse
import base64
import json
import os
import re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import facebook_card_update as shared
import facebook_future_replacement as replacement
import studio_optional as gate


def archive_check(p,root):
    path=replacement.local(root,p['archive_path'],'design_revision/history')
    archive=shared.read(path)
    if shared.sha(shared.canonical(archive))!=p['archive_sha256']:
        raise shared.UpdateError('reviewed_original_archive_changed')
    fields={'old_before','old_message','page_id','old_photo_id','assets','native_proof','root_history_retention_confirmed'}
    if (not isinstance(archive,dict) or set(archive)!=fields or archive['old_before']!=p['before'] or
        archive['page_id']!=p['page_id'] or archive['old_photo_id']!=p['before']['attachment_ids'][0] or
        not isinstance(archive['old_message'],str) or shared.sha(archive['old_message'].encode())!=p['before']['message_sha256'] or
        archive['root_history_retention_confirmed'] is not True or not isinstance(archive['assets'],list) or not archive['assets'] or
        not isinstance(archive['native_proof'],dict) or not archive['native_proof']):
        raise shared.UpdateError('exact_original_caption_photo_assets_and_native_archive_required')
    if shared.snapshot(archive['native_proof'],p['page_id'])!=p['before'] or archive['native_proof'].get('message','')!=archive['old_message']:
        raise shared.UpdateError('original_native_archive_does_not_match_signed_before')
    for asset in archive['assets']:
        if not isinstance(asset,dict) or set(asset)!={'path','sha256'}:
            raise shared.UpdateError('invalid_original_archive_asset')
        original=replacement.local(root,asset['path'],'design_revision/history')
        if not original.is_file() or shared.sha(original.read_bytes())!=asset['sha256']:
            raise shared.UpdateError('original_archive_asset_missing_or_changed')
    return path,archive


def verify_plan(plan,key,channel,root,now=None,allow_elapsed=False):
    fields={'action','channel','page_id','page_name','old_post_id','before','reviewed_at','archive_path','archive_sha256',
            'monthly_plan_path','monthly_plan_sha256','root_monthly_empty_slot_confirmed','root_cancel_old_acknowledged',
            'root_mapping_policy_confirmed','root_history_retention_confirmed'}
    fields.add('root_old_not_promotional_confirmed')
    if set(plan)!={'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'),dict) or set(plan['payload'])!=fields:
        raise shared.UpdateError('invalid_surplus_cancel_plan_schema')
    p=plan['payload'];digest=shared.sha(shared.canonical(p));current=now or datetime.now(timezone.utc)
    if (p['action']!='cancel_surplus_future_image' or p['channel']!=key or channel.get('platform')!='facebook' or
        p['page_id']!=str(channel['page_id']) or p['page_name']!=channel.get('page_name',channel.get('name')) or
        not re.fullmatch(re.escape(p['page_id'])+r'_[0-9]+',str(p['old_post_id']))):
        raise shared.UpdateError('surplus_page_identity_mismatch')
    try:
        checked=gate.aware(p['reviewed_at'])
        if checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(minutes=30)):raise ValueError()
        if plan['payload_sha256']!=digest:raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True),digest.encode())
    except Exception:raise shared.UpdateError('invalid_or_stale_root_surplus_cancel_signature') from None
    if any(p[x] is not True for x in fields if x.startswith('root_')):
        raise shared.UpdateError('explicit_root_empty_slot_cancel_reviews_required')
    before=p['before']
    if (not isinstance(before,dict) or set(before)!={'post_id','is_published','schedule','message_sha256','attachment_ids'} or
        before['post_id']!=p['old_post_id'] or before['is_published'] is not False or
        not isinstance(before['schedule'],dict) or set(before['schedule'])!={'present','value'} or before['schedule']['present'] is not True or
        type(before['schedule']['value']) is not int or not re.fullmatch(r'[0-9a-f]{64}',str(before['message_sha256'])) or
        not isinstance(before['attachment_ids'],list) or len(before['attachment_ids'])!=1 or
        not isinstance(before['attachment_ids'][0],str) or not before['attachment_ids'][0].isdecimal()):
        raise shared.UpdateError('exact_unpublished_scheduled_image_required')
    if not allow_elapsed and before['schedule']['value']<current.timestamp()+replacement.MARGIN:
        raise shared.UpdateError('surplus_schedule_too_near_for_cancel')
    archive_check(p,root);monthly_check(p,root)
    return p,digest


def monthly_check(p,root):
    path=replacement.local(root,p['monthly_plan_path'],'design_revision')
    if not path.is_file() or shared.sha(shared.canonical(shared.read(path)))!=p['monthly_plan_sha256']:
        raise shared.UpdateError('reviewed_monthly_empty_slot_plan_changed')
    replacement.monthly_decision(p,root)


def run(p,digest,channel,root,api,mode='audit',sync=None):
    if mode not in ('audit','apply','reconcile'):raise shared.UpdateError('invalid_mode')
    if mode=='apply' and sync is None:raise shared.UpdateError('durable_git_sync_required_for_cancel')
    if mode=='audit':return _run(p,digest,channel,root,api,mode,sync)
    with shared.lock(root):return _run(p,digest,channel,root,api,mode,sync)


def _run(p,digest,channel,root,api,mode,sync):
    root=Path(root).resolve();shared.identity(api,channel)
    archive_path,_=archive_check(p,root);monthly_check(p,root)
    ledger_path=root/'design_revision/surplus_cancel_ledger.json';ledger=shared.read(ledger_path) if ledger_path.exists() else {}
    key=p['old_post_id'];record=ledger.get(key,{})
    if record and record.get('plan_sha256')!=digest:raise shared.UpdateError('existing_surplus_cancel_plan_held')
    def save(state,**values):
        record.update(state=state,plan_sha256=digest,post_id=key,page_id=p['page_id'],archive_sha256=p['archive_sha256'],
                      updated_at=datetime.now(timezone.utc).isoformat(),**values);ledger[key]=record
        try:
            shared.atomic(ledger_path,ledger)
            if sync:
                # Archive and all its source assets must reach shared history
                # before cancellation. This remains true after a fresh clone.
                _,archive=archive_check(p,root)
                sync(root,[ledger_path,archive_path,*[root/x['path'] for x in archive['assets']]])
        except Exception:raise shared.UpdateError('surplus_archive_or_ledger_persistence_failed') from None
    queue=api.queue(p['page_id']);ids=[x.get('id') for x in queue]
    if mode=='reconcile':
        if record.get('state') in ('cancel_acknowledged','cancel_verified') and key not in ids:
            save('cancel_verified',old_absent_from_complete_queue=True)
            return {'status':'cancel_verified','post_id':key,'external_writes_this_run':0}
        return {'status':'held_surplus_cancel_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
    if record:return {'status':'held_surplus_cancel_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
    if key not in ids:raise shared.UpdateError('surplus_old_not_in_complete_native_queue')
    _,absent=replacement.old_check(api,p)
    if mode=='audit':return {'status':'verified_surplus_cancel_preview','post_id':key,'external_writes_this_run':0}
    save('reserved_cancel',before=p['before'],old_no_comments=absent)
    archive_check(p,root);monthly_check(p,root);replacement.old_check(api,p)
    if key not in [x.get('id') for x in api.queue(p['page_id'])]:
        raise shared.UpdateError('surplus_old_changed_during_reservation')
    try:
        result=api.cancel(key)
        if result.get('success') is not True:raise shared.UpdateError('cancel_acknowledgment_unavailable',ambiguous=True)
    except shared.UpdateError as error:
        save('unknown_cancel' if error.ambiguous else 'failed_cancel',error=error.details);raise
    save('cancel_acknowledged')
    try:
        if key in [x.get('id') for x in api.queue(p['page_id'])]:raise shared.UpdateError('surplus_full_queue_readback_mismatch')
    except shared.UpdateError as error:save('cancel_acknowledged',error=error.details);raise
    save('cancel_verified',old_absent_from_complete_queue=True)
    return {'status':'cancel_verified','post_id':key,'external_writes_this_run':1}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--mode',choices=('audit','apply','reconcile'),default='audit')
    parser.add_argument('--git-state',action='store_true');args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=replacement.local(root,args.plan,'design_revision/plans')
        p,digest=verify_plan(shared.read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
        result=run(p,digest,channel,root,replacement.Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),args.mode,shared.git_sync if args.git_state else None)
        print(json.dumps(result,ensure_ascii=False))
    except shared.UpdateError as error:print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception:print(json.dumps({'status':'held','error':{'reason':'invalid_local_surplus_cancel_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
