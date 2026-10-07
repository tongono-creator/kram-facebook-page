"""GET-only complete queue + exact known IMAGE node/photo/comment audit.

Retains actual returned nodes for archives. It never reconstructs native proof
from snapshots and contains no mutation path, signing or retry logic.
"""
import argparse
import json
import os
from datetime import datetime,timezone
from pathlib import Path
import facebook_card_update as shared
import facebook_future_replacement as images
import facebook_post_reschedule as timing


def audit(api,channel,known):
    shared.identity(api,channel)
    page_id=str(channel['page_id']);queue=api.queue(page_id)
    queue_ids=[x.get('id') for x in queue]
    if len(queue_ids)!=len(set(queue_ids)) or any(not isinstance(x,str) for x in queue_ids):
        raise shared.UpdateError('complete_queue_identity_unavailable_or_duplicate')
    result={'status':'complete_get_only_image_inventory','checked_at':datetime.now(timezone.utc).isoformat(),
        'page_id':page_id,'page_name':channel.get('page_name',channel.get('name')),
        'complete_scheduled_queue':queue,'complete_queue_read':True,'queue_ids':queue_ids,
        'records':[],'external_writes':0}
    seen=set()
    for item in known:
        post_id=item.get('post_id')
        if post_id in seen:raise shared.UpdateError('duplicate_known_image_inventory_id')
        seen.add(post_id);record={'known':item,'post_id':post_id,'status':'held'}
        try:
            post=api.post(post_id);record['native_post']=post
            timing.photo_post(post);snap=shared.snapshot(post,page_id);record['live']=snap
            photo=api.photo(snap['attachment_ids'][0]);record['native_photo']=photo
            if str(photo.get('id'))!=snap['attachment_ids'][0] or str(photo.get('from',{}).get('id'))!=page_id:
                raise shared.UpdateError('original_photo_owner_unverified')
            if snap['is_published']:
                record['status']='published_preserved';record['eligible_future_zero_comment_image']=False
            else:
                if post_id not in queue_ids:raise shared.UpdateError('unpublished_known_post_absent_from_complete_queue')
                record['no_comments']=images.comments_absent(api,snap)
                images.future_photo(post,page_id)
                record['status']='audited_future_image_zero_comments';record['eligible_future_zero_comment_image']=True
        except shared.UpdateError as error:
            record['error']=error.details;record['eligible_future_zero_comment_image']=False
        result['records'].append(record)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--channel',required=True)
    parser.add_argument('--inventory',type=Path,default=Path('design_revision/inventory.json'))
    args=parser.parse_args();root=args.root.resolve()
    try:
        channel=shared.read(root/'design_revision/channels.json')[args.channel];shared.verify_repository(root,channel)
        path=images.local(root,args.inventory,'design_revision')
        known=[x for x in shared.read(path) if x.get('channel')==args.channel]
        if not known:raise shared.UpdateError('known_image_inventory_for_channel_required')
        result=audit(images.Facebook(os.getenv(channel.get('token_env','PAGE_ACCESS_TOKEN'))),channel,known)
        print(json.dumps(result,ensure_ascii=False))
    except shared.UpdateError as error:print(json.dumps({'status':'held','error':error.details,'external_writes':0}));raise SystemExit(1)
    except Exception:print(json.dumps({'status':'held','error':{'reason':'invalid_local_image_inventory_config'},'external_writes':0}));raise SystemExit(1)


if __name__=='__main__':main()
