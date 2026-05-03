from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = ROOT / "scripts"

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_hosted_validation as hosted_validation


class HostedValidationRunnerTest(unittest.TestCase):
    def test_promoted_route_fallback_without_artifact_fails(self) -> None:
        with self.assertRaises(hosted_validation.HostedValidationFailure) as caught:
            hosted_validation.enforce_promotion_evidence(
                [
                    {
                        "route": "/api/bootstrap",
                        "flow": "bootstrap",
                        "status_code": 200,
                        "served_by": "legacy",
                        "fallback": "1",
                        "policy": hosted_validation.PROMOTED_POLICY,
                        "artifact_path": "",
                        "artifact_exists": False,
                    }
                ],
                require_postgres_primary=False,
            )
        self.assertEqual(caught.exception.report["reason"], "silent_promoted_fallback")

    def test_promoted_route_requires_existing_artifact(self) -> None:
        with self.assertRaises(hosted_validation.HostedValidationFailure) as caught:
            hosted_validation.enforce_promotion_evidence(
                [
                    {
                        "route": "/api/bootstrap",
                        "flow": "bootstrap",
                        "status_code": 200,
                        "served_by": "postgres",
                        "fallback": "0",
                        "policy": hosted_validation.PROMOTED_POLICY,
                        "artifact_path": "/tmp/does-not-exist.json",
                        "artifact_exists": False,
                    }
                ],
                require_postgres_primary=False,
            )
        self.assertEqual(caught.exception.report["reason"], "promoted_route_artifact_path_missing")

    def test_promoted_route_can_pass_green_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "contracts") as tempdir:
            artifact_path = Path(tempdir) / "promotion.json"
            artifact_path.write_text("{}", encoding="utf-8")
            hosted_validation.enforce_promotion_evidence(
                [
                    {
                        "route": "/api/bootstrap",
                        "flow": "bootstrap",
                        "status_code": 200,
                        "served_by": "postgres",
                        "fallback": "0",
                        "policy": hosted_validation.PROMOTED_POLICY,
                        "artifact_path": str(artifact_path),
                        "artifact_exists": True,
                    }
                ],
                require_postgres_primary=True,
            )

    def test_require_postgres_primary_rejects_fallback_even_with_artifact(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "contracts") as tempdir:
            artifact_path = Path(tempdir) / "fallback.json"
            artifact_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(hosted_validation.HostedValidationFailure) as caught:
                hosted_validation.enforce_promotion_evidence(
                    [
                        {
                            "route": "/api/bootstrap",
                            "flow": "bootstrap",
                            "status_code": 200,
                            "served_by": "legacy",
                            "fallback": "1",
                            "policy": hosted_validation.PROMOTED_POLICY,
                            "artifact_path": str(artifact_path),
                            "artifact_exists": True,
                            "storage_fallback": "0",
                            "storage_artifact_path": "",
                            "storage_artifact_exists": False,
                        }
                    ],
                    require_postgres_primary=True,
                )
        self.assertEqual(caught.exception.report["reason"], "promoted_route_not_served_by_postgres")

    def test_storage_fallback_without_artifact_fails(self) -> None:
        with self.assertRaises(hosted_validation.HostedValidationFailure) as caught:
            hosted_validation.enforce_promotion_evidence(
                [
                    {
                        "route": "/api/documents/7/download",
                        "flow": "document_download",
                        "status_code": 200,
                        "served_by": "postgres",
                        "fallback": "0",
                        "policy": hosted_validation.PROMOTED_POLICY,
                        "artifact_path": str(ROOT / "contracts" / "shadow" / "promotion-summary.json"),
                        "artifact_exists": True,
                        "storage_fallback": "1",
                        "storage_artifact_path": "",
                        "storage_artifact_exists": False,
                    }
                ],
                require_postgres_primary=False,
            )
        self.assertEqual(caught.exception.report["reason"], "silent_storage_fallback")


if __name__ == "__main__":
    unittest.main()
