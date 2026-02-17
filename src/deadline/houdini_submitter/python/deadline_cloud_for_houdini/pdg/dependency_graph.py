# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Dependency graph for tracking work item relationships and status."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class WorkItemStatus(Enum):
    """Status of a work item in the dependency graph."""

    PENDING = "PENDING"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass
class DependencyNode:
    """A node in the dependency graph representing a work item."""

    work_item_id: int
    top_node_name: str
    upstream_ids: set[int] = field(default_factory=set)
    downstream_ids: set[int] = field(default_factory=set)
    status: WorkItemStatus = WorkItemStatus.PENDING


class DependencyGraph:
    """Directed acyclic graph of work item dependencies."""

    def __init__(self):
        self._nodes: dict[int, DependencyNode] = {}
        self._job_to_items: dict[str, list[int]] = {}

    def add_node(
        self, work_item_id: int, top_node_name: str, upstream_ids: Optional[set[int]] = None
    ) -> None:
        """Add a work item node to the graph."""
        upstream_ids = upstream_ids or set()

        node = DependencyNode(
            work_item_id=work_item_id,
            top_node_name=top_node_name,
            upstream_ids=upstream_ids.copy(),
        )
        self._nodes[work_item_id] = node

        # Update downstream references for upstream nodes
        for upstream_id in upstream_ids:
            if upstream_id in self._nodes:
                self._nodes[upstream_id].downstream_ids.add(work_item_id)

        # Set initial status based on dependencies
        if not upstream_ids:
            node.status = WorkItemStatus.READY

    def get_ready_items(self) -> list[int]:
        """Return work item IDs whose upstream dependencies are all satisfied."""
        return [
            node.work_item_id
            for node in self._nodes.values()
            if node.status == WorkItemStatus.READY
        ]

    def mark_submitted(self, work_item_ids: list[int], child_job_id: str) -> None:
        """Mark work items as submitted and record the child job mapping."""
        self._job_to_items[child_job_id] = work_item_ids
        for wid in work_item_ids:
            if wid in self._nodes:
                self._nodes[wid].status = WorkItemStatus.SUBMITTED

    def mark_succeeded(self, child_job_id: str) -> list[int]:
        """Mark work items for a child job as succeeded.

        Returns newly unblocked downstream work item IDs.
        """
        work_item_ids = self._job_to_items.get(child_job_id, [])
        for wid in work_item_ids:
            if wid in self._nodes:
                self._nodes[wid].status = WorkItemStatus.SUCCEEDED

        return self._update_downstream_status(work_item_ids)

    def mark_failed(self, child_job_id: str) -> list[int]:
        """Mark work items for a child job as failed.

        Returns downstream work item IDs that are now permanently blocked.
        """
        work_item_ids = self._job_to_items.get(child_job_id, [])
        for wid in work_item_ids:
            if wid in self._nodes:
                self._nodes[wid].status = WorkItemStatus.FAILED

        return self._get_blocked_downstream(work_item_ids)

    def _update_downstream_status(self, completed_ids: list[int]) -> list[int]:
        """Update downstream nodes and return newly ready ones."""
        newly_ready = []
        for wid in completed_ids:
            if wid not in self._nodes:
                continue
            for downstream_id in self._nodes[wid].downstream_ids:
                downstream_node = self._nodes.get(downstream_id)
                if downstream_node and downstream_node.status == WorkItemStatus.PENDING:
                    # Check if all upstreams are now succeeded
                    if all(
                        self._nodes[uid].status == WorkItemStatus.SUCCEEDED
                        for uid in downstream_node.upstream_ids
                        if uid in self._nodes
                    ):
                        downstream_node.status = WorkItemStatus.READY
                        newly_ready.append(downstream_id)
        return newly_ready

    def _get_blocked_downstream(self, failed_ids: list[int]) -> list[int]:
        """Get all downstream nodes that are blocked due to failures."""
        blocked = []
        visited = set()

        def visit(wid: int):
            if wid in visited:
                return
            visited.add(wid)
            node = self._nodes.get(wid)
            if not node:
                return
            for downstream_id in node.downstream_ids:
                downstream_node = self._nodes.get(downstream_id)
                if downstream_node and downstream_node.status in (
                    WorkItemStatus.PENDING,
                    WorkItemStatus.READY,
                ):
                    blocked.append(downstream_id)
                    visit(downstream_id)

        for fid in failed_ids:
            visit(fid)
        return blocked

    def has_cycle(self) -> bool:
        """Detect cycles using topological sort (Kahn's algorithm)."""
        if not self._nodes:
            return False

        in_degree = {wid: len(node.upstream_ids) for wid, node in self._nodes.items()}
        queue = [wid for wid, degree in in_degree.items() if degree == 0]
        processed = 0

        while queue:
            wid = queue.pop(0)
            processed += 1
            node = self._nodes.get(wid)
            if node:
                for downstream_id in node.downstream_ids:
                    in_degree[downstream_id] -= 1
                    if in_degree[downstream_id] == 0:
                        queue.append(downstream_id)

        return processed != len(self._nodes)

    def is_complete(self) -> bool:
        """Return True if all nodes are in a terminal state."""
        terminal_states = {WorkItemStatus.SUCCEEDED, WorkItemStatus.FAILED}
        return all(node.status in terminal_states for node in self._nodes.values())

    def all_succeeded(self) -> bool:
        """Return True if all nodes succeeded."""
        return all(node.status == WorkItemStatus.SUCCEEDED for node in self._nodes.values())

    def get_summary(self) -> dict[str, int]:
        """Return counts by status."""
        summary: dict[str, int] = {}
        for node in self._nodes.values():
            status_name = node.status.value
            summary[status_name] = summary.get(status_name, 0) + 1
        return summary

    def get_node(self, work_item_id: int) -> Optional[DependencyNode]:
        """Get a node by work item ID."""
        return self._nodes.get(work_item_id)

    def __len__(self) -> int:
        return len(self._nodes)
