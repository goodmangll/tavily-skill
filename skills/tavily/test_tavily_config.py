import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("tavily.py")


def load_module():
    spec = importlib.util.spec_from_file_location("tavily_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class XdgConfigurationTests(unittest.TestCase):
    def test_loads_yaml_config_and_uses_xdg_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home = root / "config"
            state_home = root / "state"
            data_home = root / "data"
            config_file = config_home / "tavily" / "config.yaml"
            config_file.parent.mkdir(parents=True)
            config_file.write_text(
                "api_keys:\n  - first-key\n  - second-key\noutput_dir: ~/custom-results\n",
                encoding="utf-8",
            )

            environment = {
                "XDG_CONFIG_HOME": str(config_home),
                "XDG_STATE_HOME": str(state_home),
                "XDG_DATA_HOME": str(data_home),
            }
            with patch.dict(os.environ, environment, clear=True):
                tavily = load_module()
                self.assertEqual(tavily.load_keys(), ["first-key", "second-key"])
                self.assertEqual(tavily._state_file(), state_home / "tavily" / "state.json")
                self.assertEqual(tavily._output_dir(), Path("~/custom-results").expanduser())

    def test_uses_xdg_data_results_directory_when_output_dir_is_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home = root / "config"
            config_file = config_home / "tavily" / "config.yaml"
            config_file.parent.mkdir(parents=True)
            config_file.write_text("api_keys:\n  - a-key\n", encoding="utf-8")

            environment = {
                "XDG_CONFIG_HOME": str(config_home),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
            }
            with patch.dict(os.environ, environment, clear=True):
                tavily = load_module()
                self.assertEqual(tavily._output_dir(), root / "data" / "tavily" / "results")


if __name__ == "__main__":
    unittest.main()
