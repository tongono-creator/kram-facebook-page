"""Root-signed NEW editorial batch; serial reservations, no creation retries."""
import argparse
import base64
import json
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import facebook_card_update as shared
import facebook_future_replacement as images
import facebook_editorial_schedule as editorial
import studio_optional as gate


def verify_batch(plan,key,channel,root,now=None,allow_elapsed=False):
    fields={'action','channel','page_id','page_name','reviewed_at','plans','root_batch_new_posts_only_confirmed'}
    if set(plan)!={'payload','payload_sha256','root_signature'} or not isinstance(plan.get('payload'),dict) or set(plan['payload'])!=fields:
        raise shared.UpdateError('invalid_new_editorial_batch_schema')
    p=plan['payload'];digest=shared.sha(shared.canonical(p));current=now or datetime.now(timezone.utc)
    if (p['action']!='schedule_new_editorial_batch' or p['channel']!=key or p['page_id']!=str(channel['page_id']) or
        p['page_name']!=channel.get('page_name',channel.get('name')) or p['root_batch_new_posts_only_confirmed'] is not True or
        not isinstance(p['plans'],list) or not 1<=len(p['plans'])<=50):raise shared.UpdateError('new_editorial_batch_identity_or_review_mismatch')
    try:
        checked=gate.aware(p['reviewed_at'])
        if checked>current+timedelta(minutes=5) or (not allow_elapsed and current-checked>timedelta(minutes=30)):raise ValueError()
        if plan['payload_sha256']!=digest:raise ValueError()
        load_pem_public_key(channel['editor_public_key'].encode()).verify(base64.b64decode(plan['root_signature'],validate=True),digest.encode())
    except Exception:raise shared.UpdateError('invalid_or_stale_root_new_batch_signature') from None
    entries=[];ids=set();slots=set();paths=set()
    for item in p['plans']:
        if not isinstance(item,dict) or set(item)!={'path','plan_sha256'} or item['path'] in paths:raise shared.UpdateError('invalid_or_duplicate_batch_plan_reference')
        path=images.local(root,item['path'],'design_revision/plans');signed=shared.read(path)
        if shared.sha(shared.canonical(signed))!=item['plan_sha256']:raise shared.UpdateError('batch_individual_signed_plan_changed')
        payload,d=editorial.verify_plan(signed,key,channel,root,current,allow_elapsed=allow_elapsed)
        _,_,slot=editorial.package_check(payload,key,channel,root,current,allow_elapsed=allow_elapsed)
        if payload['package_id'] in ids or slot in slots:raise shared.UpdateError('duplicate_batch_package_or_same_page_slot')
        ids.add(payload['package_id']);slots.add(slot);paths.add(item['path']);entries.append((payload,d))
    return entries


def run(entries,channel,root,api,mode='audit',sync=None):
    results=[]
    for p,digest in entries:
        result=editorial.run(p,digest,channel,root,api,mode,sync)
        # A completed exact ledger entry may be re-read when continuing a batch.
        # Ambiguous/failed/reserved creation always holds; never retry it here.
        if mode=='apply' and result.get('state')=='verified':
            result=editorial.run(p,digest,channel,root,api,'reconcile',sync)
        results.append({'package_id':p['package_id'],**result})
        if str(result.get('status','')).startswith('held'):break
    return {'status':'batch_held' if len(results)!=len(entries) or any(str(x['status']).startswith('held') for x in results) else 'batch_verified' if mode!='audit' else 'batch_preview',
            'results':results,'processed':len(results),'requested':len(entries),'external_writes_this_run':sum(x.get('external_writes_this_run',0) for x in results)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--channel',required=True);parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--mode',choices=('audit','apply','reconcile'),default='audit');parser.add_argument('--git-state',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=images.local(root,args.plan,'design_revision/plans')
        entries=verify_batch(shared.read(path),args.channel,channel,root,allow_elapsed=args.mode!='apply')
        result=run(entries,channel,root,images.Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),args.mode,shared.git_sync if args.git_state else None)
        print(json.dumps(result,ensure_ascii=False))
        if result['status']=='batch_held':raise SystemExit(1)
    except shared.UpdateError as error:print(json.dumps({'status':'held','error':error.details}));raise SystemExit(1)
    except Exception:print(json.dumps({'status':'held','error':{'reason':'invalid_local_new_batch_config_or_plan'}}));raise SystemExit(1)


if __name__=='__main__':main()
