import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt,QPoint
from PyQt6.QtTest import QTest
from gui.workspace_panel import WorkspaceDialog
from memory import config_manager as config

class WorkspaceUITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def wait(self,condition):
  end=time.monotonic()+3
  while time.monotonic()<end:
   self.app.processEvents()
   if condition():return
   time.sleep(.01)
  self.fail('Workspace background operation did not finish')
 def test_six_sections_and_real_notification_toggle(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'config';folder.mkdir()
   with patch.object(config,'BASE_DIR',root),patch.object(config,'CONFIG_DIR',folder),patch.object(config,'CONFIG_FILE',folder/'api_keys.json'):
    dialog=WorkspaceDialog();dialog.show();dialog.timer.stop()
    try:
     self.wait(lambda:not dialog._busy)
     self.assertEqual(dialog.nav.count(),6)
     checkbox=dialog.flags['notifications'];self.assertTrue(checkbox.isChecked())
     QTest.mouseClick(checkbox,Qt.MouseButton.LeftButton,pos=QPoint(12,checkbox.height()//2))
     self.wait(lambda:not dialog._busy)
     self.assertFalse(config.get_workspace_settings()['notifications'])
     self.assertFalse(checkbox.isChecked())
    finally:
     dialog.close();dialog._executor.shutdown(wait=True);self.app.processEvents()
if __name__=='__main__':unittest.main()
