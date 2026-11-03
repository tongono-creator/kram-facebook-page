import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import queue_runner
import studio


class ExactQueueSelection(unittest.TestCase):
    def test_selected_release_preserves_other_queue_entries(self):
        queue={'packages':['packages/old','packages/approved','packages/next']}
        self.assertEqual(queue_runner.select_packages(queue,'approved'),['packages/approved'])
        self.assertEqual(len(queue['packages']),3)
        self.assertEqual(queue_runner.select_packages(queue),queue['packages'])

    def test_cannot_select_unqueued_duplicate_or_path_traversal(self):
        for queue,ident in [({'packages':['packages/old']},'missing'),
                            ({'packages':['packages/a','packages/a']},'a'),
                            ({'packages':['packages/a']},'../a')]:
            with self.assertRaises(studio.GateError):queue_runner.select_packages(queue,ident)
