# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""PDG Scheduler for AWS Deadline Cloud."""

import logging
import os
import tempfile
from typing import Any, Optional

from deadline.client.api import create_job_from_job_bundle
from deadline.client.config import get_setting

from .constants import DEADLINE_CLOUD_PDG_ORCHESTRATOR
from .models import SchedulerConfig
from .orchestrator_builder import OrchestratorJobBuilder
from .orchestrator_loop import OrchestratorLoop
from .scene_packager import ScenePackager
from .translator import WorkItemTranslator

logger = logging.getLogger(__name__)


class DeadlineCloudScheduler:
    """PDG scheduler that submits the TOP network to Deadline Cloud.

    This scheduler operates in two modes:
    1. Submitter mode (artist workstation): Packages scene and submits orchestrator job
    2. Orchestrator mode (farm worker): Cooks TOP network and manages child jobs

    The mode is determined by the DEADLINE_CLOUD_PDG_ORCHESTRATOR environment variable.
    """

    def __init__(self, hou_module: Optional[Any] = None):
        """Initialize the scheduler.

        Args:
            hou_module: The hou module (for testing, uses real hou if None).
        """
        self._hou = hou_module
        self._config = SchedulerConfig()
        self._is_orchestrator_mode = os.environ.get(DEADLINE_CLOUD_PDG_ORCHESTRATOR) == "1"
        self._orchestrator_loop: Optional[OrchestratorLoop] = None
        self._orchestrator_job_id: Optional[str] = None
        self._work_items: list[Any] = []

    @property
    def is_orchestrator_mode(self) -> bool:
        """Return True if running in orchestrator mode on the farm."""
        return self._is_orchestrator_mode

    def configure_from_node(self, node: Any) -> bool:
        """Read scheduler parameters from the Houdini node.

        Args:
            node: The Houdini scheduler node.

        Returns:
            True if configuration succeeded.
        """
        try:
            self._config.farm_id = self._get_parm_value(node, "farm_id", "")
            self._config.queue_id = self._get_parm_value(node, "queue_id", "")
            self._config.priority = self._get_parm_value(node, "priority", 50)
            self._config.job_name_prefix = self._get_parm_value(node, "job_name_prefix", "PDG")
            self._config.job_description = self._get_parm_value(node, "job_description", "")
            self._config.aws_profile = self._get_parm_value(node, "aws_profile", "default")
            self._config.max_concurrent_jobs = self._get_parm_value(node, "max_concurrent_jobs", 10)
            self._config.poll_interval = self._get_parm_value(node, "poll_interval", 30)

            # Use defaults from deadline client config if not set
            if not self._config.farm_id:
                self._config.farm_id = get_setting("defaults.farm_id", default="")
            if not self._config.queue_id:
                self._config.queue_id = get_setting("defaults.queue_id", default="")

            return True
        except Exception as e:
            logger.error(f"Failed to configure scheduler: {e}")
            return False

    def _get_parm_value(self, node: Any, parm_name: str, default: Any) -> Any:
        """Get a parameter value from a node with a default fallback."""
        try:
            parm = node.parm(parm_name)
            if parm is not None:
                return parm.eval()
        except Exception:
            pass
        return default

    def on_start(self, node: Any) -> bool:
        """Called when the scheduler starts.

        In submitter mode: Validates, packages scene, submits orchestrator job.
        In orchestrator mode: Initializes the orchestrator loop.

        Args:
            node: The Houdini scheduler node.

        Returns:
            True if start succeeded.
        """
        if not self.configure_from_node(node):
            return False

        if self._is_orchestrator_mode:
            return self._start_orchestrator_mode()
        else:
            return self._start_submitter_mode(node)

    def _start_submitter_mode(self, node: Any) -> bool:
        """Start in submitter mode - package and submit orchestrator job."""
        logger.info("Starting Deadline Cloud scheduler in submitter mode")

        # Get hou module
        if self._hou is None:
            import hou

            self._hou = hou

        # Package the scene
        packager = ScenePackager()
        try:
            package = packager.package_from_node(node, self._hou)
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Scene packaging failed: {e}")
            return False

        if package.warnings:
            for warning in package.warnings:
                logger.warning(warning)

        # Build orchestrator job bundle
        builder = OrchestratorJobBuilder()
        with tempfile.TemporaryDirectory() as bundle_dir:
            builder.write_bundle(self._config, package, bundle_dir)

            # Submit the orchestrator job
            try:
                result = create_job_from_job_bundle(
                    job_bundle_dir=bundle_dir,
                    farm_id=self._config.farm_id,
                    queue_id=self._config.queue_id,
                    priority=self._config.priority,
                )
                self._orchestrator_job_id = result.get("jobId")
                logger.info(f"Submitted orchestrator job: {self._orchestrator_job_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to submit orchestrator job: {e}")
                return False

    def _start_orchestrator_mode(self) -> bool:
        """Start in orchestrator mode - initialize the loop."""
        logger.info("Starting Deadline Cloud scheduler in orchestrator mode")
        self._orchestrator_loop = OrchestratorLoop(
            config=self._config,
            translator=WorkItemTranslator(),
        )
        return True

    def on_schedule(self, work_item: Any) -> int:
        """Called by PDG when a work item is ready to be scheduled.

        In submitter mode: Returns success (orchestrator handles actual scheduling).
        In orchestrator mode: Queues the work item for processing.

        Args:
            work_item: The PDG work item.

        Returns:
            Schedule result code (0 = success).
        """
        if self._is_orchestrator_mode:
            self._work_items.append(work_item)
        # In submitter mode, we just acknowledge - orchestrator does the real work
        return 0  # pdg.scheduleResult.CookSucceeded

    def on_stop(self) -> bool:
        """Called when the scheduler stops.

        In submitter mode: Logs the orchestrator job ID.
        In orchestrator mode: Runs the orchestration loop to completion.

        Returns:
            True if stop succeeded.
        """
        if self._is_orchestrator_mode:
            return self._stop_orchestrator_mode()
        else:
            return self._stop_submitter_mode()

    def _stop_submitter_mode(self) -> bool:
        """Stop in submitter mode - log job ID for tracking."""
        if self._orchestrator_job_id:
            logger.info(
                f"Orchestrator job submitted: {self._orchestrator_job_id}\n"
                f"Track progress in Deadline Cloud console:\n"
                f"  Farm: {self._config.farm_id}\n"
                f"  Queue: {self._config.queue_id}\n"
                f"  Job: {self._orchestrator_job_id}"
            )
        return True

    def _stop_orchestrator_mode(self) -> bool:
        """Stop in orchestrator mode - run the loop."""
        if not self._orchestrator_loop:
            logger.error("Orchestrator loop not initialized")
            return False

        if not self._work_items:
            logger.warning("No work items to process")
            return True

        def get_deps(item: Any) -> set[int]:
            """Get upstream work item IDs for a work item."""
            try:
                return set(dep.id for dep in item.upstreamItems)
            except Exception:
                return set()

        exit_code = self._orchestrator_loop.run(self._work_items, get_deps)
        return exit_code == 0

    @property
    def config(self) -> SchedulerConfig:
        """Return the scheduler configuration."""
        return self._config

    @property
    def orchestrator_job_id(self) -> Optional[str]:
        """Return the orchestrator job ID (submitter mode only)."""
        return self._orchestrator_job_id
