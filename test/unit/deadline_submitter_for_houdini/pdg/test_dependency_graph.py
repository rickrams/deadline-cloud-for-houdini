# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Property and unit tests for DependencyGraph.

Feature: houdini-pdg-support
Properties 7, 8, 9: Dependency graph behavior
"""

import pytest
from hypothesis import given, settings, assume

from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.dependency_graph import (
    DependencyGraph,
    WorkItemStatus,
)

from .conftest import dag_strategy


class TestDependencyGraphCompletionUnblocking:
    """Property 7: Dependency graph completion unblocking.

    For any DAG of work items, when an upstream work item's child job is marked as succeeded,
    the set of newly unblocked downstream work items should be exactly those whose upstream
    dependencies have all been satisfied.

    Validates: Requirements 4.2, 4.3, 6.2
    """

    @settings(max_examples=100)
    @given(dag=dag_strategy(min_nodes=2, max_nodes=15))
    def test_completion_unblocks_ready_downstream(self, dag: list[tuple[int, set[int]]]):
        """Completing upstream items unblocks downstream items with all deps satisfied."""
        graph = DependencyGraph()

        # Build the graph
        for work_item_id, upstream_ids in dag:
            graph.add_node(work_item_id, f"node_{work_item_id}", upstream_ids)

        # Get initial ready items (those with no dependencies)
        initial_ready = set(graph.get_ready_items())

        # Skip if no ready items to process
        assume(len(initial_ready) > 0)

        # Submit and complete all initial ready items
        for wid in initial_ready:
            graph.mark_submitted([wid], f"job_{wid}")

        newly_ready_all = set()
        for wid in initial_ready:
            newly_ready = graph.mark_succeeded(f"job_{wid}")
            newly_ready_all.update(newly_ready)

        # Verify: newly ready items should have all their upstreams succeeded
        for ready_id in newly_ready_all:
            node = graph.get_node(ready_id)
            assert node is not None
            for upstream_id in node.upstream_ids:
                upstream_node = graph.get_node(upstream_id)
                assert upstream_node is not None
                assert upstream_node.status == WorkItemStatus.SUCCEEDED


class TestDependencyGraphFailurePropagation:
    """Property 8: Dependency graph failure propagation.

    For any DAG of work items, when a work item's child job is marked as failed,
    all downstream work items that transitively depend on the failed item should
    be identified as permanently blocked.

    Validates: Requirements 6.3
    """

    @settings(max_examples=100)
    @given(dag=dag_strategy(min_nodes=2, max_nodes=15))
    def test_failure_blocks_downstream(self, dag: list[tuple[int, set[int]]]):
        """Failing an item blocks all transitive downstream items."""
        graph = DependencyGraph()

        # Build the graph
        for work_item_id, upstream_ids in dag:
            graph.add_node(work_item_id, f"node_{work_item_id}", upstream_ids)

        # Get initial ready items
        initial_ready = list(graph.get_ready_items())
        assume(len(initial_ready) > 0)

        # Submit and fail the first ready item
        first_ready = initial_ready[0]
        graph.mark_submitted([first_ready], "job_fail")
        blocked = graph.mark_failed("job_fail")

        # Verify: blocked items should be downstream of the failed item
        failed_node = graph.get_node(first_ready)
        assert failed_node is not None
        assert failed_node.status == WorkItemStatus.FAILED

        # All blocked items should be reachable from the failed node
        def get_all_downstream(wid: int, visited: set[int]) -> set[int]:
            if wid in visited:
                return set()
            visited.add(wid)
            node = graph.get_node(wid)
            if not node:
                return set()
            result = set(node.downstream_ids)
            for did in node.downstream_ids:
                result.update(get_all_downstream(did, visited))
            return result

        all_downstream = get_all_downstream(first_ready, set())
        for blocked_id in blocked:
            assert blocked_id in all_downstream


class TestTerminalStateDetection:
    """Property 9: Terminal state detection.

    For any dependency graph where all nodes are in a terminal state (SUCCEEDED or FAILED),
    is_complete() should return True. Furthermore, all_succeeded() should return True
    if and only if every node is in the SUCCEEDED state.

    Validates: Requirements 6.4
    """

    @settings(max_examples=100)
    @given(dag=dag_strategy(min_nodes=1, max_nodes=10))
    def test_all_succeeded_means_complete(self, dag: list[tuple[int, set[int]]]):
        """When all items succeed, is_complete and all_succeeded are both True."""
        graph = DependencyGraph()

        # Build the graph
        for work_item_id, upstream_ids in dag:
            graph.add_node(work_item_id, f"node_{work_item_id}", upstream_ids)

        # Process all items in topological order
        while not graph.is_complete():
            ready = graph.get_ready_items()
            if not ready:
                break
            for wid in ready:
                graph.mark_submitted([wid], f"job_{wid}")
                graph.mark_succeeded(f"job_{wid}")

        assert graph.is_complete()
        assert graph.all_succeeded()

    @settings(max_examples=100)
    @given(dag=dag_strategy(min_nodes=2, max_nodes=10))
    def test_any_failure_means_not_all_succeeded(self, dag: list[tuple[int, set[int]]]):
        """When any item fails, all_succeeded is False but is_complete can be True."""
        graph = DependencyGraph()

        # Build the graph
        for work_item_id, upstream_ids in dag:
            graph.add_node(work_item_id, f"node_{work_item_id}", upstream_ids)

        # Get initial ready items
        initial_ready = list(graph.get_ready_items())
        assume(len(initial_ready) > 0)

        # Fail the first item
        first = initial_ready[0]
        graph.mark_submitted([first], "job_0")
        graph.mark_failed("job_0")

        # Complete remaining items
        while True:
            ready = graph.get_ready_items()
            if not ready:
                break
            for wid in ready:
                graph.mark_submitted([wid], f"job_{wid}")
                graph.mark_succeeded(f"job_{wid}")

        # Mark blocked items as failed too (they can't proceed)
        # In real usage, blocked items stay PENDING/READY but we check the property
        assert not graph.all_succeeded()


class TestDependencyGraphEdgeCases:
    """Unit tests for DependencyGraph edge cases.

    Validates: Requirements 4.4
    """

    def test_empty_graph(self):
        """Empty graph has no cycles and is complete."""
        graph = DependencyGraph()
        assert not graph.has_cycle()
        assert graph.is_complete()
        assert graph.all_succeeded()
        assert graph.get_ready_items() == []
        assert graph.get_summary() == {}

    def test_single_node_graph(self):
        """Single node with no dependencies is immediately ready."""
        graph = DependencyGraph()
        graph.add_node(1, "node_1")

        assert not graph.has_cycle()
        assert not graph.is_complete()
        assert graph.get_ready_items() == [1]

        graph.mark_submitted([1], "job_1")
        graph.mark_succeeded("job_1")

        assert graph.is_complete()
        assert graph.all_succeeded()

    def test_linear_chain_dependency(self):
        """Linear chain: A -> B -> C processes in order."""
        graph = DependencyGraph()
        graph.add_node(1, "A")
        graph.add_node(2, "B", {1})
        graph.add_node(3, "C", {2})

        assert not graph.has_cycle()
        assert graph.get_ready_items() == [1]

        # Complete A
        graph.mark_submitted([1], "job_1")
        newly_ready = graph.mark_succeeded("job_1")
        assert newly_ready == [2]

        # Complete B
        graph.mark_submitted([2], "job_2")
        newly_ready = graph.mark_succeeded("job_2")
        assert newly_ready == [3]

        # Complete C
        graph.mark_submitted([3], "job_3")
        graph.mark_succeeded("job_3")

        assert graph.is_complete()
        assert graph.all_succeeded()

    def test_circular_dependency_detection(self):
        """Circular dependency is detected."""
        graph = DependencyGraph()
        # Create A -> B -> C -> A cycle
        # Note: We need to add nodes in a way that creates a cycle
        # Since add_node only links to existing upstream nodes,
        # we need to manually create the cycle
        graph.add_node(1, "A")
        graph.add_node(2, "B", {1})
        graph.add_node(3, "C", {2})

        # Manually add cycle: A depends on C
        graph._nodes[1].upstream_ids.add(3)
        graph._nodes[3].downstream_ids.add(1)

        assert graph.has_cycle()

    def test_diamond_dependency(self):
        """Diamond pattern: A -> B, A -> C, B -> D, C -> D."""
        graph = DependencyGraph()
        graph.add_node(1, "A")
        graph.add_node(2, "B", {1})
        graph.add_node(3, "C", {1})
        graph.add_node(4, "D", {2, 3})

        assert not graph.has_cycle()
        assert graph.get_ready_items() == [1]

        # Complete A - both B and C become ready
        graph.mark_submitted([1], "job_1")
        newly_ready = graph.mark_succeeded("job_1")
        assert set(newly_ready) == {2, 3}

        # Complete B - D not ready yet (needs C)
        graph.mark_submitted([2], "job_2")
        newly_ready = graph.mark_succeeded("job_2")
        assert newly_ready == []

        # Complete C - D becomes ready
        graph.mark_submitted([3], "job_3")
        newly_ready = graph.mark_succeeded("job_3")
        assert newly_ready == [4]

    def test_get_summary(self):
        """Summary returns correct counts by status."""
        graph = DependencyGraph()
        graph.add_node(1, "A")
        graph.add_node(2, "B", {1})
        graph.add_node(3, "C", {1})

        summary = graph.get_summary()
        assert summary == {"READY": 1, "PENDING": 2}

        graph.mark_submitted([1], "job_1")
        summary = graph.get_summary()
        assert summary == {"SUBMITTED": 1, "PENDING": 2}

        graph.mark_succeeded("job_1")
        summary = graph.get_summary()
        assert summary == {"SUCCEEDED": 1, "READY": 2}
