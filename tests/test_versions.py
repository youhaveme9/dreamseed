import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from dreamseed_mcp.minecraft_setup import configured_server_jar, eula_accepted, installation_status, record_acceptance
from dreamseed_mcp.schemas import InspectRequest
from dreamseed_mcp.versions import SUPPORTED_VERSIONS, get_version


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("DREAMSEED_BINARY", str(ROOT / "build/dreamseed")))


class VersionTests(unittest.TestCase):
    def test_explicit_version_catalog_matches_native_and_schemas(self):
        self.assertEqual(SUPPORTED_VERSIONS, ("1.21.1", "1.21.3"))
        capabilities = json.loads(subprocess.check_output([BINARY, "capabilities"], text=True))
        self.assertEqual(capabilities["minecraft_versions"], list(SUPPORTED_VERSIONS))
        self.assertEqual(InspectRequest.model_json_schema()["properties"]["minecraft_version"]["enum"], list(SUPPORTED_VERSIONS))
        self.assertEqual(get_version("1.21.1").data_version, 3955)
        self.assertEqual(get_version("1.21.3").data_version, 4082)

    def test_versions_are_selected_and_unlisted_aliases_rejected(self):
        for version in SUPPORTED_VERSIONS:
            request = {"minecraft_version": version, "seed": "262", "area": {"radius": 0}, "structures": []}
            result = subprocess.run([BINARY, "inspect", "--config", "-"], input=json.dumps(request), text=True, capture_output=True, check=True)
            inspected = json.loads(result.stdout)
            self.assertEqual(inspected["minecraft_version"], version)
            self.assertEqual(inspected["center_biome"], "mushroom_fields")
        for version in ("1.21", "1.21.2", "latest"):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                InspectRequest.model_validate({"minecraft_version": version, "seed": "0"})

    def test_eula_records_cannot_cross_versions(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"DREAMSEED_ACCEPT_MOJANG_EULA": ""}):
            jar = Path(temporary) / "server.jar"
            record_acceptance(jar, "1.21.3")
            self.assertTrue(eula_accepted(jar, "1.21.3"))
            self.assertFalse(eula_accepted(jar, "1.21.1"))

    def test_mismatched_official_jar_cannot_be_used_for_another_version(self):
        original_jar = configured_server_jar("1.21.1")
        if not original_jar.exists():
            with tempfile.TemporaryDirectory() as temporary:
                wrong = Path(temporary) / "wrong.jar"
                wrong.write_bytes(b"wrong version fixture")
                with patch.dict(os.environ, {"DREAMSEED_MINECRAFT_SERVER_JAR": str(wrong)}):
                    self.assertFalse(installation_status(True, "1.21.3")["available"])
            return
        with patch.dict(os.environ, {"DREAMSEED_MINECRAFT_SERVER_JAR": str(original_jar)}):
            status = installation_status(True, "1.21.3")
            self.assertFalse(status["available"])
            self.assertFalse(status["size_ok"])


if __name__ == "__main__":
    unittest.main()
