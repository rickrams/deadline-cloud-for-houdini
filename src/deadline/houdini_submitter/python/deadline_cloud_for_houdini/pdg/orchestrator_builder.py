# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Builder for the orchestrator job bundle."""

import os
from typing import Any

import yaml

from .constants import DEADLINE_CLOUD_PDG_ORCHESTRATOR
from .models import PackageResult, SchedulerConfig


class OrchestratorJobBuilder:
    """Builds the OpenJD job bundle for the orchestrator job."""

    def build(self, config: SchedulerConfig, package: PackageResult) -> dict[str, Any]:
        """Create an OpenJD job template for the orchestrator.

        The job has a single step that runs the orchestrator script
        in a headless Houdini session.

        Args:
            config: Scheduler configuration from the node parameters.
            package: The packaged scene files and manifest.

        Returns:
            A dict representing the OpenJD job template.
        """
        template: dict[str, Any] = {
            "specificationVersion": "jobtemplate-2023-09",
            "name": f"{config.job_name_prefix}_Orchestrator",
            "description": config.job_description or "PDG Orchestrator Job",
            "parameterDefinitions": [
                {
                    "name": "HipFile",
                    "type": "PATH",
                    "objectType": "FILE",
                    "dataFlow": "IN",
                    "default": package.hip_file,
                },
                {
                    "name": "TopNetworkPath",
                    "type": "STRING",
                    "default": package.top_network_path,
                },
                {
                    "name": "SchedulerNodePath",
                    "type": "STRING",
                    "default": package.scheduler_node_path,
                },
                {
                    "name": "FarmId",
                    "type": "STRING",
                    "default": config.farm_id,
                },
                {
                    "name": "QueueId",
                    "type": "STRING",
                    "default": config.queue_id,
                },
                {
                    "name": "MaxConcurrentJobs",
                    "type": "INT",
                    "default": config.max_concurrent_jobs,
                },
                {
                    "name": "PollInterval",
                    "type": "INT",
                    "default": config.poll_interval,
                },
            ],
            "jobEnvironments": [
                {
                    "name": "PDGOrchestratorEnv",
                    "variables": {
                        DEADLINE_CLOUD_PDG_ORCHESTRATOR: "1",
                    },
                }
            ],
            "steps": [
                {
                    "name": "Orchestrate",
                    "script": {
                        "actions": {
                            "onRun": {
                                "command": "hython",
                                "args": [
                                    "-m",
                                    "deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.orchestrator_main",
                                    "--hip-file",
                                    "{{Param.HipFile}}",
                                    "--top-network",
                                    "{{Param.TopNetworkPath}}",
                                    "--scheduler-node",
                                    "{{Param.SchedulerNodePath}}",
                                    "--farm-id",
                                    "{{Param.FarmId}}",
                                    "--queue-id",
                                    "{{Param.QueueId}}",
                                    "--max-concurrent-jobs",
                                    "{{Param.MaxConcurrentJobs}}",
                                    "--poll-interval",
                                    "{{Param.PollInterval}}",
                                ],
                            }
                        }
                    },
                }
            ],
        }

        return template

    def write_bundle(self, config: SchedulerConfig, package: PackageResult, bundle_dir: str) -> str:
        """Write the orchestrator job bundle to a directory.

        Args:
            config: Scheduler configuration.
            package: The packaged scene files.
            bundle_dir: Directory to write the bundle to.

        Returns:
            Path to the bundle directory.
        """
        os.makedirs(bundle_dir, exist_ok=True)

        # Write template.yaml
        template = self.build(config, package)
        template_path = os.path.join(bundle_dir, "template.yaml")
        with open(template_path, "w") as f:
            yaml.dump(template, f, default_flow_style=False)

        # Write parameter_values.yaml
        param_values = {
            "parameterValues": [
                {"name": "HipFile", "value": package.hip_file},
                {"name": "TopNetworkPath", "value": package.top_network_path},
                {"name": "SchedulerNodePath", "value": package.scheduler_node_path},
                {"name": "FarmId", "value": config.farm_id},
                {"name": "QueueId", "value": config.queue_id},
                {"name": "MaxConcurrentJobs", "value": config.max_concurrent_jobs},
                {"name": "PollInterval", "value": config.poll_interval},
            ]
        }
        params_path = os.path.join(bundle_dir, "parameter_values.yaml")
        with open(params_path, "w") as f:
            yaml.dump(param_values, f, default_flow_style=False)

        # Write asset_references.yaml
        refs_dict = {
            "assetReferences": {
                "inputs": {
                    "filenames": list(package.asset_references.input_filenames),
                    "directories": list(package.asset_references.input_directories),
                },
                "outputs": {
                    "directories": list(package.asset_references.output_directories),
                },
                "referencedPaths": list(package.asset_references.referenced_paths),
            }
        }
        refs_path = os.path.join(bundle_dir, "asset_references.yaml")
        with open(refs_path, "w") as f:
            yaml.dump(refs_dict, f, default_flow_style=False)

        return bundle_dir
