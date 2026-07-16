import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class PlatformLayoutTests(unittest.TestCase):
    def test_uses_documented_plugin_discovery_paths(self):
        for relative_path in (
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            ".codex-plugin/plugin.json",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)
        self.assertFalse((ROOT / "adapters").exists())

    def test_claude_marketplace_references_the_repository_root_plugin(self):
        marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(marketplace["name"], "tavily-skill")
        self.assertEqual(
            marketplace["plugins"],
            [{"name": "tavily-skill", "source": "./"}],
        )

    def test_pi_manifest_does_not_load_a_static_skill_extension(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["pi"]["skills"], ["skills"])
        self.assertNotIn("extensions", package["pi"])

    def test_readme_only_claims_verified_installation_paths(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("claude plugin marketplace add goodmangll/tavily-skill", readme)
        self.assertIn("| Cursor | Not configured |", readme)
        self.assertNotIn("adapters/", readme)


if __name__ == "__main__":
    unittest.main()
