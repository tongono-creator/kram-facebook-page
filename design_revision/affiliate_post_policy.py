"""Optional selected-only affiliate gate; default legacy behavior is unchanged."""
import re


def validate_affiliate_policy(config):
    if config.get('affiliate_mode','legacy')=='legacy':return None
    if config.get('affiliate_mode')!='selected_only':raise ValueError('Unknown affiliate mode')
    limit=config.get('monthly_sales_limit')
    if not isinstance(limit,int) or isinstance(limit,bool) or not 0<=limit<=2:
        raise ValueError('Selected-only monthly sales limit must be 0–2')
    groups=config.get('selected_affiliate_posts')
    if not isinstance(groups,dict):raise ValueError('Selected-only reviewed post allowlist required')
    account=str(config.get('account_id',''));seen=set()
    for month,ids in groups.items():
        if not isinstance(month,str) or not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])',month):
            raise ValueError('Reviewed publication month required')
        if not isinstance(ids,list) or len(ids)>limit:raise ValueError('Monthly selected affiliate post ceiling exceeded')
        for post_id in ids:
            if not isinstance(post_id,str) or not re.fullmatch(re.escape(account)+r'_[0-9]+',post_id) or post_id in seen:
                raise ValueError('Selected posts must be unique exact page/post IDs')
            seen.add(post_id)
    return seen


def affiliate_skip_reason(post,config):
    selected=validate_affiliate_policy(config)
    if selected is None:return None
    fullkeys={str(x) for x in [post.get('id'),*post.get('aliases',[])] if x}
    if not selected.intersection(fullkeys):return 'affiliate_not_selected'
    keys=set(fullkeys)|{x.rsplit('_',1)[-1] for x in fullkeys}
    entries=[v for k,v in config.get('post_products',{}).items() if str(k) in keys]
    if any(isinstance(v,dict) and v.get('affiliate_enabled') is False for v in entries):return 'affiliate_explicit_opt_out'
    if not any(isinstance(v,dict) and v.get('affiliate_enabled') is True for v in entries):
        return 'affiliate_reviewed_mapping_missing'
    return None
