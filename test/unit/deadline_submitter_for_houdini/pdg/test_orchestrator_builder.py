# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Unit tests for OrchestratorJobBuilder.

Validates: Requirements 2.1, 2.3, 2.4
"""

import os
import tempfile

import yaml

from deadline.client.job_bundle.submission import AssetReferences

from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.orchestrator_builder import (
    OrchestratorJobBuilder,
)
from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.models import (
    PackageResult,
    SchedulerConfig,
)
from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.constants import (
    DEADLINE_CLOUD_PDG_ORCHESTRATOR,
)


def make_builder():
    return OrchestratorJobBuilder()


def make_config():
    return SchedulerConfig(
        farm_id="farm-12345",
        queue_id="queue-67890",
        priority=50,
        job_name_prefix="TestPDG",
        job_description="Test orchestrator job",
        max_concurrent_jobs=5,
        poll_interval=15,
    )


def make_package():
    asset_refs = AssetReferences()
    asset_refs.input_filenames.add("/path/to/scene.hip")
    asset_refs.input_filenames.add("/path/to/texture.exr")
    asset_refs.input_directories.add("/path/to/textures")

    return PackageResult(
        hip_file="/path/to/scene.hip",
        top_network_path="/obj/topnet1",
        scheduler_node_path="/obj/topnet1/deadline_scheduler",
        asset_references=asset_refs,
        warnings=[],
    )


class TestOrchestratorJobBuilder:
    """Unit tests for OrchestratorJobBuilder."""

    def test_template_includes_orchestrator_env_var(self):
        """Template includes DEADLINE_CLOUD_PDG_ORCHESTRATOR environment variable."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        template = builder.build(config, package)

        # Check job environments
        assert "jobEnvironments" in template
        env_found = False
        for env in template["jobEnvironments"]:
            if "variables" in env and DEADLINE_CLOUD_PDG_ORCHESTRATOR in env["variables"]:
                assert env["variables"][DEADLINE_CLOUD_PDG_ORCHESTRATOR] == "1"
                env_found = True
                break
        assert env_found, f"Environment variable {DEADLINE_CLOUD_PDG_ORCHESTRATOR} not found"

    def test_template_includes_top_network_and_scheduler_params(self):
        """Template includes TOP network path and scheduler path as parameters."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        template = builder.build(config, package)

        # Check parameter definitions
        param_names = {p["name"] for p in template["parameterDefinitions"]}
        assert "TopNetworkPath" in param_names
        assert "SchedulerNodePath" in param_names
        assert "HipFile" in param_names

        # Check default values
        for param in template["parameterDefinitions"]:
            if param["name"] == "TopNetworkPath":
                assert param["default"] == "/obj/topnet1"
            elif param["name"] == "SchedulerNodePath":
                assert param["default"] == "/obj/topnet1/deadline_scheduler"
            elif param["name"] == "HipFile":
                assert param["default"] == "/path/to/scene.hip"

    def test_template_has_valid_structure(self):
        """Template has valid OpenJD structure."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        template = builder.build(config, package)

        # Check required fields
        assert template["specificationVersion"] == "jobtemplate-2023-09"
        assert "name" in template
        assert "steps" in template
        assert len(template["steps"]) == 1

        # Check step structure
        step = template["steps"][0]
        assert step["name"] == "Orchestrate"
        assert "script" in step
        assert "actions" in step["script"]
        assert "onRun" in step["script"]["actions"]
        assert step["script"]["actions"]["onRun"]["command"] == "hython"

    def test_template_step_uses_param_references(self):
        """Step command uses parameter references for paths."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        template = builder.build(config, package)

        step = template["steps"][0]
        args = step["script"]["actions"]["onRun"]["args"]

        # Check that args contain parameter references
        assert "{{Param.HipFile}}" in args
        assert "{{Param.TopNetworkPath}}" in args
        assert "{{Param.SchedulerNodePath}}" in args

    def test_write_bundle_creates_all_files(self):
        """write_bundle creates template.yaml, parameter_values.yaml, and asset_references.yaml."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = os.path.join(tmpdir, "bundle")
            builder.write_bundle(config, package, bundle_dir)

            # Check files exist
            assert os.path.exists(os.path.join(bundle_dir, "template.yaml"))
            assert os.path.exists(os.path.join(bundle_dir, "parameter_values.yaml"))
            assert os.path.exists(os.path.join(bundle_dir, "asset_references.yaml"))

            # Verify template.yaml content
            with open(os.path.join(bundle_dir, "template.yaml")) as f:
                template = yaml.safe_load(f)
            assert template["specificationVersion"] == "jobtemplate-2023-09"

            # Verify parameter_values.yaml content
            with open(os.path.join(bundle_dir, "parameter_values.yaml")) as f:
                params = yaml.safe_load(f)
            param_dict = {p["name"]: p["value"] for p in params["parameterValues"]}
            assert param_dict["HipFile"] == "/path/to/scene.hip"
            assert param_dict["TopNetworkPath"] == "/obj/topnet1"

            # Verify asset_references.yaml content
            with open(os.path.join(bundle_dir, "asset_references.yaml")) as f:
                refs = yaml.safe_load(f)
            assert "/path/to/scene.hip" in refs["assetReferences"]["inputs"]["filenames"]

    def test_job_name_uses_prefix(self):
        """Job name uses the configured prefix."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        template = builder.build(config, package)

        assert template["name"].startswith("TestPDG")
        assert "Orchestrator" in template["name"]

    def test_config_values_in_parameters(self):
        """Config values are included in parameter definitions."""
        builder = make_builder()
        config = make_config()
        package = make_package()

        template = builder.build(config, package)

        param_dict = {p["name"]: p["default"] for p in template["parameterDefinitions"]}
        assert param_dict["FarmId"] == "farm-12345"
        assert param_dict["QueueId"] == "queue-67890"
        assert param_dict["MaxConcurrentJobs"] == 5
        assert param_dict["PollInterval"] == 15
