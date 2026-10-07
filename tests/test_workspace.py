import unittest
from unittest.mock import patch
from minioj.workspace import WorkspaceManager

class WorkspaceBrowsingTests(unittest.TestCase):
    def test_read_and_list_during_terminal_reservation(self):
        manager=WorkspaceManager(); manager.busy.add('run')
        with patch.object(manager,'active',return_value={'container':'sandbox'}), patch('minioj.workspace.read_file',return_value=b'1 2\n') as read, patch('minioj.workspace.files',return_value={'files':[{'path':'sample.in','size':4}]}) as listing:
            self.assertEqual(manager.file_action('run','read','sample.in')['content'],'1 2\n')
            self.assertEqual(manager.file_action('run','list')['files'][0]['path'],'sample.in')
            read.assert_called_once_with('sandbox','sample.in')
            listing.assert_called_once_with('sandbox',{'op':'list'})
            self.assertIn('run',manager.busy)
    def test_write_still_requires_exclusive_reservation(self):
        manager=WorkspaceManager();manager.busy.add('run')
        with patch.object(manager,'active',return_value={'container':'sandbox'}), patch('minioj.workspace.write_file') as write:
            with self.assertRaisesRegex(ValueError,'active command or terminal'):
                manager.file_action('run','write','main.cpp','code')
            write.assert_not_called()
            self.assertIn('run',manager.busy)
