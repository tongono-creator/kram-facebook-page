"""The production single writer must send the comment the editor approved."""
import importlib.util
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT.parent/'auto_affiliate.py'
if not PATH.exists():
    PATH=ROOT/'worktrees'/'kram'/'auto_affiliate.py'
spec=importlib.util.spec_from_file_location('affiliate_bridge_fixture',PATH)
affiliate=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=affiliate
spec.loader.exec_module(affiliate)

class AffiliateBridgeTests(unittest.TestCase):
    def test_explicit_mapping_preserves_reviewed_comment(self):
        url='https://s.shopee.co.th/syntheticfixture'
        comment='พิกัดตามโจทย์ของโพสต์ ไม่แต่งราคา\n'+affiliate.DISCLOSURE+'\n'+url
        selection=affiliate.select_product({'id':'123_456','text':'offline fixture'},{'post_products':{'123_456':{'name':'Fixture','url':url,'comment':comment}}})
        self.assertEqual(affiliate.build_comment(selection),comment)
    def test_second_link_in_reviewed_comment_is_rejected(self):
        url='https://s.shopee.co.th/syntheticfixture'
        with self.assertRaises(ValueError):
            affiliate.validate_product({'name':'Fixture','url':url,'comment':affiliate.DISCLOSURE+'\n'+url+'\nhttps://s.shopee.co.th/other'})
    def test_legacy_product_still_receives_disclosure(self):
        selection=affiliate.Selection({'name':'Fixture','url':'https://s.shopee.co.th/syntheticfixture'},'keyword')
        self.assertIn(affiliate.DISCLOSURE,affiliate.build_comment(selection))
