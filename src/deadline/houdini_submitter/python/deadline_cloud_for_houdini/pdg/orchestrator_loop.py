# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Main orchestration loop for PDG execution on Deadline Cloud."""

import logging
import os
import signal
import tempfile
import time
from collections import defaultdict
from typing import Any, Callable, Optional

from botocore.exceptions import ClientError

from deadline.client.api import get_boto3_client
from deadline.client.job_bundle.submission import AssetReferences

from .dependency_graph import DependencyGraph, WorkItemStatus
from .models import JobStatus, SchedulerConfig, WorkItemMapping
from .translator import JobBundle, WorkItemTranslator

logger = logging.getLogger(__name__)


class OrchestratorLoop:
    """Main orchestration loop running on the Deadline Cloud worker."""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0  # seconds

    def __init__(
        self,
        config: SchedulerConfig,
        translator: Optional[WorkItemTranslator] = None,
        deadline_client: Optional[Any] = None,
        job_submitter: Optional[Callable[[str], str]] = None,
    ):
        """Initialize the orchestrator loop.

        Args:
            config: Scheduler configuration.
            translator: WorkItemTranslator instance (created if None).
            deadline_client: Boto3 Deadline client (created if None).
            job_submitter: Callable to submit job bundles (for testing).
        """
        self._config = config
        self._translator = translator or WorkItemTranslator()
        self._deadline_client = deadline_client
        self._job_submitter = job_submitter

        self._graph = DependencyGraph()
        self._work_item_mappings: dict[int, WorkItemMapping] = {}
        self._in_flight_jobs: dict[str, list[int]] = {}  # job_id -> work_item_ids
        self._cancelled = False
        self._upstream_outputs: dict[int, AssetReferences] = {}  # work_item_id -> outputs

        # Set up signal handlers for cancellation
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _get_deadline_client(self) -> Any:
        """Get or create the Deadline client."""
        if self._deadline_client is None:
            self._deadline_client = get_boto3_client("deadline")
        return self._deadline_client

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle termination signals."""
        logger.info(f"Received signal {signum}, initiating cancellation")
        self._cancelled = True

    def run(
        self,
        work_items: list[Any],
        get_work_item_deps: Callable[[Any], set[int]],
    ) -> int:
        """Run the orchestration loop.

        Args:
            work_items: List of PDG work items to process.
            get_work_item_deps: Function to get upstream work item IDs for a work item.

        Returns:
            Exit code: 0 if all succeeded, 1 if any failed.
        """
        logger.info(f"Starting orchestration with {len(work_items)} work items")

        # Build dependency graph
        for item in work_items:
            upstream_ids = get_work_item_deps(item)
            self._graph.add_node(item.id, getattr(item, "top_node_name", "unknown"), upstream_ids)
            self._work_item_mappings[item.id] = WorkItemMapping(
                work_item_id=item.id,
                top_node_name=getattr(item, "top_node_name", "unknown"),
            )

        # Check for cycles
        if self._graph.has_cycle():
            logger.error("Circular dependency detected in work item graph")
            return 1

        # Main loop
        while not self._graph.is_complete() and not self._cancelled:
            # Submit ready work items
            ready_ids = self._graph.get_ready_items()
            if ready_ids:
                self._submit_ready_work_items(work_items, ready_ids)

            # Poll for completions
            if self._in_flight_jobs:
                self._poll_child_jobs()

            # Sleep before next iteration
            if not self._graph.is_complete() and not self._cancelled:
                time.sleep(self._config.poll_interval)

        # Handle cancellation
        if self._cancelled:
            self._handle_cancellation()
            return 1

        # Log summary
        summary = self._graph.get_summary()
        logger.info(f"Orchestration complete: {summary}")

        return 0 if self._graph.all_succeeded() else 1

    def _submit_ready_work_items(self, all_items: list[Any], ready_ids: list[int]) -> None:
        """Submit ready work items, respecting concurrency limit."""
        # Check concurrency limit
        available_slots = self._config.max_concurrent_jobs - len(self._in_flight_jobs)
        if available_slots <= 0:
            logger.debug("Concurrency limit reached, waiting for completions")
            return

        # Group ready items by TOP node for batching
        items_by_node: dict[str, list[Any]] = defaultdict(list)
        id_to_item = {item.id: item for item in all_items}

        for wid in ready_ids[:available_slots]:
            item = id_to_item.get(wid)
            if item:
                node_name = getattr(item, "top_node_name", "unknown")
                items_by_node[node_name].append(item)

        # Submit batches
        for node_name, items in items_by_node.items():
            if len(self._in_flight_jobs) >= self._config.max_concurrent_jobs:
                break

            self._submit_batch(items, node_name)

    def _submit_batch(self, items: list[Any], node_name: str) -> None:
        """Submit a batch of work items as a child job."""
        work_item_ids = [item.id for item in items]

        # Collect upstream outputs for these items
        upstream_refs = AssetReferences()
        for item in items:
            for upstream_id in getattr(item, "upstream_ids", set()):
                if upstream_id in self._upstream_outputs:
                    refs = self._upstream_outputs[upstream_id]
                    upstream_refs.input_filenames.update(refs.input_filenames)

        # Translate to job bundle
        try:
            bundle = self._translator.translate_batch(
                items, node_name, self._config, upstream_asset_refs=upstream_refs
            )
        except Exception as e:
            logger.error(f"Failed to translate work items for {node_name}: {e}")
            for wid in work_item_ids:
                self._mark_failed(wid, str(e))
            return

        # Submit with retry
        job_id = self._submit_with_retry(bundle, node_name)
        if job_id:
            self._graph.mark_submitted(work_item_ids, job_id)
            self._in_flight_jobs[job_id] = work_item_ids
            for wid in work_item_ids:
                self._work_item_mappings[wid].child_job_id = job_id
                self._work_item_mappings[wid].status = "SUBMITTED"
            logger.info(f"Submitted child job {job_id} for {node_name} ({len(items)} work items)")
        else:
            for wid in work_item_ids:
                self._mark_failed(wid, "Job submission failed after retries")

    def _submit_with_retry(self, bundle: JobBundle, node_name: str) -> Optional[str]:
        """Submit a job bundle with retry logic."""
        for attempt in range(self.MAX_RETRIES):
            try:
                if self._job_submitter:
                    # Use injected submitter (for testing)
                    with tempfile.TemporaryDirectory() as tmpdir:
                        self._translator.write_bundle_to_dir(bundle, tmpdir)
                        return self._job_submitter(tmpdir)
                else:
                    # Use real submission
                    from deadline.client.api import create_job_from_job_bundle

                    with tempfile.TemporaryDirectory() as tmpdir:
                        self._translator.write_bundle_to_dir(bundle, tmpdir)
                        result = create_job_from_job_bundle(
                            job_bundle_dir=tmpdir,
                            farm_id=self._config.farm_id,
                            queue_id=self._config.queue_id,
                            priority=self._config.priority,
                        )
                        return result.get("jobId")

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("ThrottlingException", "ServiceUnavailable"):
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(f"Transient error submitting {node_name}, retry in {delay}s: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"Non-retryable error submitting {node_name}: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error submitting {node_name}: {e}")
                return None

        logger.error(f"Failed to submit {node_name} after {self.MAX_RETRIES} retries")
        return None

    def _poll_child_jobs(self) -> None:
        """Poll all in-flight child jobs for status updates."""
        client = self._get_deadline_client()
        completed_jobs = []

        for job_id in list(self._in_flight_jobs.keys()):
            try:
                response = client.get_job(
                    farmId=self._config.farm_id,
                    queueId=self._config.queue_id,
                    jobId=job_id,
                )
                status = response.get("lifecycleStatus", "UNKNOWN")

                if status == "SUCCEEDED":
                    logger.info(f"Child job {job_id} succeeded")
                    self._handle_job_completion(job_id, response)
                    completed_jobs.append(job_id)
                elif status in ("FAILED", "CANCELED"):
                    logger.warning(f"Child job {job_id} {status}")
                    self._handle_job_failure(job_id, response)
                    completed_jobs.append(job_id)
                else:
                    logger.debug(f"Child job {job_id} status: {status}")

            except Exception as e:
                logger.error(f"Error polling job {job_id}: {e}")

        # Remove completed jobs from in-flight
        for job_id in completed_jobs:
            del self._in_flight_jobs[job_id]

    def _handle_job_completion(self, job_id: str, response: dict[str, Any]) -> None:
        """Handle a completed child job."""
        work_item_ids = self._in_flight_jobs.get(job_id, [])

        # Collect output information
        output_refs = AssetReferences()
        # In a real implementation, we'd extract output paths from the job response

        # Mark work items as succeeded and store outputs
        newly_ready = self._graph.mark_succeeded(job_id)
        for wid in work_item_ids:
            self._work_item_mappings[wid].status = "SUCCEEDED"
            self._upstream_outputs[wid] = output_refs

        logger.info(f"Job {job_id} completed, {len(newly_ready)} work items now ready")

    def _handle_job_failure(self, job_id: str, response: dict[str, Any]) -> None:
        """Handle a failed child job."""
        work_item_ids = self._in_flight_jobs.get(job_id, [])
        message = response.get("lifecycleStatusMessage", "Unknown failure")

        blocked = self._graph.mark_failed(job_id)
        for wid in work_item_ids:
            self._work_item_mappings[wid].status = "FAILED"

        logger.warning(f"Job {job_id} failed: {message}. {len(blocked)} downstream items blocked.")

    def _mark_failed(self, work_item_id: int, reason: str) -> None:
        """Mark a single work item as failed."""
        if work_item_id in self._work_item_mappings:
            self._work_item_mappings[work_item_id].status = "FAILED"
        logger.error(f"Work item {work_item_id} failed: {reason}")

    def _handle_cancellation(self) -> None:
        """Cancel all in-flight child jobs."""
        logger.info("Cancelling in-flight child jobs")
        client = self._get_deadline_client()

        for job_id, work_item_ids in self._in_flight_jobs.items():
            try:
                client.update_job(
                    farmId=self._config.farm_id,
                    queueId=self._config.queue_id,
                    jobId=job_id,
                    targetTaskRunStatus="CANCELED",
                )
                logger.info(f"Cancelled job {job_id} (work items: {work_item_ids})")
            except Exception as e:
                logger.error(f"Error cancelling job {job_id}: {e}")

    @property
    def in_flight_count(self) -> int:
        """Return the number of in-flight child jobs."""
        return len(self._in_flight_jobs)

    @property
    def graph(self) -> DependencyGraph:
        """Return the dependency graph (for testing)."""
        return self._graph
