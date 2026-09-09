from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def test_skill_entrypoint_is_at_repository_root(self):
        self.assertTrue((ROOT / "SKILL.md").is_file())
        self.assertFalse(
            (ROOT / "skills" / "rightcode-image" / "SKILL.md").exists()
        )


if __name__ == "__main__":
    unittest.main()
