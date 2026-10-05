"""Actual sole-worker integration with synthetic APIs; no external writes."""
import json, tempfile, unittest
from pathlib import Path
import auto_affiliate as aa

class Fake:
    def __init__(self): self.writes=[]
    def get_identity(self): return {'id':'111','username':'Fixture'}
    def iter_posts(self,since):
        yield {'id':'111_222','aliases':['222'],'created_at':'2026-10-05T00:00:00+00:00','original':True,'published':True,'text':'fixture keyword'}
    def iter_existing_replies(self,post_id): return iter([])
    def publish_reply(self,post_id,text): self.writes.append((post_id,text)); return '333'
    def verify_reply(self,post_id,reply_id): return reply_id=='333'

class SelectedOnlyWorker(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.json';self.api=Fake()
        self.product={'name':'Fixture','url':'https://s.shopee.co.th/fixture','comment':'Fixture.\n'+aa.DISCLOSURE+'\nhttps://s.shopee.co.th/fixture','affiliate_enabled':True}
        self.cfg={'account_id':'111','expected_username':'Fixture','rollout_since':'2026-10-01T00:00:00Z','lookback_hours':720,
                  'affiliate_mode':'selected_only','monthly_sales_limit':2,'selected_affiliate_posts':{'2026-10':[]},
                  'post_products':{'111_222':self.product},'approved_fallback':self.product,
                  'catalog':[{**self.product,'keywords':['fixture keyword']}]}
    def run_worker(self):
        return aa.AffiliateReconciler('facebook',self.cfg,aa.StateStore(self.path),self.api,publish=True).run()
    def test_empty_selection_blocks_blanket_explicit_keyword_and_fallback_and_preserves_history(self):
        history={'facebook':{'111':{'111_100':{'status':'existing','reply_id':'777'}}}}
        self.path.write_text(json.dumps(history),encoding='utf-8');before=self.path.read_bytes()
        result=self.run_worker()
        self.assertEqual(result['skipped']['affiliate_not_selected'],1)
        self.assertEqual(self.api.writes,[]);self.assertEqual(self.path.read_bytes(),before)
    def test_opt_out_alias_wins_even_when_full_id_selected(self):
        self.cfg['selected_affiliate_posts']['2026-10']=['111_222']
        self.cfg['post_products']['222']={**self.product,'affiliate_enabled':False}
        result=self.run_worker()
        self.assertEqual(result['skipped']['affiliate_explicit_opt_out'],1);self.assertEqual(self.api.writes,[])
    def test_only_reviewed_selected_mapping_writes_once(self):
        self.cfg['selected_affiliate_posts']['2026-10']=['111_222']
        result=self.run_worker();self.assertEqual(result['published'],1);self.assertEqual(len(self.api.writes),1)
        self.run_worker();self.assertEqual(len(self.api.writes),1)

if __name__=='__main__':unittest.main()
