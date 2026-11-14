import base64
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from core import wayland_capture as m

class SharingTests(unittest.TestCase):
    def tearDown(self):
        m.stop_capture()

    def process(self, responses):
        return SimpleNamespace(
            stdin=io.BytesIO(),
            stdout=io.BytesIO(b''.join(json.dumps(row).encode()+b'\n' for row in responses)),
            stderr=io.BytesIO(), poll=lambda:None, wait=Mock(), terminate=Mock(), kill=Mock())

    def test_two_captures_reuse_one_worker_and_stop_closes_pipes(self):
        png=b'\x89PNG\r\n\x1a\nframe'
        response={'png':base64.b64encode(png).decode()}
        process=self.process([response,response])
        with patch.object(m.subprocess,'Popen',return_value=process) as launch, patch.object(m.selectors,'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value=[True]
            self.assertEqual(m.capture_frame(),png)
            self.assertEqual(m.capture_frame(),png)
            launch.assert_called_once()
            self.assertEqual(process.stdin.getvalue(),b'capture\ncapture\n')
            m.stop_capture()
            self.assertIsNone(m._process)
            self.assertTrue(process.stdout.closed)

    def test_denial_is_reported_once_and_worker_stops(self):
        process=self.process([{'error':'Sharing denied'}])
        with patch.object(m.subprocess,'Popen',return_value=process) as launch, patch.object(m.selectors,'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value=[True]
            with self.assertRaisesRegex(RuntimeError,'Sharing denied'):
                m.capture_frame()
            launch.assert_called_once()
            self.assertIsNone(m._process)

    def test_revoked_sharing_status_releases_worker(self):
        m._process=self.process([{'active':False}])
        with patch.object(m.selectors,'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value.select.return_value=[True]
            self.assertFalse(m.is_active())
            self.assertIsNone(m._process)

if __name__=='__main__':unittest.main()
