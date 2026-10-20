import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release import inspect_tar
from scripts.merge_release import content_fingerprint, digest, verify_bundle


class ReleaseArchiveTests(unittest.TestCase):
    def archive(self, directory, member_name, symlink=False):
        path = Path(directory) / "release.tar.gz"
        with tarfile.open(path, "w:gz") as stream:
            member = tarfile.TarInfo(member_name)
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "/outside"
                stream.addfile(member)
            else:
                member.size = 4
                stream.addfile(member, io.BytesIO(b"test"))
        return path

    def test_archive_rejects_private_and_proprietary_files(self):
        for name in ("root/server.jar", "root/.env.production", "root/jobs/state.json", "root/key.pem"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(RuntimeError):
                    inspect_tar(self.archive(directory, name), set())

    def test_archive_rejects_escape_paths_and_links(self):
        for name, symlink in (("../escape", False), ("root/../../escape", False), ("root/link", True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(RuntimeError):
                    inspect_tar(self.archive(directory, name, symlink), set())

    def test_archive_requires_complete_source_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.archive(directory, "root/LICENSE")
            self.assertEqual(inspect_tar(archive, {"LICENSE"}), "root")
            with self.assertRaises(RuntimeError):
                inspect_tar(archive, {"CMakeLists.txt"})


class ReleaseMergeTests(unittest.TestCase):
    def test_content_fingerprint_ignores_zip_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, year in enumerate((2020, 2026)):
                path = Path(directory) / f"package{index}.whl"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(zipfile.ZipInfo("package/code.py", (year, 1, 1, 0, 0, 0)), b"same content")
                paths.append(path)
            self.assertNotEqual(digest(paths[0]), digest(paths[1]))
            self.assertEqual(content_fingerprint(paths[0]), content_fingerprint(paths[1]))

    def test_merge_rejects_duplicate_archive_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for content in (b"one", b"two"):
                    member = tarfile.TarInfo("root/code.py")
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            with self.assertRaises(RuntimeError):
                content_fingerprint(path)

    def bundle(self, directory):
        root = Path(directory)
        artifacts = []
        for name in ("dreamseed-0.1.0-linux-x86_64.tar.gz", "dreamseed_mcp-0.1.0.tar.gz", "dreamseed_mcp-0.1.0-py3-none-any.whl"):
            path = root / name
            path.write_bytes(b"checksum test fixture")
            artifacts.append({"name": name, "sha256": digest(path), "size_bytes": path.stat().st_size})
        manifest = {
            "project": "DreamSeed", "version": "0.1.0", "minecraft_versions": ["1.21.1"],
            "git_revision": "a" * 40, "working_tree_dirty": False, "target": "linux-x86_64",
            "validation": {"source_rebuilt": True, "native_archive_search": True, "isolated_wheel_install": True,
                           "mcp": {"ok": True, "tools_tested": 9, "job_recovery": True}},
            "artifacts": artifacts,
        }
        path = root / "release-manifest-linux-x86_64.json"
        path.write_text(json.dumps(manifest))
        return path, manifest

    def test_merge_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.bundle(directory)
            (path.parent / manifest["artifacts"][0]["name"]).write_bytes(b"changed content")
            with self.assertRaises(RuntimeError):
                verify_bundle(path, "a" * 40)

    def test_merge_rejects_dirty_or_wrong_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.bundle(directory)
            with self.assertRaises(RuntimeError):
                verify_bundle(path, "b" * 40)
            manifest["working_tree_dirty"] = True
            path.write_text(json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                verify_bundle(path, "a" * 40)


if __name__ == "__main__":
    unittest.main()
