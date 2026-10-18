"""Secret-scan controls and unavailable-result reporting."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load


class SecretControlIsolationTests(unittest.TestCase):
    def test_controls_do_not_read_application_or_retained_fixture_files(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        with patch.dict(sys.modules, {"export": SimpleNamespace(export=None)}):
            module = load("secret_scan")
        original_read = Path.read_text

        def read_report_only(path, *args, **kwargs):
            self.assertEqual(path.name, "report.json")
            return original_read(path, *args, **kwargs)

        def scan(command, **kwargs):
            source = Path(command[2])
            files = sorted(p for p in source.rglob("*") if p.is_file())
            self.assertEqual(len(files), 3)
            report = Path(command[command.index("--report-path") + 1])
            report.write_text(
                json.dumps([dict(File=str(p), StartLine=2) for p in files])
            )
            return SimpleNamespace(returncode=1)

        with (
            patch.object(module.subprocess, "run", side_effect=scan),
            patch.object(Path, "read_text", read_report_only),
        ):
            module.verify_rules(Path("gitleaks"), Path(".gitleaks.toml"))


class SecretScanFailureTests(unittest.TestCase):
    def test_checkout_scan_does_not_require_retained_resource_manifest(self):
        module = load("export")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app").mkdir()
            (root / "app/code.py").write_text("PUBLIC = True\n")
            # No retained manifest or ignored review resource exists in checkout.
            module.export(
                root / "scan", root=root, files=["app/code.py"], include_retained=False
            )
            self.assertEqual((root / "scan/app/code.py").read_text(), "PUBLIC = True\n")
            with self.assertRaises(FileNotFoundError):
                module.export(root / "retained", root=root, files=["app/code.py"])
            (root / "config").mkdir()
            (root / "config/ci-retained-resources.json").write_text(
                json.dumps(
                    {
                        "resources": {
                            "app/reviews/native/index-live-engineering-v1.json": "0"
                            * 64
                        }
                    }
                )
            )
            with self.assertRaisesRegex(
                ValueError, "Missing or changed retained resource"
            ):
                module.export(root / "retained", root=root, files=["app/code.py"])
            module.export(
                root / "scan-with-stale-manifest",
                root=root,
                files=["app/code.py"],
                include_retained=False,
            )
            self.assertTrue((root / "scan-with-stale-manifest/app/code.py").is_file())

    def test_scan_setup_failure_writes_unavailable_metrics_and_summary_reason(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        import subprocess

        with patch.dict(sys.modules, {"export": SimpleNamespace(export=None)}):
            module = load("secret_scan")
        for stage in ("controls", "export", "execution"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / "quality"

                def scanner(*args, **kwargs):
                    raise subprocess.TimeoutExpired("gitleaks", 120)

                with (
                    patch.object(
                        sys, "argv", ["secret_scan.py", "--output", str(output)]
                    ),
                    patch.object(
                        module,
                        "verify_rules",
                        side_effect=ValueError(
                            "must not publish arbitrary error payload"
                        )
                        if stage == "controls"
                        else None,
                    ),
                    patch.object(
                        module,
                        "export",
                        side_effect=OSError("must not publish arbitrary error payload")
                        if stage == "export"
                        else None,
                    ) as exported,
                    patch.object(module.subprocess, "run", side_effect=scanner),
                ):
                    self.assertEqual(module.main(), 1)
                data = json.loads((output / "secret-metrics.json").read_text())
                self.assertEqual(data["status"], "FAIL")
                self.assertIsNone(data["findings"])
                self.assertNotIn("arbitrary error payload", json.dumps(data))
                if stage != "controls":
                    self.assertFalse(exported.call_args.kwargs["include_retained"])
                text, records, failed = load("quality_report").render(
                    {"secrets": {"outcome": "failure"}}, output.parent, expanded=True
                )
                record = next(r for r in records if r["name"] == "secrets")
                self.assertTrue(failed)
                self.assertEqual(record["reason"], data["reason"])
                self.assertIn("Secret scan unavailable during", text)
                self.assertNotIn("No such file or directory: &#x27;", record["reason"])
