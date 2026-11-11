"""Moving data from the old name ("AI Voice Studio") to Audiovane."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import legacy  # noqa: E402


class MigrateDir(unittest.TestCase):
    def test_old_folder_is_renamed_with_contents(self):
        with tempfile.TemporaryDirectory() as t:
            old = os.path.join(t, "AI Voice Studio", "models")
            os.makedirs(old)
            open(os.path.join(old, "m.bin"), "w").write("x")
            new = legacy.migrate_dir(os.path.join(t, "Audiovane"))
            self.assertTrue(os.path.isfile(os.path.join(new, "models", "m.bin")))
            self.assertFalse(os.path.exists(os.path.join(t, "AI Voice Studio")))

    def test_existing_new_folder_is_left_alone(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "AI Voice Studio"))
            os.makedirs(os.path.join(t, "Audiovane"))
            legacy.migrate_dir(os.path.join(t, "Audiovane"))
            self.assertTrue(os.path.isdir(os.path.join(t, "AI Voice Studio")))

    def test_nothing_to_migrate(self):
        with tempfile.TemporaryDirectory() as t:
            p = legacy.migrate_dir(os.path.join(t, "Audiovane"))
            self.assertFalse(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()
