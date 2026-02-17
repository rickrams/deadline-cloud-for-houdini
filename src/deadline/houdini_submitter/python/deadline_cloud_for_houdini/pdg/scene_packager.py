# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Scene packager for collecting Houdini scene files and assets."""

import os
from typing import Optional

from deadline.client.job_bundle.submission import AssetReferences

from .models import PackageResult


class ScenePackager:
    """Collects scene files and assets for upload as job attachments."""

    def package(
        self,
        hip_file: str,
        top_network_path: str,
        scheduler_node_path: str,
        hou_module: Optional[object] = None,
    ) -> PackageResult:
        """Analyze the scene to find all referenced files.

        Args:
            hip_file: Path to the .hip scene file.
            top_network_path: The TOP network path within the scene.
            scheduler_node_path: The scheduler node path within the scene.
            hou_module: Optional hou module for testing (uses real hou if None).

        Returns:
            PackageResult with the file manifest and any warnings.

        Raises:
            FileNotFoundError: If the scene file doesn't exist.
            ValueError: If the scene file is unsaved.
        """
        # Validate scene file exists
        if not hip_file:
            raise ValueError("Scene file path is empty - scene may be unsaved")

        if not os.path.exists(hip_file):
            raise FileNotFoundError(f"Scene file not found: {hip_file}")

        # Check for unsaved scene (untitled.hip or similar)
        basename = os.path.basename(hip_file)
        if basename.startswith("untitled"):
            raise ValueError(f"Scene appears to be unsaved: {hip_file}")

        asset_refs = AssetReferences()
        warnings: list[str] = []

        # Add the hip file itself
        asset_refs.input_filenames.add(hip_file)

        # Collect referenced files using Houdini's file references API
        if hou_module is not None:
            self._collect_references_from_hou(hou_module, asset_refs, warnings)

        return PackageResult(
            hip_file=hip_file,
            top_network_path=top_network_path,
            scheduler_node_path=scheduler_node_path,
            asset_references=asset_refs,
            warnings=warnings,
        )

    def _collect_references_from_hou(
        self,
        hou_module: object,
        asset_refs: AssetReferences,
        warnings: list[str],
    ) -> None:
        """Collect file references using Houdini's API.

        Args:
            hou_module: The hou module.
            asset_refs: AssetReferences to populate.
            warnings: List to append warnings to.
        """
        try:
            # Get all file references from the scene
            file_refs = hou_module.fileReferences()  # type: ignore

            for parm, ref_path in file_refs:
                if not ref_path:
                    continue

                # Skip internal references
                if ref_path.startswith(("opdef:", "oplib:", "temp:", "op:")):
                    continue

                # Evaluate the path to resolve variables
                try:
                    if parm is not None:
                        evaluated_path = parm.eval()
                    else:
                        evaluated_path = ref_path
                except Exception:
                    evaluated_path = ref_path

                if not evaluated_path:
                    continue

                # Check if file exists
                if os.path.exists(evaluated_path):
                    if os.path.isdir(evaluated_path):
                        asset_refs.input_directories.add(evaluated_path)
                    else:
                        asset_refs.input_filenames.add(evaluated_path)
                else:
                    warnings.append(f"Referenced file not found: {evaluated_path}")

        except Exception as e:
            warnings.append(f"Error collecting file references: {e}")

    def package_from_node(
        self,
        scheduler_node: object,
        hou_module: object,
    ) -> PackageResult:
        """Package scene from a scheduler node.

        Args:
            scheduler_node: The Houdini scheduler node.
            hou_module: The hou module.

        Returns:
            PackageResult with the file manifest and any warnings.
        """
        hip_file = hou_module.hipFile.path()  # type: ignore
        top_network = scheduler_node.parent()  # type: ignore
        top_network_path = top_network.path() if top_network else ""  # type: ignore
        scheduler_node_path = scheduler_node.path()  # type: ignore

        return self.package(
            hip_file=hip_file,
            top_network_path=top_network_path,
            scheduler_node_path=scheduler_node_path,
            hou_module=hou_module,
        )
