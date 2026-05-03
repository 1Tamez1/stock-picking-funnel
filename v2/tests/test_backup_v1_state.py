from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BackupScriptShapeTest(unittest.TestCase):
    def test_backup_script_references_canonical_v1_artifacts(self) -> None:
        script = (ROOT / "scripts" / "backup_v1_state.py").read_text(encoding="utf-8")
        self.assertIn("AGENT_RUNBOOK.md", script)
        self.assertIn("agent_payload_templates", script)
        self.assertIn("var", script)


if __name__ == "__main__":
    unittest.main()

