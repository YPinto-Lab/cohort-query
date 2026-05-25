"""Tests for notebook runner resilience in MappingConfigManager."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from managers.mapping_config_manager import MappingConfigManager


class TestMappingConfigManagerHeadless(unittest.TestCase):
    def test_run_does_not_raise_when_display_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "mapping_configs"
            config_dir.mkdir(parents=True, exist_ok=True)
            template_path = config_dir / "PRJTEST1.json.template"
            template_path.write_text(
                json.dumps(
                    {
                        "project_id": "PRJTEST1",
                        "view_name": "MockView",
                        "discovered_keys": {
                            "from_jattr": [],
                            "from_attributes": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            manager = MappingConfigManager(config_dir=config_dir)

            with patch("managers.mapping_config_manager.display", side_effect=RuntimeError("display unavailable")):
                manager.run()


if __name__ == "__main__":
    unittest.main()

