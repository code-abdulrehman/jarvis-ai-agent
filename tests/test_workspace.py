import unittest
from unittest.mock import patch
from core import workspace as w

class WorkspaceTests(unittest.TestCase):
    def test_vision_disabled_blocks_screen_and_camera(self):
        with patch.object(w, 'settings', return_value={'vision': False}):
            self.assertIsNotNone(w.denial('screen_process', {'angle':'screen'}))
            self.assertIsNotNone(w.denial('screen_process', {'angle':'camera'}))
            self.assertIsNone(w.denial('close_camera', {}))

    def test_app_open_and_close_are_separate(self):
        with patch.object(w, 'settings', return_value={'apps_open':True, 'apps_close':False}):
            self.assertIsNone(w.denial('open_app', {'action':'open'}))
            self.assertIsNotNone(w.denial('open_app', {'action':'close'}))

    def test_browser_off_still_allows_disconnect(self):
        with patch.object(w, 'settings', return_value={'browser':False}):
            self.assertIsNotNone(w.denial('browser_control', {'action':'click'}))
            self.assertIsNone(w.denial('browser_control', {'action':'close_all'}))

    def test_terminal_is_independent_from_mouse(self):
        with patch.object(w, 'settings', return_value={'computer':False,'terminal':True}):
            self.assertIsNotNone(w.denial('computer_control', {'action':'click'}))
            self.assertIsNone(w.denial('terminal_control', {'action':'run_command'}))
            self.assertIsNotNone(w.denial('terminal_control', {'action':'type_command'}))

if __name__=='__main__':unittest.main()
