# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Property and unit tests for WorkItemTranslator.

Feature: houdini-pdg-support
Properties 1, 2, 3, 5, 6, 11: Translation behavior
"""

import pytest
from hypothesis import given, settings, assume

from deadline.client.job_bundle.submission import AssetReferences

from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.translator import (
    WorkItemTranslator,
    JobBundle,
)
from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.models import SchedulerConfig

from .conftest import (
    work_item_strategy,
    work_item_batch_strategy,
    MockWorkItem,
)


def make_translator():
    return WorkItemTranslator()


def make_config():
    return SchedulerConfig(
        farm_id="farm-123",
        queue_id="queue-456",
        job_name_prefix="TEST",
    )


class TestTranslationFidelity:
    """Property 1: Translation fidelity.

    For any PDG work item with a command, arguments, attributes, and environment variables,
    translating it to an OpenJD job bundle should produce a bundle where the step task command
    matches the work item command, the job parameters include all work item attributes, and
    the job environment includes all work item environment variables.

    Validates: Requirements 3.2, 3.3, 3.4
    """

    @settings(max_examples=100)
    @given(work_item=work_item_strategy())
    def test_command_preserved(self, work_item: MockWorkItem):
        """Work item command is preserved in the OpenJD step."""
        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch([work_item], "test_node", config)

        # Find the step with our command
        steps = bundle.template["steps"]
        assert len(steps) > 0

        # The command should appear in one of the steps
        commands = [step["script"]["actions"]["onRun"]["command"] for step in steps]
        assert work_item.command in commands

    @settings(max_examples=100)
    @given(work_item=work_item_strategy())
    def test_attributes_become_parameters(self, work_item: MockWorkItem):
        """Work item attributes are mapped to job parameters."""
        assume(len(work_item.attributes) > 0)

        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch([work_item], "test_node", config)

        # Check parameter definitions include attribute keys
        if "parameterDefinitions" in bundle.template:
            param_names = {p["name"] for p in bundle.template["parameterDefinitions"]}
            for attr_key in work_item.attributes.keys():
                assert attr_key in param_names

    @settings(max_examples=100)
    @given(work_item=work_item_strategy())
    def test_environment_preserved(self, work_item: MockWorkItem):
        """Work item environment variables are preserved in job environment."""
        assume(len(work_item.environment) > 0)

        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch([work_item], "test_node", config)

        # Check job environments
        if "jobEnvironments" in bundle.template:
            job_env = bundle.template["jobEnvironments"][0]["variables"]
            for key, value in work_item.environment.items():
                assert key in job_env
                assert job_env[key] == value


class TestHomogeneousWorkItemGrouping:
    """Property 2: Homogeneous work item grouping.

    For any set of work items from a single TOP node where all work items have the same command,
    the translator should produce a single OpenJD step containing one task per work item,
    with the task parameter space covering all work items.

    Validates: Requirements 3.5
    """

    @settings(max_examples=100)
    @given(work_items=work_item_batch_strategy(homogeneous=True, min_size=2, max_size=5))
    def test_homogeneous_items_single_step(self, work_items: list[MockWorkItem]):
        """Homogeneous work items produce a single step with parameter space."""
        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch(work_items, "test_node", config)

        # Should have exactly one step since all commands are the same
        assert len(bundle.template["steps"]) == 1

        step = bundle.template["steps"][0]

        # Should have a parameter space with all work item IDs
        assert "parameterSpace" in step
        task_params = step["parameterSpace"]["taskParameterDefinitions"]
        assert len(task_params) == 1
        assert task_params[0]["name"] == "WorkItemId"

        # All work item IDs should be in the range
        work_item_ids = {item.id for item in work_items}
        range_ids = set(task_params[0]["range"])
        assert work_item_ids == range_ids


class TestHeterogeneousWorkItemSplitting:
    """Property 3: Heterogeneous work item splitting.

    For any set of work items from a single TOP node where work items have different commands,
    the translator should produce separate OpenJD steps grouped by command.

    Validates: Requirements 3.6
    """

    @settings(max_examples=100)
    @given(work_items=work_item_batch_strategy(homogeneous=False, min_size=2, max_size=5))
    def test_heterogeneous_items_multiple_steps(self, work_items: list[MockWorkItem]):
        """Heterogeneous work items produce multiple steps grouped by command."""
        # Count unique commands
        unique_commands = set(item.command for item in work_items)
        assume(len(unique_commands) >= 2)

        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch(work_items, "test_node", config)

        # Should have one step per unique command
        assert len(bundle.template["steps"]) == len(unique_commands)

        # Each step should have a command from our set
        step_commands = {
            step["script"]["actions"]["onRun"]["command"] for step in bundle.template["steps"]
        }
        assert step_commands == unique_commands


class TestFileTagToAssetReferencesMapping:
    """Property 5: File tag to AssetReferences mapping.

    For any work item with input or output File_Tags, the translated OpenJD job bundle
    should contain a corresponding entry in AssetReferences for each file tag.

    Validates: Requirements 5.1, 5.2
    """

    @settings(max_examples=100)
    @given(work_item=work_item_strategy())
    def test_input_files_become_input_references(self, work_item: MockWorkItem):
        """Input file tags become input asset references."""
        assume(len(work_item.input_files) > 0)

        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch([work_item], "test_node", config)

        for input_file in work_item.input_files:
            if input_file:  # Skip empty strings
                assert input_file in bundle.asset_references.input_filenames

    @settings(max_examples=100)
    @given(work_item=work_item_strategy())
    def test_output_files_become_output_directories(self, work_item: MockWorkItem):
        """Output file tags result in output directory references."""
        assume(len(work_item.output_files) > 0)
        # Filter to files with valid directory paths
        valid_outputs = [f for f in work_item.output_files if f and "/" in f]
        assume(len(valid_outputs) > 0)

        translator = make_translator()
        config = make_config()
        bundle = translator.translate_batch([work_item], "test_node", config)

        import os

        for output_file in valid_outputs:
            output_dir = os.path.dirname(output_file)
            if output_dir:
                assert output_dir in bundle.asset_references.output_directories


class TestFileDeduplication:
    """Property 6: File deduplication.

    For any set of work items within a single batch where multiple work items reference
    the same file path, the translated job bundle should contain exactly one entry
    per unique file path.

    Validates: Requirements 5.4
    """

    def test_duplicate_input_files_deduplicated(self):
        """Duplicate input files across work items are deduplicated."""
        translator = make_translator()
        config = make_config()

        shared_file = "/shared/input.exr"
        items = [
            MockWorkItem(id=1, name="item1", input_files=[shared_file, "/unique1.exr"]),
            MockWorkItem(id=2, name="item2", input_files=[shared_file, "/unique2.exr"]),
            MockWorkItem(id=3, name="item3", input_files=[shared_file]),
        ]

        bundle = translator.translate_batch(items, "test_node", config)

        # shared_file should appear exactly once
        input_files = list(bundle.asset_references.input_filenames)
        assert input_files.count(shared_file) == 1

        # All unique files should be present
        assert "/unique1.exr" in input_files
        assert "/unique2.exr" in input_files

    def test_duplicate_output_dirs_deduplicated(self):
        """Duplicate output directories across work items are deduplicated."""
        translator = make_translator()
        config = make_config()

        items = [
            MockWorkItem(id=1, name="item1", output_files=["/output/frame.0001.exr"]),
            MockWorkItem(id=2, name="item2", output_files=["/output/frame.0002.exr"]),
            MockWorkItem(id=3, name="item3", output_files=["/output/frame.0003.exr"]),
        ]

        bundle = translator.translate_batch(items, "test_node", config)

        # /output should appear exactly once
        output_dirs = list(bundle.asset_references.output_directories)
        assert output_dirs.count("/output") == 1


class TestCrossJobFileWiring:
    """Property 11: Cross-job file wiring.

    For any completed upstream child job that produced output files, and any downstream
    work items that depend on those outputs, the translated job bundle for the downstream
    child job should include the upstream output files as input attachments.

    Validates: Requirements 5.3
    """

    def test_upstream_outputs_become_downstream_inputs(self):
        """Upstream output files are wired as downstream input references."""
        translator = make_translator()
        config = make_config()

        # Simulate upstream job outputs
        upstream_refs = AssetReferences()
        upstream_refs.input_filenames.add("/upstream/output.exr")
        upstream_refs.output_directories.add("/upstream")

        # Downstream work item
        downstream_item = MockWorkItem(
            id=10, name="downstream", input_files=["/downstream/local.exr"]
        )

        bundle = translator.translate_batch(
            [downstream_item], "downstream_node", config, upstream_asset_refs=upstream_refs
        )

        # Upstream files should be in downstream's input references
        assert "/upstream/output.exr" in bundle.asset_references.input_filenames
        # Downstream's own files should also be present
        assert "/downstream/local.exr" in bundle.asset_references.input_filenames


class TestTranslatorEdgeCases:
    """Unit tests for translator edge cases."""

    def test_empty_batch_raises_error(self):
        """Empty work item batch raises ValueError."""
        translator = make_translator()
        config = make_config()

        with pytest.raises(ValueError, match="Cannot translate empty"):
            translator.translate_batch([], "test_node", config)

    def test_single_item_no_parameter_space(self):
        """Single work item produces step without parameter space."""
        translator = make_translator()
        config = make_config()

        item = MockWorkItem(id=1, name="single", arguments=["-f", "1"])

        bundle = translator.translate_batch([item], "test_node", config)

        step = bundle.template["steps"][0]
        assert "parameterSpace" not in step
        assert step["script"]["actions"]["onRun"]["args"] == ["-f", "1"]

    def test_template_validation_catches_missing_fields(self):
        """Template validation catches missing required fields."""
        translator = make_translator()

        invalid_template = {"name": "test"}  # Missing specificationVersion and steps

        errors = translator.validate_template(invalid_template)

        assert len(errors) > 0
        assert any("specificationVersion" in e for e in errors)
        assert any("steps" in e for e in errors)

    def test_template_serialization_is_pretty(self):
        """Serialized template is pretty-printed JSON."""
        translator = make_translator()
        config = make_config()

        item = MockWorkItem(id=1, name="test")
        bundle = translator.translate_batch([item], "test_node", config)

        json_str = translator.serialize_template(bundle.template)

        assert "\n" in json_str
        assert "  " in json_str  # Indentation
