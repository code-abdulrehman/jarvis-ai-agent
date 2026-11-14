import unittest
from core.codex_connection import CodexConnection
class CodexTests(unittest.TestCase):
 def test_notifications_do_not_resolve_requests(self):
  client=CodexConnection();client._handle({'method':'turn/started','params':{'threadId':'a'}})
  self.assertEqual(client.snapshot()['events'][0]['method'],'turn/started')
 def test_server_approvals_wait_for_user(self):
  client=CodexConnection();client._handle({'id':12,'method':'item/commandExecution/requestApproval','params':{'command':'echo hi'}})
  self.assertEqual(client.snapshot()['approvals'][0]['id'],12)
 def test_unrecognized_approval_is_not_autoaccepted(self):
  client=CodexConnection();client._handle({'id':3,'method':'unknown/requestApproval','params':{}})
  with self.assertRaises(ValueError):client.approve(3,True)
if __name__=='__main__':unittest.main()
