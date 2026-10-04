import json
import os
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import test_gate as fixtures
import studio

class SignatureTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.EditorialGateTests('test_valid_package_is_returned_with_identity_intact')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.package=fixture.package
        key=Ed25519PrivateKey.generate()
        self.key_path=fixture.root/'synthetic-key.pem'
        self.key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        self.config={**fixture.channel,'require_signature':True,'editor_public_key':key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
    def approve(self):
        with patch.dict(os.environ,{'STUDIO_EDITOR_KEY':str(self.key_path)}):
            studio.approve_package(self.package,notes='Synthetic signed test',checks=fixtures.CHECKS)
    def test_unsigned_live_review_is_rejected(self):
        with patch.dict(os.environ,{},clear=True):
            studio.approve_package(self.package,notes='Synthetic unsigned test',checks=fixtures.CHECKS)
        with self.assertRaises(studio.GateError):
            studio.verify_approval(self.package,self.config,now=fixtures.NOW)
    def test_signed_intact_package_passes(self):
        self.approve()
        studio.verify_approval(self.package,self.config,now=fixtures.NOW)
    def test_approval_text_tampering_breaks_signature(self):
        self.approve()
        path=self.package/'review.json'
        review=studio.read_json(path);review['notes']='Tampered approval'
        path.write_text(json.dumps(review),encoding='utf-8')
        with self.assertRaises(studio.GateError):
            studio.verify_approval(self.package,self.config,now=fixtures.NOW)
