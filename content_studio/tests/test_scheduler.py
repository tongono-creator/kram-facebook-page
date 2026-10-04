"""Offline release tests. Synthetic approvals do not approve any real content."""
import json
import os
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scheduler
import studio


class FakeApi:
    def __init__(self):
        self.queue, self.published, self.writes = [], [], []
        self.error, self.hide = None, False
        self.ident = {'id': '123', 'name': 'Test page'}

    def identity(self):
        return self.ident

    def posts(self, published=False):
        return list(self.published if published else self.queue)

    def schedule(self, package, caption, slot):
        self.writes.append((str(package), caption, slot))
        if self.error:
            raise self.error
        if not self.hide:
            self.queue.append({'id': '123_456', 'message': caption, 'scheduled_publish_time': slot,
                               'attachments': {'data': [{'target': {'id': '789'}}]}})
        return {'id': '789', 'post_id': '123_456'}


class SchedulerTests(unittest.TestCase):
    def test_photo_only_response_is_resolved_from_exact_live_photo_and_slot(self):
        original = self.api.schedule
        def photo_only(*args):
            response = original(*args)
            return {'id': response['id']}
        self.api.schedule = photo_only
        result = self.runner.run([self.package],publish=True)
        self.assertEqual(result[0]['status'],'verified')
        self.assertEqual(result[0]['post_id'],'123_456')
        self.assertEqual(len(self.api.writes),1)
        self.assertEqual(studio.read_json(self.runner.path)[studio.read_json(self.package/'manifest.json')['id']]['post_id'],'123_456')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.channel = {'platform': 'facebook', 'enabled': True, 'channel_key': 'kram_fb',
                        'page_id': '123', 'name': 'Test page', 'allowed_categories': ['home']}
        self.package = self.root/'package'; self.package.mkdir()
        now = datetime.now(timezone.utc)
        self.slot = int((now+timedelta(days=2)).timestamp())
        manifest = {'id': 'test-one', 'channel_key': 'kram_fb', 'page_id': '123',
                    'scheduled_at': datetime.fromtimestamp(self.slot,timezone.utc).isoformat(),
                    'visual_type': 'ai_editorial', 'product_id': 'sku-one', 'status': 'draft'}
        url = 'https://s.shopee.co.th/testfixture'
        affiliate = {'product_id': 'sku-one', 'name': 'Synthetic storage product', 'url': url,
                     'category': 'home', 'eligible_channels': ['kram_fb'], 'verified_at': now.isoformat(),
                     'disclosure': studio.DISCLOSURE, 'comment': studio.DISCLOSURE+'\n'+url}
        evidence = {'fictional': True, 'editorial_note': 'Offline fixture only'}
        for filename, value in [('manifest.json',manifest),('affiliate.json',affiliate),('evidence.json',evidence)]:
            (self.package/filename).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        (self.package/'caption.txt').write_text('สมมติ Test AI illustration',encoding='utf-8')
        (self.package/'card.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0'*4+b'IHDR'+struct.pack('>II',1080,1350)+b'\0'*20)
        with patch.dict(os.environ, {}, clear=True):
            studio.approve_package(self.package,notes='Synthetic test checks only',checks={key:True for key in studio.CHECKS})
        self.api = FakeApi()
        self.runner = scheduler.Scheduler(self.root,self.channel,api=self.api)

    def ledger(self):
        return studio.read_json(self.root/'content_studio_ledger.json')

    def reserve(self, **extra):
        self.runner.save('test-one','unknown',package_sha256=studio.digest_package(self.package),
                         page_id='123',scheduled_at=datetime.fromtimestamp(self.slot,timezone.utc).isoformat(),**extra)

    def test_default_dry_run_does_not_use_api_or_write_files(self):
        self.api.identity = lambda: self.fail('No network on local dry-run')
        self.assertEqual(self.runner.run([self.package])[0]['status'],'dry_run')
        self.assertFalse(self.runner.path.exists())
        self.assertFalse(self.runner.mapping.exists())
        self.assertFalse((self.root/'content_studio_ledger.lock').exists())

    def test_live_preview_reads_without_reserving_or_posting(self):
        self.assertEqual(self.runner.run([self.package],live_preview=True)[0]['status'],'live_preview')
        self.assertEqual(self.api.writes,[])
        self.assertFalse(self.runner.path.exists())

    def test_success_is_verified_and_maps_all_worker_aliases(self):
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'verified')
        self.assertEqual(self.ledger()['test-one']['status'],'verified')
        mapping = studio.read_json(self.runner.mapping)['facebook']
        self.assertEqual(set(mapping),{'123_456','456','789'})
        self.assertEqual(mapping['789']['name'],'Synthetic storage product')
        self.runner.run([self.package],publish=True)
        self.assertEqual(len(self.api.writes),1)

    def test_wrong_token_identity_stops_before_write(self):
        self.api.ident = {'id':'999','name':'Test page'}
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertFalse(self.runner.path.exists())
        self.assertEqual(self.api.writes,[])

    def test_existing_slot_rejected_even_with_same_caption(self):
        self.api.queue = [{'id':'123_old','message':'สมมติ Test AI illustration','scheduled_publish_time':self.slot}]
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.api.writes,[])

    def test_timeout_reserves_unknown_and_never_reposts(self):
        self.api.error = scheduler.ApiError('POST')
        with self.assertRaises(scheduler.ApiError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.ledger()['test-one']['status'],'unknown')
        self.api.error = None
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'held')
        self.assertEqual(len(self.api.writes),1)

    def test_known_rejection_is_failed_and_also_requires_reconciliation(self):
        self.api.error = scheduler.ApiError('POST',400)
        with self.assertRaises(scheduler.ApiError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.ledger()['test-one']['status'],'failed')
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'held')
        self.assertEqual(len(self.api.writes),1)

    def test_remote_reservation_failure_prevents_post(self):
        self.runner.sync = lambda paths: (_ for _ in ()).throw(scheduler.ScheduleError('Synthetic git rejection'))
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.ledger()['test-one']['status'],'publishing')
        self.assertEqual(self.api.writes,[])

    def test_success_with_missing_readback_keeps_identifiers_for_reconciliation(self):
        self.api.hide = True
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        record = self.ledger()['test-one']
        self.assertEqual((record['status'],record['post_id'],record['photo_id']),('unknown','123_456','789'))
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'held')
        self.assertEqual(len(self.api.writes),1)

    def test_unknown_can_reconcile_exact_live_slot_caption_photo(self):
        self.reserve(post_id='123_456',photo_id='789')
        self.api.queue = [{'id':'123_456','message':'สมมติ Test AI illustration','scheduled_publish_time':self.slot,
                           'attachments':{'data':[{'target':{'id':'789'}}]}}]
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'reconciled')
        self.assertEqual(self.api.writes,[])

    def test_wrong_photo_does_not_reconcile_or_repost(self):
        self.reserve(post_id='123_456',photo_id='789')
        self.api.queue = [{'id':'123_456','message':'สมมติ Test AI illustration','scheduled_publish_time':self.slot,
                           'attachments':{'data':[{'target':{'id':'other'}}]}}]
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'held')
        self.assertEqual(self.api.writes,[])

    def test_published_without_original_slot_cannot_prove_reservation(self):
        self.reserve(post_id='123_456',photo_id='789')
        self.api.published = [{'id':'123_456','message':'สมมติ Test AI illustration',
                              'attachments':{'data':[{'target':{'id':'789'}}]}}]
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'held')
        self.assertEqual(self.api.writes,[])

    def test_elapsed_known_post_recovers_by_exact_id_caption_photo_and_close_created_time(self):
        self.slot = int((datetime.now(timezone.utc)-timedelta(hours=1)).timestamp())
        manifest = studio.read_json(self.package/'manifest.json')
        manifest['scheduled_at'] = datetime.fromtimestamp(self.slot,timezone.utc).isoformat()
        (self.package/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        with patch.dict(os.environ,{},clear=True):
            studio.approve_package(self.package,notes='Synthetic elapsed review',checks={key:True for key in studio.CHECKS})
        self.reserve(post_id='123_456',photo_id='789')
        self.api.published = [{'id':'123_456','message':'สมมติ Test AI illustration',
                              'created_time':datetime.fromtimestamp(self.slot+60,timezone.utc).isoformat(),
                              'attachments':{'data':[{'target':{'id':'789'}}]}}]
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'reconciled')
        self.assertEqual(self.api.writes,[])

    def test_new_elapsed_package_remains_blocked(self):
        manifest = studio.read_json(self.package/'manifest.json')
        manifest['scheduled_at'] = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        (self.package/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        with patch.dict(os.environ,{},clear=True):
            studio.approve_package(self.package,notes='Synthetic elapsed review',checks={key:True for key in studio.CHECKS})
        with self.assertRaises(studio.GateError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.api.writes,[])

    def test_mapping_conflict_preserved_after_success(self):
        scheduler.atomic_json(self.runner.mapping,{'facebook':{'789':{'name':'Existing product','url':'https://s.shopee.co.th/old'}}})
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(studio.read_json(self.runner.mapping)['facebook']['789']['name'],'Existing product')
        self.assertEqual(self.ledger()['test-one']['post_id'],'123_456')
        self.assertEqual(len(self.api.writes),1)

    def test_changes_after_approval_rejected_before_api(self):
        (self.package/'caption.txt').write_text('Changed AI สมมติ',encoding='utf-8')
        with self.assertRaises(studio.GateError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.api.writes,[])

    def test_old_ledger_product_cooldown_blocks_new_package(self):
        self.runner.save('older-package','verified',page_id='123',product_id='sku-one',
                         scheduled_at=datetime.fromtimestamp(self.slot-86400,timezone.utc).isoformat())
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.api.writes,[])

    def test_mapping_push_failure_keeps_returned_remote_ids(self):
        calls = []
        def sync(paths):
            calls.append(paths)
            if len(calls)==3:
                raise scheduler.ScheduleError('Synthetic mapping push failed')
        self.runner.sync = sync
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.ledger()['test-one']['post_id'],'123_456')
        self.assertEqual(self.ledger()['test-one']['photo_id'],'789')
        self.runner.sync = None
        self.assertEqual(self.runner.run([self.package],publish=True)[0]['status'],'reconciled')
        self.assertEqual(len(self.api.writes),1)

    def test_preexisting_process_lock_prevents_release(self):
        (self.root/'content_studio_ledger.lock').write_text('Synthetic other process',encoding='utf-8')
        with self.assertRaises(scheduler.ScheduleError):
            self.runner.run([self.package],publish=True)
        self.assertEqual(self.api.writes,[])

    def test_package_changed_during_preflight_cannot_release(self):
        original_identity = self.api.identity
        def identity():
            (self.package/'caption.txt').write_text('สมมติ mutated AI',encoding='utf-8')
            return original_identity()
        self.api.identity = identity
        with self.assertRaises(studio.GateError):
            self.runner.run([self.package],publish=True)
        self.assertFalse(self.runner.path.exists())
        self.assertEqual(self.api.writes,[])

    def test_non_facebook_and_disabled_channels_rejected(self):
        for changes in ({'platform':'threads'},{'enabled':False}):
            with self.assertRaises(scheduler.ScheduleError):
                scheduler.Scheduler(self.root,{**self.channel,**changes},api=self.api)


class ApiSecurityTests(unittest.TestCase):
    def test_cli_publish_without_shared_state_stops_before_any_api_or_file_read(self):
        with patch.object(scheduler.FacebookApi, 'identity') as identity, patch.object(studio, 'read_json') as read:
            with self.assertRaisesRegex(scheduler.ScheduleError, 'requires --git-state'):
                scheduler.main(['--repo-root','unused','--channel','kram_fb','--packages','unused','--publish'])
            identity.assert_not_called()
            read.assert_not_called()

    def test_pagination_uses_cursor_and_bearer_never_next_token_url(self):
        with patch.dict(os.environ,{'PAGE_ACCESS_TOKEN':'TEST_SECRET_NOT_LIVE'}):
            api = scheduler.FacebookApi({'page_id':'123'})
        replies = [
            {'data':[{'id':'one'}],'paging':{'next':'https://graph.facebook.com/v25.0/123/scheduled_posts?access_token=TEST_SECRET_NOT_LIVE','cursors':{'after':'cursor-two'}}},
            {'data':[{'id':'two'}]},
        ]
        calls = []
        class Response:
            status_code = 200
            def json(self):
                return replies.pop(0)
        def request(method,url,**kwargs):
            calls.append((url,dict(kwargs['params'])))
            return Response()
        api.session.request = request
        self.assertEqual([post['id'] for post in api.posts()],['one','two'])
        self.assertTrue(all('TEST_SECRET_NOT_LIVE' not in url for url,_ in calls))
        self.assertEqual(calls[1][1]['after'],'cursor-two')
        self.assertEqual(api.session.headers['Authorization'],'Bearer TEST_SECRET_NOT_LIVE')

    def test_request_exception_does_not_expose_secret(self):
        with patch.dict(os.environ,{'PAGE_ACCESS_TOKEN':'TEST_SECRET_NOT_LIVE'}):
            api = scheduler.FacebookApi({'page_id':'123'})
        api.session.request = lambda *args,**kwargs: (_ for _ in ()).throw(scheduler.requests.RequestException('TEST_SECRET_NOT_LIVE'))
        with self.assertRaises(scheduler.ApiError) as caught:
            api.identity()
        self.assertNotIn('TEST_SECRET_NOT_LIVE',str(caught.exception))

    def test_http200_error_payload_is_not_treated_as_success(self):
        with patch.dict(os.environ,{'PAGE_ACCESS_TOKEN':'TEST_SECRET_NOT_LIVE'}):
            api = scheduler.FacebookApi({'page_id':'123'})
        class Response:
            status_code = 200
            def json(self):
                return {'error':{'message':'TEST_SECRET_NOT_LIVE'}}
        api.session.request = lambda *args,**kwargs: Response()
        with self.assertRaises(scheduler.ApiError) as caught:
            api.identity()
        self.assertNotIn('TEST_SECRET_NOT_LIVE',str(caught.exception))


if __name__ == '__main__':
    unittest.main()
