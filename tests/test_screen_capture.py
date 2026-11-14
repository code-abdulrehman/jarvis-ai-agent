import importlib.util
import os
import sys
import unittest
from unittest.mock import patch
from actions import screen_processor as m
class CaptureTests(unittest.TestCase):
    def test_wayland_uses_portal_before_x11(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}), patch.object(m, '_capture_via_portal', create=True, return_value=b'png') as portal, patch.object(m, '_capture_via_cli', side_effect=AssertionError('X11 called')), patch.object(m, '_compress', return_value=(b'jpeg', 'image/jpeg')):
            self.assertEqual(m.capture_screen(), (b'jpeg', 'image/jpeg'))
            portal.assert_called_once()
    def test_denial_is_not_retried(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}), patch.object(m, '_capture_via_portal', create=True, side_effect=RuntimeError('cancelled')) as portal, patch.object(m, '_capture_via_cli', side_effect=AssertionError('X11 called')):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                m.capture_screen()
            portal.assert_called_once()
    def test_x11_still_uses_existing_capture(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11', 'WAYLAND_DISPLAY': ''}), patch.object(m, '_capture_once', return_value=(b'png', 'image/png')) as capture:
            self.assertEqual(m.capture_screen(), (b'png', 'image/png'))
            capture.assert_called_once()
if __name__ == '__main__': unittest.main()
