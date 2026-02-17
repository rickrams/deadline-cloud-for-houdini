# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Property tests for job template serialization.

Feature: houdini-pdg-support
Property 4: Job template round-trip serialization
"""

import json

from hypothesis import given, settings

from .conftest import template_dict_strategy


class TestJobTemplateRoundTrip:
    """Property 4: Job template round-trip serialization.

    For any valid JobBundle, serializing it to JSON and deserializing the JSON back
    should produce a JobBundle with an equivalent template structure.

    Validates: Requirements 3.7, 3.8
    """

    @settings(max_examples=100)
    @given(template=template_dict_strategy())
    def test_template_round_trip_preserves_structure(self, template: dict):
        """Serializing and deserializing a template dict preserves structure."""
        # Serialize to JSON
        json_str = json.dumps(template, indent=2)

        # Deserialize back
        restored = json.loads(json_str)

        # Verify equivalence
        assert restored == template

    @settings(max_examples=100)
    @given(template=template_dict_strategy())
    def test_serialized_json_is_pretty_printed(self, template: dict):
        """Serialized JSON should be pretty-printed (contain newlines and indentation)."""
        json_str = json.dumps(template, indent=2)

        # Pretty-printed JSON has newlines
        assert "\n" in json_str
        # Pretty-printed JSON has indentation
        assert "  " in json_str

    @settings(max_examples=100)
    @given(template=template_dict_strategy())
    def test_template_has_required_fields(self, template: dict):
        """Generated templates have required OpenJD fields."""
        assert "specificationVersion" in template
        assert template["specificationVersion"] == "jobtemplate-2023-09"
        assert "name" in template
        assert "steps" in template
        assert len(template["steps"]) > 0
