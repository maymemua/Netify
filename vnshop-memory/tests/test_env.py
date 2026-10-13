import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kg.env import load_env


class LoadEnvTest(unittest.TestCase):
    def test_reads_aura_credentials_file_format(self):
        content = ("\ufeff# Wait a few minutes before connecting using these details.\n"
                   "NEO4J_URI=neo4j+s://abc.databases.neo4j.io\n"
                   "NEO4J_USERNAME=abc\n"
                   'NEO4J_PASSWORD="p=ss word"\n'
                   "NEO4J_DATABASE=abc\n"
                   "AURA_INSTANCENAME=Free instance\n"
                   "EMPTY=\n")
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"NEO4J_DATABASE": "kept"}, clear=True):
            path = Path(d) / ".env"
            path.write_text(content, encoding="utf-8")
            load_env(path)
            self.assertEqual(os.environ["NEO4J_URI"], "neo4j+s://abc.databases.neo4j.io")
            self.assertEqual(os.environ["NEO4J_PASSWORD"], "p=ss word")
            self.assertEqual(os.environ["AURA_INSTANCENAME"], "Free instance")
            self.assertEqual(os.environ["NEO4J_DATABASE"], "kept")  # biến đặt sẵn được ưu tiên
            self.assertNotIn("EMPTY", os.environ)

    def test_missing_file_is_ignored(self):
        load_env(Path("/không/có/file/này/.env"))


if __name__ == "__main__":
    unittest.main()
