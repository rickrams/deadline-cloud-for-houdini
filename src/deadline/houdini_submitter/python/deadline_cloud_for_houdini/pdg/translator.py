# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Translator for converting PDG work items to OpenJD job bundles."""

import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import yaml

from deadline.client.job_bundle.submission import AssetReferences

from .models import SchedulerConfig


class WorkItemProtocol(Protocol):
    """Protocol for PDG work item interface."""

    id: int
    name: str
    command: str
    arguments: list[str]
    environment: dict[str, str]
    attributes: dict[str, str]
    input_files: list[str]
    output_files: list[str]


@dataclass
class JobBundle:
    """An OpenJD job bundle ready for submission."""

    template: dict[str, Any]
    asset_references: AssetReferences = field(default_factory=AssetReferences)
    parameters: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the template to pretty-printed JSON."""
        return json.dumps(self.template, indent=2)


class WorkItemTranslator:
    """Translates PDG work items into OpenJD job bundles."""

    def translate_batch(
        self,
        work_items: list[WorkItemProtocol],
        top_node_name: str,
        config: SchedulerConfig,
        upstream_asset_refs: Optional[AssetReferences] = None,
    ) -> JobBundle:
        """Translate a batch of work items from a single TOP node into an OpenJD job bundle.

        Homogeneous work items (same command) are grouped into a single step with a
        task parameter space. Heterogeneous work items are split into separate steps.
        """
        if not work_items:
            raise ValueError("Cannot translate empty work item batch")

        template = self.build_template_dict(work_items, top_node_name, config)
        asset_refs = self._build_asset_references(work_items, upstream_asset_refs)
        parameters = self._build_parameters(work_items)

        return JobBundle(template=template, asset_references=asset_refs, parameters=parameters)

    def build_template_dict(
        self,
        work_items: list[WorkItemProtocol],
        top_node_name: str,
        config: SchedulerConfig,
    ) -> dict[str, Any]:
        """Build an OpenJD job template dict from work items."""
        # Group work items by command (executable)
        groups = self._group_by_command(work_items)

        steps = []
        for command, items in groups.items():
            step = self._build_step(command, items, top_node_name)
            steps.append(step)

        # Build job-level environment from all work items
        job_env = self._merge_environments(work_items)

        template: dict[str, Any] = {
            "specificationVersion": "jobtemplate-2023-09",
            "name": f"{config.job_name_prefix}_{top_node_name}",
            "steps": steps,
        }

        if job_env:
            template["jobEnvironments"] = [{"name": "PDGEnvironment", "variables": job_env}]

        # Add job parameters from work item attributes
        params = self._build_job_parameters(work_items)
        if params:
            template["parameterDefinitions"] = params

        return template

    def _group_by_command(
        self, work_items: list[WorkItemProtocol]
    ) -> dict[str, list[WorkItemProtocol]]:
        """Group work items by their command executable."""
        groups: dict[str, list[WorkItemProtocol]] = defaultdict(list)
        for item in work_items:
            groups[item.command].append(item)
        return dict(groups)

    def _build_step(
        self, command: str, items: list[WorkItemProtocol], top_node_name: str
    ) -> dict[str, Any]:
        """Build an OpenJD step for a group of work items with the same command."""
        step_name = f"{top_node_name}_{command.replace('/', '_').replace('.', '_')}"

        # Build task parameter space if multiple items
        if len(items) > 1:
            step: dict[str, Any] = {
                "name": step_name,
                "parameterSpace": {
                    "taskParameterDefinitions": [
                        {"name": "WorkItemId", "type": "INT", "range": [item.id for item in items]}
                    ]
                },
                "script": {
                    "actions": {
                        "onRun": {
                            "command": command,
                            "args": ["{{Task.Param.WorkItemId}}"],
                        }
                    }
                },
            }
        else:
            item = items[0]
            step = {
                "name": step_name,
                "script": {
                    "actions": {
                        "onRun": {
                            "command": command,
                            "args": item.arguments if item.arguments else [],
                        }
                    }
                },
            }

        return step

    def _merge_environments(self, work_items: list[WorkItemProtocol]) -> dict[str, str]:
        """Merge environment variables from all work items."""
        merged: dict[str, str] = {}
        for item in work_items:
            merged.update(item.environment)
        return merged

    def _build_job_parameters(self, work_items: list[WorkItemProtocol]) -> list[dict[str, Any]]:
        """Build job parameter definitions from work item attributes."""
        # Collect all unique attribute keys
        all_keys: set[str] = set()
        for item in work_items:
            all_keys.update(item.attributes.keys())

        params = []
        for key in sorted(all_keys):
            params.append({"name": key, "type": "STRING"})
        return params

    def _build_parameters(self, work_items: list[WorkItemProtocol]) -> dict[str, str]:
        """Build parameter values from work item attributes."""
        # Use first work item's attributes as representative
        if work_items:
            return dict(work_items[0].attributes)
        return {}

    def _build_asset_references(
        self,
        work_items: list[WorkItemProtocol],
        upstream_asset_refs: Optional[AssetReferences] = None,
    ) -> AssetReferences:
        """Build asset references from work item file tags."""
        refs = AssetReferences()

        # Add upstream asset references if provided
        if upstream_asset_refs:
            refs.input_filenames.update(upstream_asset_refs.input_filenames)
            refs.input_directories.update(upstream_asset_refs.input_directories)
            refs.output_directories.update(upstream_asset_refs.output_directories)
            refs.referenced_paths.update(upstream_asset_refs.referenced_paths)

        # Deduplicate files across work items
        seen_inputs: set[str] = set()
        seen_outputs: set[str] = set()

        for item in work_items:
            for f in item.input_files:
                if f and f not in seen_inputs:
                    seen_inputs.add(f)
                    refs.input_filenames.add(f)
            for f in item.output_files:
                if f and f not in seen_outputs:
                    seen_outputs.add(f)
                    # Output files go to output directories (parent dir)
                    output_dir = os.path.dirname(f)
                    if output_dir:
                        refs.output_directories.add(output_dir)

        return refs

    def serialize_template(self, template: dict[str, Any]) -> str:
        """Serialize a template dict to pretty-printed JSON."""
        return json.dumps(template, indent=2)

    def validate_template(self, template: dict[str, Any]) -> list[str]:
        """Validate a template dict against the OpenJD schema.

        Returns a list of validation error messages (empty if valid).
        """
        errors = []

        # Basic structural validation
        if "specificationVersion" not in template:
            errors.append("Missing required field: specificationVersion")
        elif template["specificationVersion"] != "jobtemplate-2023-09":
            errors.append(f"Unsupported specificationVersion: {template['specificationVersion']}")

        if "name" not in template:
            errors.append("Missing required field: name")

        if "steps" not in template:
            errors.append("Missing required field: steps")
        elif not isinstance(template["steps"], list) or len(template["steps"]) == 0:
            errors.append("steps must be a non-empty list")

        # Try openjd validation if available
        try:
            from openjd.model import decode_job_template

            decode_job_template(template=template)
        except ImportError:
            pass  # openjd not available, skip deep validation
        except Exception as e:
            errors.append(f"OpenJD validation error: {e}")

        return errors

    def write_bundle_to_dir(self, bundle: JobBundle, bundle_dir: str) -> None:
        """Write a job bundle to a directory."""
        # Write template.yaml
        template_path = os.path.join(bundle_dir, "template.yaml")
        with open(template_path, "w") as f:
            yaml.dump(bundle.template, f, default_flow_style=False)

        # Write parameter_values.yaml if there are parameters
        if bundle.parameters:
            params_path = os.path.join(bundle_dir, "parameter_values.yaml")
            param_values = [{"name": k, "value": v} for k, v in bundle.parameters.items()]
            with open(params_path, "w") as f:
                yaml.dump({"parameterValues": param_values}, f, default_flow_style=False)

        # Write asset_references.yaml
        refs_path = os.path.join(bundle_dir, "asset_references.yaml")
        refs_dict = {
            "assetReferences": {
                "inputs": {
                    "filenames": list(bundle.asset_references.input_filenames),
                    "directories": list(bundle.asset_references.input_directories),
                },
                "outputs": {"directories": list(bundle.asset_references.output_directories)},
                "referencedPaths": list(bundle.asset_references.referenced_paths),
            }
        }
        with open(refs_path, "w") as f:
            yaml.dump(refs_dict, f, default_flow_style=False)
