import importlib.util,unittest,os
from unittest.mock import patch
from core import platform_support as m
class PlatformTests(unittest.TestCase):
 def test_wayland_allows_portal_vision_but_not_global_input(self):
  with patch.object(m.platform,'system',return_value='Linux'),patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland'}):
   support=m.detect()
  self.assertTrue(support.can_capture_screen)
  self.assertFalse(support.can_control_input)
  limits=' '.join(m.describe_for_model(support))
  self.assertIn('browser_control',limits)
  self.assertNotIn('CANNOT see',limits)
if __name__=='__main__':unittest.main()
