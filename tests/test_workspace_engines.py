from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile,unittest
from core import workspace
from core.routines.engine import RoutineEngine
from core.tasks.engine import TaskEngine

class EngineTests(unittest.TestCase):
 def test_routine_editor_add_update_pause_and_delete(self):
  with tempfile.TemporaryDirectory() as tmp:
   engine=RoutineEngine(Path(tmp)/'routines.json',SimpleNamespace(),autostart=False)
   with patch.object(workspace,'routine_engine',return_value=engine),patch.object(workspace,'record'):
    result=workspace.save_routine({'name':'Review','kind':'prompt','text':'Review changes','time':'09:00','days':'1,2,3,4,5'})
    self.assertEqual(result['trigger']['rule']['days'],[1,2,3,4,5])
    update=workspace.save_routine({'name':'Daily review','text':'Check changes','time':'10:00','days':'1,2','enabled':False},result['id'])
    self.assertFalse(update['enabled']);self.assertEqual(update['trigger']['rule']['time'],'10:00')
    self.assertTrue(engine.remove(result['id']));self.assertEqual(engine.list(),[])
 def test_routines_off_do_not_run(self):
  with tempfile.TemporaryDirectory() as tmp:
   engine=RoutineEngine(Path(tmp)/'routines.json',SimpleNamespace(),autostart=False)
   routine={'kind':'say','text':'hello'}
   with patch.object(workspace,'settings',return_value={'routines':False}):
    self.assertEqual(engine._fire(routine),'paused in Workspace')
    engine.tick()
 def test_task_results_use_existing_engine_store(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   engine=TaskEngine(root/'tasks',root/'reports',[Path(__file__).resolve().parent.parent/'agents'],autostart=False)
   with patch('core.tasks.desktop.ensure',return_value=engine),patch.object(workspace,'record'):
    task=workspace.start_task('Compare two approaches','general',5)
    self.assertEqual(workspace.task_action(task['id'],'result')['task'],'Compare two approaches')
    self.assertTrue(workspace.task_action(task['id'],'cancel'))
if __name__=='__main__':unittest.main()
