import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from core.action_loader import ActionRegistry
from core import workspace
from core import popups

class DispatchTests(unittest.TestCase):
 def test_file_action_is_blocked_before_handler(self):
  handler=Mock();registry=ActionRegistry({'screen_process':SimpleNamespace(valid=True,handler=handler)},logger=lambda s:None)
  with patch.object(workspace,'settings',return_value={'vision':False}):
   result=registry.run('screen_process',{})
  self.assertIn('status=failed',result);handler.assert_not_called()
 def test_notifications_off_never_calls_os(self):
  with patch.object(workspace,'settings',return_value={'notifications':False}),patch.object(popups.subprocess,'run') as run:
   self.assertFalse(popups.show('Task','Finished'))
  run.assert_not_called()
 def test_direct_capture_is_blocked(self):
  from actions.screen_processor import capture_screen,_capture_camera
  with patch.object(workspace,'settings',return_value={'vision':False}):
   with self.assertRaises(PermissionError):capture_screen()
   with self.assertRaises(PermissionError):_capture_camera()
if __name__=='__main__':unittest.main()

class CaptureRevocationTests(unittest.TestCase):
 def test_switch_off_during_capture_does_not_return_image(self):
  import os
  from actions import screen_processor as m
  state={'vision':True}
  def frame():state['vision']=False;return b'png'
  with patch.object(workspace,'settings',side_effect=lambda:state),patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland'}),patch.object(m,'_capture_via_portal',side_effect=frame),patch.object(m,'_compress',return_value=(b'jpeg','image/jpeg')):
   with self.assertRaises(PermissionError):m.capture_screen()
