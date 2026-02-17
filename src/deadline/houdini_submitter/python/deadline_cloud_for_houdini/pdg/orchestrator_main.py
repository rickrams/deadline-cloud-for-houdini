#!/usr/bin/env python
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Orchestrator entry point for PDG execution on Deadline Cloud workers.

This script is executed by the orchestrator job on a Deadline Cloud worker.
It launches a headless Houdini session, opens the scene, and cooks the TOP network.
"""

import argparse
import logging
import os
import sys

# Set orchestrator mode before importing scheduler
os.environ["DEADLINE_CLOUD_PDG_ORCHESTRATOR"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PDG Orchestrator for Deadline Cloud")
    parser.add_argument("--hip-file", required=True, help="Path to the Houdini scene file")
    parser.add_argument("--top-network", required=True, help="TOP network path in the scene")
    parser.add_argument("--scheduler-node", required=True, help="Scheduler node path in the scene")
    parser.add_argument("--farm-id", required=True, help="Deadline Cloud farm ID")
    parser.add_argument("--queue-id", required=True, help="Deadline Cloud queue ID")
    parser.add_argument("--max-concurrent-jobs", type=int, default=10, help="Max concurrent child jobs")
    parser.add_argument("--poll-interval", type=int, default=30, help="Status poll interval in seconds")
    return parser.parse_args()


def main() -> int:
    """Main entry point for the orchestrator."""
    args = parse_args()

    logger.info(f"Starting PDG orchestrator")
    logger.info(f"  Scene: {args.hip_file}")
    logger.info(f"  TOP Network: {args.top_network}")
    logger.info(f"  Scheduler: {args.scheduler_node}")
    logger.info(f"  Farm: {args.farm_id}")
    logger.info(f"  Queue: {args.queue_id}")

    # Import hou (must be in a Houdini environment)
    try:
        import hou
    except ImportError:
        logger.error("Failed to import hou module - not running in Houdini environment")
        return 1

    # Open the scene
    try:
        logger.info(f"Opening scene: {args.hip_file}")
        hou.hipFile.load(args.hip_file, suppress_save_prompt=True)
    except Exception as e:
        logger.error(f"Failed to open scene: {e}")
        return 1

    # Get the TOP network and scheduler node
    try:
        top_network = hou.node(args.top_network)
        if top_network is None:
            logger.error(f"TOP network not found: {args.top_network}")
            return 1

        scheduler_node = hou.node(args.scheduler_node)
        if scheduler_node is None:
            logger.error(f"Scheduler node not found: {args.scheduler_node}")
            return 1
    except Exception as e:
        logger.error(f"Failed to get nodes: {e}")
        return 1

    # Configure the scheduler from the node parameters
    from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.scheduler import (
        DeadlineCloudScheduler,
    )

    scheduler = DeadlineCloudScheduler(hou_module=hou)

    # Override config with command line args
    scheduler._config.farm_id = args.farm_id
    scheduler._config.queue_id = args.queue_id
    scheduler._config.max_concurrent_jobs = args.max_concurrent_jobs
    scheduler._config.poll_interval = args.poll_interval

    # Start the scheduler in orchestrator mode
    if not scheduler.on_start(scheduler_node):
        logger.error("Failed to start scheduler")
        return 1

    # Cook the TOP network
    try:
        logger.info(f"Cooking TOP network: {args.top_network}")
        # Use the scheduler to cook - this will call on_schedule for each work item
        top_network.cookWorkItems(block=True)
    except Exception as e:
        logger.error(f"Failed to cook TOP network: {e}")
        return 1

    # Stop the scheduler (this runs the orchestration loop)
    if not scheduler.on_stop():
        logger.error("Orchestration failed")
        return 1

    logger.info("Orchestration completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
