"""Compatibility shim for the split setting templates package."""

from .setting_templates_pkg import (
    HIERARCHY_DEFAULTS,
    SETTING_TEMPLATES,
    build_project_settings_summary,
    extract_relevant_categories_from_text,
    get_hierarchy_config_json,
    get_templates_metadata,
)

__all__ = [
    "HIERARCHY_DEFAULTS",
    "SETTING_TEMPLATES",
    "build_project_settings_summary",
    "extract_relevant_categories_from_text",
    "get_hierarchy_config_json",
    "get_templates_metadata",
]
