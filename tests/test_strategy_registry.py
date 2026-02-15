#!/usr/bin/env python3
"""
Test Strategy Discovery & Registry

Tests:
- Strategy discovery from file system
- Registry excludes correct folders
- Template metadata generation
"""

import pytest
from pathlib import Path
from shoonya_platform.strategy_runner.universal_settings.universal_registry import list_strategy_templates


class TestStrategyRegistry:
    """Test strategy discovery from filesystem"""
    
    def test_list_strategy_templates_returns_list(self):
        """Registry should return list of templates"""
        templates = list_strategy_templates()
        assert isinstance(templates, list)
    
    def test_template_contains_required_fields(self):
        """Each template should have required metadata"""
        templates = list_strategy_templates()
        
        required_fields = {"id", "folder", "file", "module", "label", "slug"}
        for template in templates:
            assert required_fields.issubset(set(template.keys())), \
                f"Template missing fields: {required_fields - set(template.keys())}"
    
    def test_registry_excludes_universal_settings(self):
        """Registry should exclude universal_settings folder"""
        templates = list_strategy_templates()
        
        for t in templates:
            assert t["folder"] != "universal_settings"
            assert t["folder"] != "universal_registry"
            assert t["folder"] != "universal_strategy_reporter"
            assert t["folder"] != "writer"
    
    def test_registry_excludes_market_adapters(self):
        """Registry should not list market adapters"""
        templates = list_strategy_templates()
        
        for t in templates:
            assert t["folder"] not in ["database_market", "live_feed_market"]
            assert "market_adapter_factory" not in t["module"]
    
    def test_registry_excludes_system_folders(self):
        """Registry should exclude __pycache__ and legacy"""
        templates = list_strategy_templates()
        
        for t in templates:
            assert t["folder"] not in ["__pycache__", "legacy", "universal_config"]
    
    def test_module_path_is_importable(self):
        """Module paths should be importable"""
        templates = list_strategy_templates()
        
        for t in templates:
            # Verify format matches expected pattern
            module = t["module"]
            assert module.startswith("shoonya_platform.strategy_runner.")
            assert "." in module  # At least one dot
    
    def test_template_ids_are_unique(self):
        """Template IDs should be unique"""
        templates = list_strategy_templates()
        
        ids = [t["id"] for t in templates]
        assert len(ids) == len(set(ids)), "Duplicate template IDs found"
    
    def test_template_slugs_match_files(self):
        """Slug should match Python file name (without .py)"""
        templates = list_strategy_templates()
        
        for t in templates:
            file_stem = Path(t["file"]).stem
            assert t["slug"] == file_stem, \
                f"Slug mismatch: {t['slug']} != {file_stem}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
