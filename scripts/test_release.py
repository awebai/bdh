import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("release.py")
SPEC = importlib.util.spec_from_file_location("bdh_release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(release)


class ReleaseScriptTests(unittest.TestCase):
    def test_normalize_version(self):
        self.assertEqual(release.normalize_version("0.12.0"), ("0.12.0", "v0.12.0"))
        self.assertEqual(release.normalize_version("v1.2.3"), ("1.2.3", "v1.2.3"))

    def test_rejects_ambiguous_versions(self):
        for value in ("latest", "0.11.8", "01.2.3", "1.2", "v1.2.3-rc.1", "v1.2.3/other"):
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                release.normalize_version(value)

    def test_exact_asset_names(self):
        names = {
            release.asset_name("0.12.0", goos, goarch)
            for goos, goarch in release.PLATFORMS
        }
        self.assertEqual(
            names,
            {
                "bdh_0.12.0_darwin_amd64.tar.gz",
                "bdh_0.12.0_darwin_arm64.tar.gz",
                "bdh_0.12.0_linux_amd64.tar.gz",
                "bdh_0.12.0_linux_arm64.tar.gz",
                "bdh_0.12.0_windows_amd64.zip",
                "bdh_0.12.0_windows_arm64.zip",
            },
        )

    def test_archives_are_stable_and_have_only_expected_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bdh"
            license_file = root / "LICENSE"
            readme = root / "README.md"
            binary.write_bytes(b"binary")
            license_file.write_text("license", encoding="utf-8")
            readme.write_text("readme", encoding="utf-8")
            files = [(binary, "bdh", 0o755), (license_file, "LICENSE", 0o644), (readme, "README.md", 0o644)]
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            release.stable_tar(first, files, 1_700_000_000)
            release.stable_tar(second, files, 1_700_000_000)
            self.assertEqual(release.sha256(first), release.sha256(second))
            self.assertEqual(release.archive_members(first), ["bdh", "LICENSE", "README.md"])

    def test_installer_is_install_only_and_uses_canonical_repository(self):
        installer = SCRIPT.parents[1].joinpath("install.sh").read_text(encoding="utf-8")
        self.assertIn('REPO="awebai/bdh"', installer)
        self.assertIn('archive_name="${BINARY}_${VERSION}_${platform}.${ext}"', installer)
        self.assertIn('"$LAST_INSTALL_PATH" :version', installer)
        self.assertIn('LAST_INSTALL_PATH="$bin_dir/bdh$goexe"', installer)
        self.assertIn('output_binary="bdh$(go env GOEXE 2>/dev/null || true)"', installer)
        self.assertNotIn('bdh version 2>/dev/null || echo "bdh (development build)"', installer)
        self.assertNotIn("run_init", installer)
        self.assertNotIn("BEADHUB_API_KEY", installer)

    def test_rejects_unknown_receipt_format_before_reading_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            stage.joinpath("release-receipt.json").write_text(
                json.dumps({"format_version": 2}), encoding="utf-8"
            )
            stage.joinpath("checksums.txt").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(release.ReleaseError, "format_version"):
                release.verify_stage(SCRIPT.parents[1], stage)

    def test_optional_action_cannot_race_runnerless_tag_push(self):
        workflow = SCRIPT.parents[1].joinpath(".github/workflows/bdh-release.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("push:\n    tags:", workflow)
        self.assertIn("refusing to replace runnerless artifacts", workflow)

    def test_publication_modes_keep_public_releases_immutable(self):
        tag = "v0.12.0"
        expected = {"archive.tar.gz", "checksums.txt", "release-receipt.json"}
        assets = [{"name": name} for name in sorted(expected)]
        self.assertEqual(release.publication_mode(None, tag, expected), "create")
        self.assertEqual(
            release.publication_mode(
                {"tagName": tag, "isDraft": True, "isPrerelease": False, "assets": []}, tag, expected
            ),
            "resume",
        )
        self.assertEqual(
            release.publication_mode(
                {"tagName": tag, "isDraft": False, "isPrerelease": True, "assets": assets}, tag, expected
            ),
            "resume",
        )
        self.assertEqual(
            release.publication_mode(
                {"tagName": tag, "isDraft": False, "isPrerelease": False, "assets": assets}, tag, expected
            ),
            "verify",
        )
        with self.assertRaisesRegex(release.ReleaseError, "incomplete"):
            release.publication_mode(
                {"tagName": tag, "isDraft": False, "isPrerelease": False, "assets": []}, tag, expected
            )


if __name__ == "__main__":
    unittest.main()
