import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "tools" / "generate.py"
BASE = {
    "name": "Nexa Test", "pkg": "com.nexa.test", "vn": "1.0.0", "vc": 1,
    "min": 26, "fmt": "apk", "var": "release", "args": "", "abi": False,
    "perms": ["internet"], "color": "#FFD600", "url": "", "orient": "unspecified",
    "kiosk": False, "fs": False, "kp": False, "zm": False, "ex": False,
    "of": False, "pt": False, "sc": "", "ua": "", "bc": "", "flv": "",
    "fb": False, "minify": False, "ov": True, "out": "nexa-test"
}


class GeneratorTests(unittest.TestCase):
    def run_generator(self, root, command, config):
        env = os.environ.copy()
        env["CFG"] = json.dumps(config)
        env["GITHUB_OUTPUT"] = str(root / "github-output.txt")
        env["RUN"] = "1"
        return subprocess.run([sys.executable, str(SCRIPT), command], cwd=root, env=env,
                              text=True, capture_output=True)

    def test_scratch_prep_creates_strict_build_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = {**BASE, "sr": "scratch"}
            result = self.run_generator(root, "prep", cfg)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            script = (root / ".build.sh").read_text()
            self.assertIn("set -Eeuo pipefail", script)
            self.assertIn("gradle -p build_app assembleRelease", script)

    def test_invalid_package_fails_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {**BASE, "sr": "scratch", "pkg": "com.Bad Package"}
            result = self.run_generator(pathlib.Path(tmp), "prep", cfg)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Package name tidak valid", result.stdout)

    def test_zip_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "uploads").mkdir()
            with zipfile.ZipFile(root / "uploads" / "project.zip", "w") as archive:
                archive.writestr("../escape.txt", "not allowed")
            cfg = {**BASE, "sr": "zip", "zip": "uploads/project.zip"}
            result = self.run_generator(root, "prep", cfg)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("path di luar folder proyek", result.stdout)
            self.assertFalse((root.parent / "escape.txt").exists())

    def test_node_project_without_lockfile_uses_npm_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "uploads").mkdir()
            with zipfile.ZipFile(root / "uploads" / "project.zip", "w") as archive:
                archive.writestr("package.json", json.dumps({"name": "sample", "dependencies": {}}))
                archive.writestr("capacitor.config.json", json.dumps({"appId": "com.sample.app"}))
            cfg = {**BASE, "sr": "zip", "zip": "uploads/project.zip"}
            result = self.run_generator(root, "prep", cfg)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            script = (root / ".build.sh").read_text()
            self.assertIn("else npm install --no-audit --no-fund; fi", script)
            self.assertNotIn("npm ci || npm install", script)

    def test_subfolder_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "uploads").mkdir()
            with zipfile.ZipFile(root / "uploads" / "project.zip", "w") as archive:
                archive.writestr("app/package.json", json.dumps({"name": "sample"}))
                archive.writestr("app/index.html", "<h1>sample</h1>")
            cfg = {**BASE, "sr": "zip", "zip": "uploads/project.zip", "sub": "../outside"}
            result = self.run_generator(root, "prep", cfg)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Subfolder proyek tidak valid", result.stdout)

    def test_node_project_uses_lockfile_aware_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "uploads").mkdir()
            with zipfile.ZipFile(root / "uploads" / "project.zip", "w") as archive:
                archive.writestr("package.json", json.dumps({"name": "sample", "dependencies": {}}))
                archive.writestr("capacitor.config.json", json.dumps({"appId": "com.sample.app"}))
                archive.writestr("package-lock.json", json.dumps({"name": "sample", "lockfileVersion": 3, "packages": {}}))
            cfg = {**BASE, "sr": "zip", "zip": "uploads/project.zip"}
            result = self.run_generator(root, "prep", cfg)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            script = (root / ".build.sh").read_text()
            self.assertIn("if [ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]", script)
            self.assertNotIn("npm ci || npm install", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
