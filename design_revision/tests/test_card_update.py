"""Offline safety tests only; generated fixture keys, no credentials or Meta writes."""
import base64
import copy
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
import facebook_card_update as update


class Fake:
 def __init__(self,root,post):
  self.root=root;self.value=copy.deepcopy(post);self.writes=[];self.upload_error=None;self.replace_error=None;self.after_upload_change=False;self.slot_change=False
 def identity(self):return {'id':'111','name':'Fixture'}
 def post(self,id):return copy.deepcopy(self.value)
 def photo(self,id):return {'id':id,'from':{'id':'111'}}
 def upload(self,page,path):
  ledger=update.read(self.root/'design_revision/ledger.json')
  assert ledger['111_222']['state']=='reserved_upload'
  self.writes.append(('upload',page))
  if self.upload_error:raise self.upload_error
  if self.after_upload_change:self.value['message']='Someone edited this during upload'
  return {'id':'999'}
 def replace(self,id,photo,message):
  ledger=update.read(self.root/'design_revision/ledger.json')
  assert ledger[id]['state']=='reserved_update' and ledger[id]['photo_id']==photo
  self.writes.append(('replace',id))
  if self.replace_error:raise self.replace_error
  self.value['message']=message;self.value['attachments']={'data':[{'target':{'id':photo}}]}
  if self.slot_change:self.value['scheduled_publish_time']+=3600
  return {'success':True}


class CardUpdate(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  folder=self.root/'design_revision/revisions/pilot';folder.mkdir(parents=True)
  for n in ['card.png','mobile.png']:(folder/n).write_bytes(('Fixture '+n).encode())
  self.now=datetime(2026,10,5,12,tzinfo=timezone.utc)
  key=Ed25519PrivateKey.generate();self.key=key
  self.channel={'platform':'facebook','page_id':'111','name':'Fixture','editor_public_key':key.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo).decode()}
  self.post={'id':'111_222','from':{'id':'111'},'is_published':False,'scheduled_publish_time':1791200000,
    'message':'Original fictional AI explanation','attachments':{'data':[{'target':{'id':'333'}}]}}
  self.payload={'action':'replace_same_post_card','channel':'kram_fb','page_id':'111','page_name':'Fixture','post_id':'111_222',
    'reviewed_at':self.now.isoformat(),'before':update.snapshot(self.post,'111'),
    'card_path':'design_revision/revisions/pilot/card.png','mobile_path':'design_revision/revisions/pilot/mobile.png',
    'card_sha256':update.sha((folder/'card.png').read_bytes()),'mobile_sha256':update.sha((folder/'mobile.png').read_bytes()),
    'message_after':'Bigger headline. AI editorial illustration; fictional scene.','caption_disclosure_confirmed':True,'root_visual_confirmed':True}
  self.digest=update.sha(update.canonical(self.payload));self.api=Fake(self.root,self.post)
 def signed(self):
  digest=update.sha(update.canonical(self.payload))
  return {'payload':self.payload,'payload_sha256':digest,'root_signature':base64.b64encode(self.key.sign(digest.encode())).decode()}
 def run_correction(self,mode='apply',sync=None):return update.correct(self.payload,self.digest,self.channel,self.root,self.api,mode,sync)
 def test_root_signature_tamper_and_corrected_image_hash_are_checked(self):
  update.verify_plan(self.signed(),'kram_fb',self.channel,self.root,self.now)
  plan=self.signed();plan['payload']['message_after']='Tampered AI copy'
  with self.assertRaises(update.UpdateError):update.verify_plan(plan,'kram_fb',self.channel,self.root,self.now)
  (self.root/self.payload['mobile_path']).write_bytes(b'changed after Root inspection')
  with self.assertRaises(update.UpdateError):update.verify_plan(self.signed(),'kram_fb',self.channel,self.root,self.now)
 def test_existing_signed_package_path_cannot_be_used_as_corrected_asset(self):
  folder=self.root/'packages/original';folder.mkdir(parents=True);(folder/'card.png').write_bytes(b'original')
  self.payload.update(card_path='packages/original/card.png',card_sha256=update.sha(b'original'))
  with self.assertRaises(update.UpdateError):update.verify_plan(self.signed(),'kram_fb',self.channel,self.root,self.now)
 def test_audit_preview_has_no_file_or_api_mutations(self):
  result=self.run_correction('audit')
  self.assertEqual(result['external_writes_this_run'],0);self.assertEqual(self.api.writes,[])
  self.assertFalse((self.root/'design_revision/ledger.json').exists())
 def test_durable_reservations_before_both_posts_preserve_same_id_and_slot(self):
  synced=[]
  def sync(root,paths):synced.append(update.read(paths[0])['111_222']['state'])
  result=self.run_correction(sync=sync)
  self.assertEqual(result['post_id'],'111_222');self.assertEqual(self.api.writes,[('upload','111'),('replace','111_222')])
  self.assertEqual(synced,['reserved_upload','uploaded','reserved_update','verified'])
  self.assertEqual(self.api.value['scheduled_publish_time'],self.post['scheduled_publish_time'])
  self.assertFalse(self.api.value['is_published'])
 def test_already_published_post_keeps_publication_and_absent_schedule(self):
  self.api.value['is_published']=True;self.api.value.pop('scheduled_publish_time')
  self.payload['before']=update.snapshot(self.api.value,'111')
  result=self.run_correction()
  self.assertEqual(result['status'],'verified');self.assertTrue(self.api.value['is_published'])
  self.assertNotIn('scheduled_publish_time',self.api.value)
 def test_unknown_upload_holds_and_never_uploads_again(self):
  self.api.upload_error=update.UpdateError('timeout',ambiguous=True)
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.api.upload_error=None;result=self.run_correction()
  self.assertEqual(result['status'],'held_reconcile_required');self.assertEqual(len(self.api.writes),1)
 def test_known_rejection_does_not_retry_but_same_id_ui_reconciliation_is_get_only(self):
  self.api.replace_error=update.UpdateError('rejected',403,200)
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.assertEqual(self.run_correction()['status'],'held_reconcile_required');self.assertEqual(len(self.api.writes),2)
  self.api.value['message']=self.payload['message_after'];self.api.value['attachments']={'data':[{'target':{'id':'999'}}]}
  result=self.run_correction('reconcile')
  self.assertEqual(result['status'],'verified_reconciled');self.assertEqual(result['external_writes_this_run'],0)
  self.assertEqual(len(self.api.writes),2)
 def test_unknown_update_does_not_retry_and_reads_same_id_only(self):
  self.api.replace_error=update.UpdateError('timeout',ambiguous=True)
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.assertEqual(self.run_correction()['status'],'held_reconcile_required');self.assertEqual(len(self.api.writes),2)
 def test_live_edit_during_upload_preserved_with_no_post_update(self):
  self.api.after_upload_change=True
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.assertEqual(self.api.writes,[('upload','111')])
  self.assertEqual(self.api.value['message'],'Someone edited this during upload')
 def test_changed_schedule_after_update_is_unknown_not_success(self):
  self.api.slot_change=True
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.assertEqual(update.read(self.root/'design_revision/ledger.json')['111_222']['state'],'unknown_update')
  self.assertEqual(self.run_correction()['status'],'held_reconcile_required');self.assertEqual(len(self.api.writes),2)
 def test_sync_failure_prevents_upload_and_retains_reservation(self):
  def fail(root,paths):raise RuntimeError('private remote details should not leak')
  with self.assertRaises(update.UpdateError) as error:self.run_correction(sync=fail)
  self.assertNotIn('private',str(error.exception));self.assertEqual(self.api.writes,[])
  self.assertEqual(self.run_correction()['status'],'held_reconcile_required')
 def test_photo_wrong_owner_or_missing_fiction_prevents_post_update(self):
  self.api.photo=lambda id:{'id':id,'from':{'id':'other'}}
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.assertEqual(self.api.writes,[('upload','111')])
 def test_fiction_marker_cannot_be_removed_even_with_ai_caption(self):
  self.payload['message_after']='AI editorial illustration only.'
  with self.assertRaises(update.UpdateError):self.run_correction()
  self.assertEqual(self.api.writes,[])
 def test_graph_adapter_uses_bearer_and_only_unpublished_upload_same_post_message_attachment(self):
  class Response:
   ok=True;status_code=200
   def json(self):return {'success':True,'id':'999'}
  class Session:
   def __init__(self):self.headers={};self.calls=[]
   def request(self,*a,**kw):self.calls.append((a,kw));return Response()
  session=Session();api=update.Facebook('FIXTURE_SECRET',session)
  api.upload('111',self.root/self.payload['card_path']);api.replace('111_222','999','AI caption')
  self.assertEqual(session.headers['Authorization'],'Bearer FIXTURE_SECRET')
  self.assertEqual(session.calls[0][1]['data'],{'published':'false'})
  self.assertEqual(set(session.calls[1][1]['data']),{'message','attached_media'})
  self.assertTrue(session.calls[1][0][1].endswith('/111_222'))
  self.assertTrue(all('FIXTURE_SECRET' not in a[1] for a,_ in session.calls))


if __name__=='__main__':unittest.main()
