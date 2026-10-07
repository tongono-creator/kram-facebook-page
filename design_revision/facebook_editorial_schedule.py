"""Root-signed new editorial IMAGE slots. No original post or fabricated ID.

Shares optional package gate and the accepted native Page photo scheduling form.
This adapter is isolated and not deployed. Default audit is read-only.
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
import facebook_future_replacement as images
import studio_optional as gate


def package_check(p,key,channel,root,now=None,allow_elapsed=False):
    package=images.local(root,p['package_path'],'design_revision/revisions')
    config={**channel,'enabled':True,'channel_key':key,'require_signature':True}
    try:
        manifest=gate.verify_approval(package,config,now,allow_elapsed=allow_elapsed)
        if gate.digest_package(package)!=p['package_sha256']:raise ValueError()
    except Exception:raise shared.UpdateError('new_editorial_package_changed_or_unreviewed') from None
    if manifest.get('affiliate_enabled') is not False:
        raise shared.UpdateError('new_image_adapter_requires_explicit_editorial_optout')
    if manifest['id']!=p['package_id']:raise shared.UpdateError('new_editorial_package_identity_mismatch')
    mobile=images.local(root,p['mobile_path'],'design_revision/revisions')
    if not mobile.is_file() or shared.sha(mobile.read_bytes())!=p['mobile_sha256']:
        raise shared.UpdateError('new_editorial_mobile_changed')
    slot=int(gate.aware(manifest['scheduled_at']).timestamp())
    monthly=shared.read(images.local(root,p['monthly_plan_path'],'design_revision'))
    if shared.sha(shared.canonical(monthly))!=p['monthly_plan_sha256'] or not isinstance(monthly.get('operations'),list):
        raise shared.UpdateError('new_editorial_monthly_plan_changed')
    rows=[x for x in monthly['operations'] if isinstance(x,dict) and x.get('package_id')==p['package_id']]
    if rows!=[{'action':'schedule_new_editorial_image','package_id':p['package_id'],'after_schedule':slot}]:
        raise shared.UpdateError('new_editorial_exact_monthly_slot_decision_mismatch')
    current=now or datetime.now(timezone.utc)
    if not allow_elapsed and not current.timestamp()+images.MARGIN<=slot<=current.timestamp()+60*86400:
        raise shared.UpdateError('new_editorial_slot_outside_local_60minute_60day_window')
    caption=(package/'caption.txt').read_text(encoding='utf-8').strip()
    return package,caption,slot


def verify_plan(plan,key,channel,root,now=None,allow_elapsed=False):
    fields={'action','channel','page_id','page_name','package_id','reviewed_at','package_path','package_sha256',
            'mobile_path','mobile_sha256','monthly_plan_path','monthly_plan_sha256','root_full_mobile_confirmed',
            'root_monthly_plan_confirmed','root_new_slot_confirmed','root_optional_affiliate_policy_confirmed'}
    if set(plan)!={'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'),dict) or set(plan['payload'])!=fields:
        raise shared.UpdateError('invalid_new_editorial_plan_schema')
    p=plan['payload'];digest=shared.sha(shared.canonical(p));current=now or datetime.now(timezone.utc)
    if (p['action']!='schedule_new_editorial_image' or p['channel']!=key or channel.get('platform')!='facebook' or
        p['page_id']!=str(channel['page_id']) or p['page_name']!=channel.get('page_name',channel.get('name')) or
        not isinstance(p['package_id'],str) or not p['package_id'].strip()):
        raise shared.UpdateError('new_editorial_identity_mismatch')
    try:
        checked=gate.aware(p['reviewed_at'])
        if checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(minutes=30)):raise ValueError()
        if plan['payload_sha256']!=digest:raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True),digest.encode())
    except Exception:raise shared.UpdateError('invalid_or_stale_root_new_editorial_signature') from None
    if any(p[x] is not True for x in fields if x.startswith('root_')):
        raise shared.UpdateError('explicit_root_new_editorial_reviews_required')
    package_check(p,key,channel,root,current,allow_elapsed)
    return p,digest


def run(p,digest,channel,root,api,mode='audit',sync=None):
    if mode not in ('audit','apply','reconcile'):raise shared.UpdateError('invalid_mode')
    if mode=='apply' and sync is None:raise shared.UpdateError('durable_git_sync_required_for_new_image')
    if mode=='audit':return _run(p,digest,channel,root,api,mode,sync)
    with shared.lock(root):return _run(p,digest,channel,root,api,mode,sync)


def _run(p,digest,channel,root,api,mode,sync):
    root=Path(root).resolve();shared.identity(api,channel)
    path=root/'design_revision/editorial_schedule_ledger.json';ledger=shared.read(path) if path.exists() else {}
    key=p['package_id'];record=ledger.get(key,{})
    if record and record.get('plan_sha256')!=digest:raise shared.UpdateError('existing_editorial_schedule_plan_held')
    def save(state,**values):
        record.update(state=state,package_id=key,page_id=p['page_id'],plan_sha256=digest,updated_at=datetime.now(timezone.utc).isoformat(),**values)
        ledger[key]=record
        try:
            shared.atomic(path,ledger)
            if sync:sync(root,[path])
        except Exception:raise shared.UpdateError('new_image_ledger_persistence_failed') from None
    if record:
        if mode=='reconcile' and record.get('photo_id'):
            matches=[x for x in api.queue(p['page_id']) if shared.attachment_ids(x.get('attachments',{}))==[record['photo_id']] and
                     shared.sha(x.get('message','').encode())==record['caption_sha256'] and x.get('scheduled_publish_time')==record['slot']]
            if len(matches)==1:
                candidate={**record,'new_post_id':matches[0]['id']}
                after=images.new_check(api,p,candidate)
                save('verified',new_post_id=after['post_id'],after=after)
                return {'status':'verified','post_id':after['post_id'],'external_writes_this_run':0}
        return {'status':'held_editorial_schedule_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
    if mode=='reconcile':return {'status':'held_no_editorial_schedule_reservation','external_writes_this_run':0}
    package,caption,slot=package_check(p,p['channel'],channel,root,allow_elapsed=mode!='apply')
    queue=api.queue(p['page_id'])
    if any(x.get('scheduled_publish_time')==slot for x in queue):raise shared.UpdateError('new_editorial_slot_occupied')
    if any(x.get('page_id')==p['page_id'] and x.get('slot')==slot for x in ledger.values()):
        raise shared.UpdateError('new_editorial_slot_already_reserved')
    # Also hold a cross-adapter reservation that has not yet appeared in Meta.
    replacement_ledger=root/'design_revision/replacement_ledger.json'
    if replacement_ledger.exists() and any(x.get('page_id')==p['page_id'] and x.get('slot')==slot for x in shared.read(replacement_ledger).values()):
        raise shared.UpdateError('replacement_adapter_reserved_new_editorial_slot')
    commercial_ledger=root/'design_revision/commercial_schedule_ledger.json'
    if commercial_ledger.exists() and any(x.get('page_id')==p['page_id'] and x.get('slot')==slot for x in shared.read(commercial_ledger).values()):
        raise shared.UpdateError('commercial_adapter_reserved_new_editorial_slot')
    if mode=='audit':return {'status':'verified_new_editorial_preview','package_id':key,'slot':slot,'external_writes_this_run':0}
    save('reserved_create',slot=slot,caption_sha256=shared.sha(caption.encode()),package_sha256=p['package_sha256'])
    package,caption,slot=package_check(p,p['channel'],channel,root)
    if any(x.get('scheduled_publish_time')==slot for x in api.queue(p['page_id'])):
        raise shared.UpdateError('new_editorial_slot_changed_during_reservation')
    try:
        response=api.create(p['page_id'],package,caption,slot)
        photo_id=str(response.get('id',''));new_id=str(response.get('post_id',''))
        if not photo_id.isdecimal():raise shared.UpdateError('new_image_photo_id_unavailable',ambiguous=True)
        if new_id and not re.fullmatch(re.escape(p['page_id'])+r'_[0-9]+',new_id):
            raise shared.UpdateError('new_image_post_id_unavailable',ambiguous=True)
    except shared.UpdateError as error:
        save('unknown_create' if error.ambiguous else 'failed_create',error=error.details);raise
    save('created_pending_readback',photo_id=photo_id,new_post_id=new_id or None)
    try:
        matches=[x for x in api.queue(p['page_id']) if shared.attachment_ids(x.get('attachments',{}))==[photo_id] and
                 x.get('message')==caption and x.get('scheduled_publish_time')==slot]
        if len(matches)!=1 or (new_id and new_id!=matches[0]['id']):raise shared.UpdateError('new_image_native_queue_readback_unknown')
        candidate={**record,'new_post_id':matches[0]['id']};after=images.new_check(api,p,candidate)
    except shared.UpdateError as error:save('unknown_create',error=error.details);raise
    save('verified',new_post_id=after['post_id'],after=after)
    return {'status':'verified','package_id':key,'post_id':after['post_id'],'photo_id':photo_id,'external_writes_this_run':1}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--mode',choices=('audit','apply','reconcile'),default='audit')
    parser.add_argument('--git-state',action='store_true');args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=images.local(root,args.plan,'design_revision/plans')
        p,digest=verify_plan(shared.read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
        result=run(p,digest,channel,root,images.Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),args.mode,shared.git_sync if args.git_state else None)
        print(json.dumps(result,ensure_ascii=False))
    except shared.UpdateError as error:print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception:print(json.dumps({'status':'held','error':{'reason':'invalid_local_new_image_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
