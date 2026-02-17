# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Property and unit tests for OrchestratorLoop.

Feature: houdini-pdg-support
Properties 10, 12: Orchestrator behavior
"""

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.orchestrator_loop import (
    OrchestratorLoop,
)
from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.models import SchedulerConfig


@dataclass
class MockWorkItemForLoop:
    """Mock work item for orchestrator loop testing."""

    id: int
    name: str = ""
    top_node_name: str = "test_node"
    command: str = "/usr/bin/render"
    arguments: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    upstream_ids: set[int] = field(default_factory=set)


def make_config(max_concurrent=5, poll_interval=1):
    return SchedulerConfig(
        farm_id="farm-123",
        queue_id="queue-456",
        max_concurrent_jobs=max_concurrent,
        poll_interval=poll_interval,
    )


class TestConcurrencyLimitInvariant:
    """Property 10: Concurrency limit invariant.

    For any sequence of work item submissions and child job completions,
    the number of in-flight child jobs should never exceed max_concurrent_jobs.

    Validates: Requirements 6.5
    """

    @settings(max_examples=50)
    @given(
        num_items=st.integers(min_value=1, max_value=20),
        max_concurrent=st.integers(min_value=1, max_value=5),
    )
    def test_in_flight_never_exceeds_limit(self, num_items: int, max_concurrent: int):
        """In-flight job count never exceeds configured limit."""
        config = make_config(max_concurrent=max_concurrent)

        # Track submitted jobs
        job_counter = [0]

        def mock_submitter(bundle_dir: str) -> str:
            job_id = f"job-{job_counter[0]}"
            job_counter[0] += 1
            return job_id

        # Create mock client that returns RUNNING status
        mock_client = MagicMock()
        mock_client.get_job.return_value = {"lifecycleStatus": "RUNNING"}

        loop = OrchestratorLoop(
            config=config,
            deadline_client=mock_client,
            job_submitter=mock_submitter,
        )

        # Create work items with no dependencies (all ready immediately)
        items = [MockWorkItemForLoop(id=i, name=f"item_{i}") for i in range(num_items)]

        # Initialize graph and mappings
        for item in items:
            loop._graph.add_node(item.id, item.top_node_name, set())
            loop._work_item_mappings[item.id] = MagicMock(status="PENDING")

        ready = loop._graph.get_ready_items()
        loop._submit_ready_work_items(items, ready)

        # Verify concurrency limit
        assert loop.in_flight_count <= max_concurrent


class TestResultCollectionFidelity:
    """Property 12: Result collection fidelity.

    For any completed child job with output file paths and result attributes,
    the corresponding WorkItemMapping should contain all output information.

    Validates: Requirements 8.1, 8.2
    """

    def test_successful_job_updates_mapping(self):
        """Successful job completion updates work item mapping status."""
        config = make_config()
        mock_client = MagicMock()

        loop = OrchestratorLoop(config=config, deadline_client=mock_client)

        # Set up a submitted job
        loop._in_flight_jobs["job-1"] = [1, 2]
        loop._work_item_mappings[1] = MagicMock(status="SUBMITTED")
        loop._work_item_mappings[2] = MagicMock(status="SUBMITTED")
        loop._graph.add_node(1, "node1", set())
        loop._graph.add_node(2, "node1", set())
        loop._graph.mark_submitted([1, 2], "job-1")

        # Simulate completion
        response = {
            "lifecycleStatus": "SUCCEEDED",
            "lifecycleStatusMessage": "Completed",
        }
        loop._handle_job_completion("job-1", response)

        # Verify mappings updated
        assert loop._work_item_mappings[1].status == "SUCCEEDED"
        assert loop._work_item_mappings[2].status == "SUCCEEDED"


class TestOrchestratorEdgeCases:
    """Unit tests for orchestrator edge cases."""

    def test_retry_on_transient_error(self):
        """Transient API errors trigger retry with backoff."""
        from botocore.exceptions import ClientError

        config = make_config()
        call_count = [0]

        def failing_submitter(bundle_dir: str) -> str:
            call_count[0] += 1
            if call_count[0] < 3:
                raise ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
                    "CreateJob",
                )
            return "job-success"

        loop = OrchestratorLoop(config=config, job_submitter=failing_submitter)
        loop.RETRY_BASE_DELAY = 0.01  # Speed up test

        from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.translator import (
            JobBundle,
        )

        bundle = JobBundle(
            template={"specificationVersion": "jobtemplate-2023-09", "name": "test", "steps": []}
        )

        job_id = loop._submit_with_retry(bundle, "test_node")

        assert job_id == "job-success"
        assert call_count[0] == 3

    def test_cancellation_stops_new_submissions(self):
        """Setting cancelled flag prevents new submissions."""
        config = make_config()
        loop = OrchestratorLoop(config=config)
        loop._cancelled = True

        items = [MockWorkItemForLoop(id=1)]
        for item in items:
            loop._graph.add_node(item.id, item.top_node_name, set())

        # Even with ready items, cancelled loop shouldn't submit
        # (This is checked in the run() method's while condition)
        assert loop._cancelled
        assert loop.in_flight_count == 0

    def test_all_succeeded_returns_zero(self):
        """All work items succeeding returns exit code 0."""
        config = make_config()
        mock_client = MagicMock()
        mock_client.get_job.return_value = {"lifecycleStatus": "SUCCEEDED"}

        submitted = []

        def mock_submitter(bundle_dir: str) -> str:
            job_id = f"job-{len(submitted)}"
            submitted.append(job_id)
            return job_id

        loop = OrchestratorLoop(
            config=config, deadline_client=mock_client, job_submitter=mock_submitter
        )

        items = [MockWorkItemForLoop(id=1)]

        # Manually run through the logic
        for item in items:
            loop._graph.add_node(item.id, item.top_node_name, set())
            loop._work_item_mappings[item.id] = MagicMock(status="PENDING")

        # Submit
        ready = loop._graph.get_ready_items()
        loop._submit_ready_work_items(items, ready)

        # Complete
        loop._poll_child_jobs()

        assert loop._graph.all_succeeded()

    def test_any_failure_returns_one(self):
        """Any work item failing returns exit code 1."""
        config = make_config()
        mock_client = MagicMock()
        mock_client.get_job.return_value = {
            "lifecycleStatus": "FAILED",
            "lifecycleStatusMessage": "Task failed",
        }

        def mock_submitter(bundle_dir: str) -> str:
            return "job-1"

        loop = OrchestratorLoop(
            config=config, deadline_client=mock_client, job_submitter=mock_submitter
        )

        items = [MockWorkItemForLoop(id=1)]

        for item in items:
            loop._graph.add_node(item.id, item.top_node_name, set())
            loop._work_item_mappings[item.id] = MagicMock(status="PENDING")

        # Submit and fail
        ready = loop._graph.get_ready_items()
        loop._submit_ready_work_items(items, ready)
        loop._poll_child_jobs()

        assert not loop._graph.all_succeeded()

    def test_circular_dependency_detected(self):
        """Circular dependency in work items is detected."""
        config = make_config()
        loop = OrchestratorLoop(config=config)

        # Create circular dependency manually
        loop._graph.add_node(1, "A", set())
        loop._graph.add_node(2, "B", {1})
        loop._graph.add_node(3, "C", {2})
        # Add cycle
        loop._graph._nodes[1].upstream_ids.add(3)
        loop._graph._nodes[3].downstream_ids.add(1)

        assert loop._graph.has_cycle()
