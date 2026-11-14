import unittest
from unittest.mock import patch
from core.browser_bridge import BrowserBridge
class BridgeTests(unittest.TestCase):
    def test_pair_code_is_one_use(self):
        with patch('core.browser_bridge.config.get_browser_connections',return_value=[]),patch('core.browser_bridge.config.save_browser_connections'),patch('core.browser_bridge.config.save_workspace_settings'),patch('core.browser_bridge.config.get_workspace_settings',return_value={}):
            bridge=BrowserBridge();code=bridge.new_pairing_code()
            result=bridge.pair(code,'profile-1','Work')
            self.assertTrue(result['token'])
            with self.assertRaises(PermissionError):bridge.pair(code,'profile-2','Other')
            self.assertNotIn('token',bridge.snapshot()['profiles'][0])
    def test_disconnected_profile_cannot_run(self):
        with patch('core.browser_bridge.config.get_browser_connections',return_value=[]),patch('core.browser_bridge.config.save_browser_connections'),patch('core.browser_bridge.config.save_workspace_settings'),patch('core.browser_bridge.config.get_workspace_settings',return_value={}),patch('core.workspace.require'):
            bridge=BrowserBridge();bridge.pair(bridge.new_pairing_code(),'p','Work')
            with self.assertRaisesRegex(RuntimeError,'not connected'):bridge.request('p','get_text',{})
if __name__=='__main__':unittest.main()
