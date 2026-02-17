# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Pytest fixtures and Hypothesis strategies for PDG tests."""

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock

import pytest
from hypothesis import strategies as st

from deadline.client.job_bundle.submission import AssetReferences


# Mock PDG work item for testing
@dataclass
class MockWorkItem:
    """Mock PDG work item for testing without Houdini."""

    id: int
    name: str = ""
    command: str = "/usr/bin/render"
    arguments: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    upstream_ids: set[int] = field(default_factory=set)


# Hypothesis strategies
@st.composite
def work_item_strategy(draw, min_id=0, max_id=1000):
    """Generate a mock PDG work item."""
    work_item_id = draw(st.integers(min_value=min_id, max_value=max_id))
    name = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=20))
    command = draw(
        st.sampled_from(["/usr/bin/render", "/usr/bin/hython", "/usr/bin/mantra", "python"])
    )
    arguments = draw(st.lists(st.text(min_size=1, max_size=50), max_size=5))
    environment = draw(
        st.dictionaries(
            st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1, max_size=20),
            st.text(min_size=0, max_size=50),
            max_size=5,
        )
    )
    attributes = draw(
        st.dictionaries(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=20),
            st.text(min_size=0, max_size=50),
            max_size=5,
        )
    )
    input_files = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz/._0123456789", min_size=5, max_size=50),
            max_size=3,
        )
    )
    output_files = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz/._0123456789", min_size=5, max_size=50),
            max_size=3,
        )
    )

    return MockWorkItem(
        id=work_item_id,
        name=name,
        command=command,
        arguments=arguments,
        environment=environment,
        attributes=attributes,
        input_files=input_files,
        output_files=output_files,
    )


@st.composite
def work_item_batch_strategy(draw, homogeneous=None, min_size=1, max_size=10):
    """Generate a batch of work items, optionally homogeneous (same command)."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))

    if homogeneous is True:
        # All items have the same command
        command = draw(
            st.sampled_from(["/usr/bin/render", "/usr/bin/hython", "/usr/bin/mantra", "python"])
        )
        items = []
        for i in range(size):
            item = draw(work_item_strategy(min_id=i * 100, max_id=i * 100 + 99))
            item.command = command
            items.append(item)
        return items
    elif homogeneous is False:
        # Items have different commands (at least 2 different)
        commands = ["/usr/bin/render", "/usr/bin/hython", "/usr/bin/mantra", "python"]
        items = []
        for i in range(size):
            item = draw(work_item_strategy(min_id=i * 100, max_id=i * 100 + 99))
            item.command = commands[i % len(commands)]
            items.append(item)
        # Ensure at least 2 different commands if size > 1
        if size > 1 and len(set(item.command for item in items)) < 2:
            items[1].command = commands[(commands.index(items[0].command) + 1) % len(commands)]
        return items
    else:
        # Random mix
        return draw(st.lists(work_item_strategy(), min_size=min_size, max_size=max_size))


@st.composite
def dag_strategy(draw, min_nodes=1, max_nodes=20, max_depth=5):
    """Generate a random DAG of work item dependencies.

    Returns a list of (work_item_id, upstream_ids) tuples representing a valid DAG.
    """
    num_nodes = draw(st.integers(min_value=min_nodes, max_value=max_nodes))

    # Build DAG layer by layer to guarantee acyclicity
    nodes = []
    for i in range(num_nodes):
        # Can only depend on nodes with smaller IDs (earlier in the list)
        if i == 0:
            upstream_ids = set()
        else:
            # Randomly select some earlier nodes as dependencies
            possible_upstreams = list(range(i))
            num_deps = draw(st.integers(min_value=0, max_value=min(i, 3)))
            upstream_ids = set(draw(st.sampled_from(possible_upstreams)) for _ in range(num_deps))
        nodes.append((i, upstream_ids))

    return nodes


@st.composite
def template_dict_strategy(draw):
    """Generate a valid OpenJD job template dict."""
    job_name = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=20))
    step_name = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=20))
    command = draw(st.sampled_from(["render", "hython", "python"]))

    return {
        "specificationVersion": "jobtemplate-2023-09",
        "name": job_name,
        "steps": [
            {
                "name": step_name,
                "script": {
                    "actions": {"onRun": {"command": command}},
                },
            }
        ],
    }


@st.composite
def scheduler_config_strategy(draw):
    """Generate a valid SchedulerConfig."""
    from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.models import (
        SchedulerConfig,
    )

    return SchedulerConfig(
        farm_id=draw(st.text(alphabet="abcdef0123456789-", min_size=10, max_size=40)),
        queue_id=draw(st.text(alphabet="abcdef0123456789-", min_size=10, max_size=40)),
        priority=draw(st.integers(min_value=0, max_value=100)),
        job_name_prefix=draw(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=10)),
        job_description=draw(st.text(min_size=0, max_size=100)),
        aws_profile=draw(st.sampled_from(["default", "dev", "prod"])),
        max_concurrent_jobs=draw(st.integers(min_value=1, max_value=50)),
        poll_interval=draw(st.integers(min_value=5, max_value=120)),
    )


@pytest.fixture
def mock_work_item():
    """Create a simple mock work item."""
    return MockWorkItem(
        id=1,
        name="test_item",
        command="/usr/bin/render",
        arguments=["-f", "1", "-o", "/tmp/output.exr"],
        environment={"RENDER_ENGINE": "mantra"},
        attributes={"frame": "1", "output": "/tmp/output.exr"},
        input_files=["/tmp/input.hip"],
        output_files=["/tmp/output.exr"],
    )


@pytest.fixture
def mock_deadline_client():
    """Create a mock Deadline Cloud client."""
    client = MagicMock()
    client.get_job.return_value = {
        "jobId": "job-123",
        "lifecycleStatus": "SUCCEEDED",
        "lifecycleStatusMessage": "Completed",
    }
    return client
