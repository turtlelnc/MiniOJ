import unittest
from unittest.mock import patch
from minioj.workspace import WorkspaceManager

class WorkspacePolicyTests(unittest.TestCase):
    def test_disabled_rejected_before_runtime_or_run_creation(self):
        manager=WorkspaceManager()
        with patch('minioj.workspace.db.problem',return_value={'allow_workspace':False}),patch('minioj.workspace.available') as runtime,patch('minioj.workspace.db.create_run') as create:
            with self.assertRaisesRegex(PermissionError,'未允许'):manager.create(1,'agent',{},True)
            runtime.assert_not_called();create.assert_not_called()
    def test_external_run_without_environment_allowed(self):
        with patch('minioj.workspace.db.problem',return_value={'allow_workspace':False}),patch('minioj.workspace.db.create_run',return_value='run'):
            self.assertEqual(WorkspaceManager().create(1,'agent',{},False),'run')
    def test_new_problem_defaults_disabled(self):
        from minioj.app import ProblemInput
        self.assertFalse(ProblemInput(title='x',testcases=[{'input':'','expected_output':''}]).allow_workspace)
