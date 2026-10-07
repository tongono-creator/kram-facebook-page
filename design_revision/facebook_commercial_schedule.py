"""Isolated NEW actual-product-photo scheduler and sole-worker mapping gate.

No product discovery, signing, comment writer, deployment or old-post mutation.
Pre-create reservation binds canonical SKU, date-specific SubIDs and approved
comment. Actual new aliases can only be added after Meta returns real IDs.
"""
import argparse
import base64
import copy
import json
import os
import re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import facebook_card_update as shared
import facebook_future_replacement as images
import studio_optional as gate
import affiliate_post_policy as policy


def config_files(root):
    worker_path=Path(root)/'auto_affiliate_config.json';mapping_path=Path(root)/'affiliate_post_products.json'
    worker=shared.read(worker_path);mapping=shared.read(mapping_path)
    cfg=worker.get('facebook')
    if not isinstance(cfg,dict) or not isinstance(mapping.get('facebook'),dict):raise shared.UpdateError('existing_single_worker_config_and_registry_required')
    registry_name=cfg.get('post_products_file')
    if not isinstance(registry_name,str) or (worker_path.parent/registry_name).resolve()!=mapping_path.resolve() or not isinstance(cfg.get('post_products',{}),dict):
        raise shared.UpdateError('existing_worker_must_load_exact_reviewed_registry')
    return worker_path,mapping_path,worker,mapping,cfg


def package_check(p,key,channel,root,now=None,allow_elapsed=False):
    current=now or datetime.now(timezone.utc);package=images.local(root,p['package_path'],'design_revision/revisions')
    try:
        manifest=gate.verify_approval(package,{**channel,'enabled':True,'channel_key':key,'require_signature':True},current,allow_elapsed)
        if gate.digest_package(package)!=p['package_sha256']:raise ValueError()
    except Exception:raise shared.UpdateError('commercial_package_changed_unreviewed_or_product_gate_failed') from None
    if manifest.get('affiliate_enabled') is not True or manifest.get('visual_type')!='actual_product_photo' or manifest['id']!=p['package_id']:
        raise shared.UpdateError('explicit_new_actual_product_photo_and_monetization_required')
    affiliate=shared.read(package/'affiliate.json');sku=str(affiliate.get('shop_id',''))+'/'+str(affiliate.get('product_id',''))
    if not re.fullmatch(r'[0-9]+/[0-9]+',sku) or sku!=p['canonical_sku']:raise shared.UpdateError('verified_canonical_shop_item_required')
    if key=='rocket_fb' and affiliate.get('category') in ('books','book'):raise shared.UpdateError('rocket_book_experiment_excluded')
    slot=int(gate.aware(manifest['scheduled_at']).timestamp());local=gate.aware(manifest['scheduled_at']).astimezone(timezone(timedelta(minutes=420)))
    subids=affiliate.get('subids')
    if not isinstance(subids,list) or len(subids)!=5 or any(not isinstance(x,str) or not x.strip() for x in subids) or subids[1]!=local.strftime('%Y%m%d'):
        raise shared.UpdateError('five_verified_date_bound_shopee_subids_required')
    if not isinstance(affiliate.get('variants'),list):raise shared.UpdateError('actual_selected_variant_list_required')
    destination=affiliate.get('destination_url','');parsed=urlparse(destination)
    if parsed.scheme!='https' or (parsed.hostname or '').lower() not in ('shopee.co.th','shopee.com') or parsed.path.rstrip('/')!='/product/'+sku:
        raise shared.UpdateError('exact_canonical_shopee_destination_required')
    mobile=images.local(root,p['mobile_path'],'design_revision/revisions');photo=images.local(root,p['actual_product_photo_path'],'design_revision/revisions')
    if not mobile.is_file() or shared.sha(mobile.read_bytes())!=p['mobile_sha256'] or not photo.is_file() or shared.sha(photo.read_bytes())!=p['actual_product_photo_sha256']:
        raise shared.UpdateError('actual_product_source_or_mobile_missing_changed')
    proof=shared.read(images.local(root,p['tracking_variant_proof_path'],'design_revision/revisions'))
    if shared.sha(shared.canonical(proof))!=p['tracking_variant_proof_sha256']:
        raise shared.UpdateError('tracking_variant_proof_changed')
    expected={'canonical_sku':sku,'affiliate_url':affiliate['url'],'destination_url':destination,'subids':subids,
        'variants':affiliate.get('variants'),'actual_product_photo_sha256':p['actual_product_photo_sha256']}
    if any(proof.get(k)!=v for k,v in expected.items()) or proof.get('root_actual_destination_variant_subids_verified') is not True:
        raise shared.UpdateError('actual_destination_variant_photo_tracking_proof_mismatch')
    try:
        checked=gate.aware(proof['verified_at'])
        if checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(hours=24)):raise ValueError()
    except Exception:raise shared.UpdateError('fresh_actual_product_tracking_variant_proof_required') from None
    monthly=shared.read(images.local(root,p['monthly_plan_path'],'design_revision'))
    if shared.sha(shared.canonical(monthly))!=p['monthly_plan_sha256'] or not isinstance(monthly.get('operations'),list):raise shared.UpdateError('commercial_monthly_plan_changed')
    rows=[x for x in monthly['operations'] if isinstance(x,dict) and x.get('package_id')==p['package_id']]
    if rows!=[{'action':'schedule_new_commercial_product_photo','package_id':p['package_id'],'after_schedule':slot,'canonical_sku':sku}]:
        raise shared.UpdateError('exact_commercial_monthly_sku_slot_decision_required')
    if not allow_elapsed and not current.timestamp()+images.MARGIN<=slot<=current.timestamp()+60*86400:
        raise shared.UpdateError('commercial_slot_outside_local_60minute_60day_window')
    return package,manifest,affiliate,slot,local.strftime('%Y-%m')


def verify_plan(plan,key,channel,root,now=None,allow_elapsed=False):
    fields={'action','channel','page_id','page_name','reviewed_at','package_id','package_path','package_sha256',
        'mobile_path','mobile_sha256','actual_product_photo_path','actual_product_photo_sha256','canonical_sku',
        'tracking_variant_proof_path','tracking_variant_proof_sha256','monthly_plan_path','monthly_plan_sha256',
        'worker_before_sha256','mapping_before_sha256','monthly_sales_limit_after','root_actual_product_photo_confirmed',
        'root_variant_destination_subids_confirmed','root_existing_single_writer_confirmed','root_whole_page_7day_cooldown_confirmed',
        'root_monthly_sales_plan_confirmed','root_enable_exact_selected_comment_after_native_verified'}
    if set(plan)!={'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'),dict) or set(plan['payload'])!=fields:
        raise shared.UpdateError('invalid_new_commercial_plan_schema')
    p=plan['payload'];digest=shared.sha(shared.canonical(p));current=now or datetime.now(timezone.utc)
    if (p['action']!='schedule_new_commercial_product_photo' or p['channel']!=key or channel.get('platform')!='facebook' or
        p['page_id']!=str(channel['page_id']) or p['page_name']!=channel.get('page_name',channel.get('name')) or
        type(p['monthly_sales_limit_after']) is not int or not 1<=p['monthly_sales_limit_after']<=2 or
        any(p[x] is not True for x in fields if x.startswith('root_'))):raise shared.UpdateError('commercial_identity_and_explicit_root_reviews_required')
    try:
        checked=gate.aware(p['reviewed_at'])
        if checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(minutes=30)):raise ValueError()
        if plan['payload_sha256']!=digest:raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True),digest.encode())
    except Exception:raise shared.UpdateError('invalid_or_stale_root_commercial_signature') from None
    package_check(p,key,channel,root,current,allow_elapsed)
    return p,digest


def run(p,digest,channel,root,api,mode='audit',sync=None):
    if mode not in ('audit','apply','reconcile'):raise shared.UpdateError('invalid_mode')
    if mode=='apply' and sync is None:raise shared.UpdateError('durable_product_reservation_sync_required')
    if mode=='audit':return _run(p,digest,channel,root,api,mode,sync)
    with shared.lock(root):return _run(p,digest,channel,root,api,mode,sync)


def _run(p,digest,channel,root,api,mode,sync):
    root=Path(root).resolve();shared.identity(api,channel)
    package,manifest,affiliate,slot,month=package_check(p,p['channel'],channel,root,allow_elapsed=mode!='apply')
    caption=(package/'caption.txt').read_text(encoding='utf-8').strip()
    ledger_path=root/'design_revision/commercial_schedule_ledger.json';ledger=shared.read(ledger_path) if ledger_path.exists() else {}
    record=ledger.get(p['package_id'],{})
    if record and record.get('plan_sha256')!=digest:raise shared.UpdateError('existing_commercial_plan_held')
    worker_path,mapping_path,worker,mapping,cfg=config_files(root)
    if str(cfg.get('account_id'))!=p['page_id'] or cfg.get('affiliate_mode')!='selected_only':
        raise shared.UpdateError('exact_page_selected_only_single_worker_required')
    policy.validate_affiliate_policy(cfg)
    def save(state,paths=None,**values):
        record.update(state=state,plan_sha256=digest,package_id=p['package_id'],page_id=p['page_id'],updated_at=datetime.now(timezone.utc).isoformat(),**values)
        ledger[p['package_id']]=record
        try:
            shared.atomic(ledger_path,ledger)
            if sync:sync(root,[ledger_path,*(paths or [])])
        except Exception:raise shared.UpdateError('commercial_mapping_or_reservation_persistence_failed') from None
    def native_match():
        if not record.get('photo_id'):raise shared.UpdateError('commercial_photo_id_unknown_reconcile_required')
        matches=[x for x in api.queue(p['page_id']) if shared.attachment_ids(x.get('attachments',{}))==[record['photo_id']] and x.get('message')==caption and x.get('scheduled_publish_time')==slot]
        if len(matches)!=1 or (record.get('new_post_id') and record['new_post_id']!=matches[0]['id']):raise shared.UpdateError('commercial_exact_native_queue_match_required')
        return images.new_check(api,p,{**record,'new_post_id':matches[0]['id']})
    if record:
        if mode!='reconcile':return {'status':'held_commercial_reconcile_required','state':record.get('state'),'external_writes_this_run':0}
        after=native_match()
        if record.get('state')=='verified' and shared.sha(shared.canonical(worker))==record.get('worker_after_sha256') and shared.sha(shared.canonical(mapping))==record.get('mapping_after_sha256'):
            return {'status':'verified','post_id':after['post_id'],'external_writes_this_run':0}
        # Unknown creation never recreates or silently enables monetization.
        return {'status':'held_commercial_mapping_review_required','native_verified_post_id':after['post_id'],'state':record.get('state'),'external_writes_this_run':0}
    if mode=='reconcile':return {'status':'held_no_commercial_reservation','external_writes_this_run':0}
    if shared.sha(shared.canonical(worker))!=p['worker_before_sha256'] or shared.sha(shared.canonical(mapping))!=p['mapping_before_sha256']:
        raise shared.UpdateError('root_reviewed_worker_or_mapping_changed')
    selected=cfg.get('selected_affiliate_posts',{}).get(month,[])
    if len(selected)>=p['monthly_sales_limit_after']:raise shared.UpdateError('reviewed_monthly_commercial_limit_full')
    proposed_policy=copy.deepcopy(cfg);proposed_policy['monthly_sales_limit']=p['monthly_sales_limit_after']
    try:policy.validate_affiliate_policy(proposed_policy)
    except ValueError:raise shared.UpdateError('reviewed_new_limit_conflicts_with_existing_selected_months') from None
    if any(x.get('canonical_sku')==p['canonical_sku'] and abs(x.get('slot',0)-slot)<7*86400 for x in ledger.values()):
        raise shared.UpdateError('commercial_sku_7day_reservation_cooldown')
    if any(x.get('scheduled_publish_time')==slot for x in api.queue(p['page_id'])):raise shared.UpdateError('commercial_slot_occupied')
    for filename in ('editorial_schedule_ledger.json','replacement_ledger.json'):
        path=root/'design_revision'/filename
        if path.exists() and any(x.get('page_id')==p['page_id'] and x.get('slot')==slot for x in shared.read(path).values()):
            raise shared.UpdateError('another_image_adapter_reserved_commercial_slot')
    if mode=='audit':return {'status':'verified_commercial_preview','package_id':p['package_id'],'canonical_sku':p['canonical_sku'],'slot':slot,'external_writes_this_run':0}
    reserved_product={'canonical_sku':p['canonical_sku'],'shop_id':affiliate['shop_id'],'product_id':affiliate['product_id'],
        'name':affiliate['name'],'url':affiliate['url'],'comment':affiliate['comment'],'subids':affiliate['subids'],'variants':affiliate['variants']}
    save('reserved_create',slot=slot,caption_sha256=shared.sha(caption.encode()),canonical_sku=p['canonical_sku'],product_reservation=reserved_product,
         package_sha256=p['package_sha256'],month=month,paths=[package/'affiliate.json',images.local(root,p['tracking_variant_proof_path'],'design_revision/revisions')])
    package_check(p,p['channel'],channel,root)
    _,_,latest_worker,latest_mapping,_=config_files(root)
    if shared.sha(shared.canonical(latest_worker))!=p['worker_before_sha256'] or shared.sha(shared.canonical(latest_mapping))!=p['mapping_before_sha256']:
        raise shared.UpdateError('worker_or_mapping_changed_during_commercial_reservation')
    if any(x.get('scheduled_publish_time')==slot for x in api.queue(p['page_id'])):raise shared.UpdateError('commercial_slot_changed_during_reservation')
    try:
        response=api.create(p['page_id'],package,caption,slot);photo_id=str(response.get('id',''));new_id=str(response.get('post_id',''))
        if not photo_id.isdecimal() or (new_id and not re.fullmatch(re.escape(p['page_id'])+r'_[0-9]+',new_id)):
            raise shared.UpdateError('commercial_create_exact_ids_unavailable',ambiguous=True)
    except shared.UpdateError as error:save('unknown_create' if error.ambiguous else 'failed_create',error=error.details);raise
    save('created_pending_readback',photo_id=photo_id,new_post_id=new_id or None)
    try:after=native_match()
    except shared.UpdateError as error:save('unknown_create',error=error.details);raise
    save('native_verified_pending_mapping',new_post_id=after['post_id'],after=after)
    aliases={after['post_id'],after['post_id'].rsplit('_',1)[-1],photo_id}
    # Do not overwrite any existing alias or inline worker override. The worker
    # remains unselected until all actual aliases and policy are durable together.
    if aliases.intersection(mapping['facebook']) or aliases.intersection(cfg.get('post_products',{})):
        raise shared.UpdateError('commercial_exact_alias_conflict_preserve_existing')
    product={**reserved_product,'affiliate_enabled':True,'scheduled_at':manifest['scheduled_at'],'root_package_sha256':p['package_sha256']}
    for alias in aliases:mapping['facebook'][alias]=copy.deepcopy(product)
    cfg['monthly_sales_limit']=p['monthly_sales_limit_after'];cfg.setdefault('selected_affiliate_posts',{}).setdefault(month,[]).append(after['post_id'])
    policy.validate_affiliate_policy(cfg)
    shared.atomic(mapping_path,mapping);shared.atomic(worker_path,worker)
    save('enabling_verified_exact_mapping',paths=[mapping_path,worker_path],aliases=sorted(aliases),
         worker_after_sha256=shared.sha(shared.canonical(worker)),mapping_after_sha256=shared.sha(shared.canonical(mapping)))
    native_match()
    save('verified',after=after)
    return {'status':'verified_commercial_native_and_exact_mapping','post_id':after['post_id'],'photo_id':photo_id,
        'canonical_sku':p['canonical_sku'],'existing_single_worker_selected':True,'affiliate_comment_delivery_verified':None,'external_writes_this_run':1}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--mode',choices=('audit','apply','reconcile'),default='audit');parser.add_argument('--git-state',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=images.local(root,args.plan,'design_revision/plans');p,digest=verify_plan(shared.read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
        result=run(p,digest,channel,root,images.Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),args.mode,shared.git_sync if args.git_state else None)
        print(json.dumps(result,ensure_ascii=False))
    except shared.UpdateError as error:print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception:print(json.dumps({'status':'held','error':{'reason':'invalid_local_commercial_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
