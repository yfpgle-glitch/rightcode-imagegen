from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import image_output_layout as layout
import generate_image as client

class OutputLayoutTests(unittest.TestCase):
    def test_nested_package_uses_repository_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); (root/'.git').mkdir(); (root/'code').mkdir(); (root/'code/package.json').write_text('{}')
            result=layout.resolve_layout(cwd=root/'code', now=datetime(2026,9,5), task_namespace='rightcode')
            self.assertEqual(result.images_dir,root/'output/images/2026-09-05')
            self.assertEqual(result.prompts_dir,root/'output/images/.prompts/2026-09-05')
            self.assertEqual(result.task_dir,root/'output/images/.tasks/rightcode')

    def test_explicit_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp).resolve()/'custom'
            result=layout.resolve_layout(target,task_namespace='rightcode')
            self.assertEqual(result.images_dir,target)
            self.assertEqual(result.prompts_dir,target/'.prompts')

    def test_no_root_and_home_are_not_default_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve(); (home/'AGENTS.md').write_text(''); child=home/'child'; child.mkdir()
            self.assertIsNone(layout.find_project_root(child,home=home))
            with mock.patch.object(layout,'find_project_root',return_value=None):
                with self.assertRaises(layout.ImageOutputLayoutError):
                    layout.resolve_layout(cwd=child,task_namespace='rightcode')

    def test_old_checkpoint_is_copied_and_current_one_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); (root/'.git').mkdir(); code=root/'code';code.mkdir()
            old=code/'generated_images/.tasks/rightcode/right-code-task-old.json';old.parent.mkdir(parents=True);old.write_text('{"prompt":"original"}')
            result=layout.resolve_layout(cwd=code,task_namespace='rightcode')
            with mock.patch.object(client.Path,'cwd',return_value=code):
                client.restore_legacy_checkpoint(result,'old')
                target=result.task_dir/old.name
                self.assertEqual(target.read_bytes(),old.read_bytes())
                target.write_text('newer')
                client.restore_legacy_checkpoint(result,'old')
                self.assertEqual(target.read_text(),'newer')
                self.assertTrue(old.exists())

if __name__=='__main__': unittest.main()
