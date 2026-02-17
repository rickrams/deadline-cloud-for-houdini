# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Property and unit tests for ScenePackager.

Feature: houdini-pdg-support
Property 13: Scene packaging completeness
"""

import os
import tempfile
from unittest.mock import MagicMock, Mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.scene_packager import (
    ScenePackager,
)


def make_packager():
    return ScenePackager()


class TestScenePackagingCompleteness:
    """Property 13: Scene packaging completeness.

    For any Houdini scene file with a set of referenced assets (textures, caches, HDAs),
    the ScenePackager should produce a PackageResult whose referenced files contain
    every file referenced by the scene.

    Validates: Requirements 2.2
    """

    @settings(max_examples=50)
    @given(
        num_refs=st.integers(min_value=0, max_value=10),
        num_missing=st.integers(min_value=0, max_value=3),
    )
    def test_all_existing_references_collected(self, num_refs: int, num_missing: int):
        """All existing file references are collected in asset_references."""
        packager = make_packager()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake hip file
            hip_file = os.path.join(tmpdir, "test_scene.hip")
            with open(hip_file, "w") as f:
                f.write("fake hip content")

            # Create referenced files
            existing_files = []
            for i in range(num_refs):
                ref_file = os.path.join(tmpdir, f"texture_{i}.exr")
                with open(ref_file, "w") as f:
                    f.write(f"texture {i}")
                existing_files.append(ref_file)

            # Create mock hou module with file references
            mock_hou = MagicMock()
            mock_refs = []
            for ref_file in existing_files:
                mock_parm = MagicMock()
                mock_parm.eval.return_value = ref_file
                mock_refs.append((mock_parm, ref_file))

            # Add some missing file references
            for i in range(num_missing):
                mock_parm = MagicMock()
                missing_path = f"/nonexistent/missing_{i}.exr"
                mock_parm.eval.return_value = missing_path
                mock_refs.append((mock_parm, missing_path))

            mock_hou.fileReferences.return_value = mock_refs

            # Package the scene
            result = packager.package(
                hip_file=hip_file,
                top_network_path="/obj/topnet1",
                scheduler_node_path="/obj/topnet1/scheduler1",
                hou_module=mock_hou,
            )

            # Verify all existing files are in input_filenames
            for ref_file in existing_files:
                assert ref_file in result.asset_references.input_filenames

            # Verify hip file is included
            assert hip_file in result.asset_references.input_filenames

            # Verify warnings for missing files
            assert len(result.warnings) == num_missing


class TestScenePackagerValidation:
    """Unit tests for scene validation.

    Validates: Requirements 2.5
    """

    def test_missing_scene_file_raises_error(self):
        """Missing scene file raises FileNotFoundError."""
        packager = make_packager()

        with pytest.raises(FileNotFoundError, match="Scene file not found"):
            packager.package(
                hip_file="/nonexistent/scene.hip",
                top_network_path="/obj/topnet1",
                scheduler_node_path="/obj/topnet1/scheduler1",
            )

    def test_empty_scene_path_raises_error(self):
        """Empty scene path raises ValueError."""
        packager = make_packager()

        with pytest.raises(ValueError, match="empty"):
            packager.package(
                hip_file="",
                top_network_path="/obj/topnet1",
                scheduler_node_path="/obj/topnet1/scheduler1",
            )

    def test_unsaved_scene_raises_error(self):
        """Unsaved scene (untitled) raises ValueError."""
        packager = make_packager()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file that looks like an unsaved scene
            hip_file = os.path.join(tmpdir, "untitled.hip")
            with open(hip_file, "w") as f:
                f.write("fake")

            with pytest.raises(ValueError, match="unsaved"):
                packager.package(
                    hip_file=hip_file,
                    top_network_path="/obj/topnet1",
                    scheduler_node_path="/obj/topnet1/scheduler1",
                )

    def test_valid_scene_packages_successfully(self):
        """Valid scene file packages without error."""
        packager = make_packager()

        with tempfile.TemporaryDirectory() as tmpdir:
            hip_file = os.path.join(tmpdir, "my_scene.hip")
            with open(hip_file, "w") as f:
                f.write("fake hip content")

            result = packager.package(
                hip_file=hip_file,
                top_network_path="/obj/topnet1",
                scheduler_node_path="/obj/topnet1/scheduler1",
            )

            assert result.hip_file == hip_file
            assert result.top_network_path == "/obj/topnet1"
            assert result.scheduler_node_path == "/obj/topnet1/scheduler1"
            assert hip_file in result.asset_references.input_filenames

    def test_skips_internal_references(self):
        """Internal references (opdef:, oplib:, etc.) are skipped."""
        packager = make_packager()

        with tempfile.TemporaryDirectory() as tmpdir:
            hip_file = os.path.join(tmpdir, "test_scene.hip")
            with open(hip_file, "w") as f:
                f.write("fake")

            # Mock hou with internal references
            mock_hou = MagicMock()
            mock_hou.fileReferences.return_value = [
                (None, "opdef:/Sop/box"),
                (None, "oplib:/path/to/hda"),
                (None, "temp:/tmp/cache"),
                (None, "op:/obj/geo1"),
            ]

            result = packager.package(
                hip_file=hip_file,
                top_network_path="/obj/topnet1",
                scheduler_node_path="/obj/topnet1/scheduler1",
                hou_module=mock_hou,
            )

            # Only the hip file should be in references (internal refs skipped)
            assert len(result.asset_references.input_filenames) == 1
            assert hip_file in result.asset_references.input_filenames

    def test_directories_added_to_input_directories(self):
        """Directory references are added to input_directories."""
        packager = make_packager()

        with tempfile.TemporaryDirectory() as tmpdir:
            hip_file = os.path.join(tmpdir, "test_scene.hip")
            with open(hip_file, "w") as f:
                f.write("fake")

            # Create a referenced directory
            ref_dir = os.path.join(tmpdir, "textures")
            os.makedirs(ref_dir)

            mock_hou = MagicMock()
            mock_parm = MagicMock()
            mock_parm.eval.return_value = ref_dir
            mock_hou.fileReferences.return_value = [(mock_parm, ref_dir)]

            result = packager.package(
                hip_file=hip_file,
                top_network_path="/obj/topnet1",
                scheduler_node_path="/obj/topnet1/scheduler1",
                hou_module=mock_hou,
            )

            assert ref_dir in result.asset_references.input_directories
