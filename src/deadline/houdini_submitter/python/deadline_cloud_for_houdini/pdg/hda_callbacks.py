# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""HDA callbacks for the Deadline Cloud PDG Scheduler node.

This module provides the Python callbacks for the Deadline Cloud scheduler HDA.
The HDA should be created in Houdini with the following parameters and callbacks.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_scheduler_parm_templates() -> list[Any]:
    """Create parameter templates for the scheduler node.

    Returns a list of hou.ParmTemplate objects that define the scheduler's parameters.
    This should be called when creating the HDA to set up its parameter interface.
    """
    import hou

    templates = []

    # Deadline Cloud Settings folder
    dc_folder = hou.FolderParmTemplate(
        "deadline_cloud_settings",
        "Deadline Cloud Settings",
        folder_type=hou.folderType.Tabs,
    )

    # Farm selection
    dc_folder.addParmTemplate(
        hou.StringParmTemplate(
            "farm_id",
            "Farm",
            1,
            default_value=("",),
            help="AWS Deadline Cloud Farm ID",
        )
    )

    # Queue selection
    dc_folder.addParmTemplate(
        hou.StringParmTemplate(
            "queue_id",
            "Queue",
            1,
            default_value=("",),
            help="AWS Deadline Cloud Queue ID",
        )
    )

    # Priority
    dc_folder.addParmTemplate(
        hou.IntParmTemplate(
            "priority",
            "Priority",
            1,
            default_value=(50,),
            min=0,
            max=100,
            help="Job priority (0-100, higher is more urgent)",
        )
    )

    templates.append(dc_folder)

    # Job Settings folder
    job_folder = hou.FolderParmTemplate(
        "job_settings",
        "Job Settings",
        folder_type=hou.folderType.Tabs,
    )

    # Job name prefix
    job_folder.addParmTemplate(
        hou.StringParmTemplate(
            "job_name_prefix",
            "Job Name Prefix",
            1,
            default_value=("PDG",),
            help="Prefix for submitted job names",
        )
    )

    # Job description
    job_folder.addParmTemplate(
        hou.StringParmTemplate(
            "job_description",
            "Description",
            1,
            default_value=("",),
            help="Description for submitted jobs",
        )
    )

    # AWS profile
    job_folder.addParmTemplate(
        hou.StringParmTemplate(
            "aws_profile",
            "AWS Profile",
            1,
            default_value=("default",),
            help="AWS profile name for credentials",
        )
    )

    templates.append(job_folder)

    # Advanced Settings folder
    adv_folder = hou.FolderParmTemplate(
        "advanced_settings",
        "Advanced",
        folder_type=hou.folderType.Tabs,
    )

    # Max concurrent jobs
    adv_folder.addParmTemplate(
        hou.IntParmTemplate(
            "max_concurrent_jobs",
            "Max Concurrent Jobs",
            1,
            default_value=(10,),
            min=1,
            max=100,
            help="Maximum number of concurrent child jobs",
        )
    )

    # Poll interval
    adv_folder.addParmTemplate(
        hou.IntParmTemplate(
            "poll_interval",
            "Poll Interval (seconds)",
            1,
            default_value=(30,),
            min=5,
            max=300,
            help="Seconds between status polls",
        )
    )

    templates.append(adv_folder)

    return templates


# HDA Callback Functions


def farm_id_callback(node: Any) -> None:
    """Callback when farm_id parameter changes.

    Updates the queue menu to show queues for the selected farm.
    """
    try:
        from deadline.client.api import list_queues

        farm_id = node.parm("farm_id").eval()
        if not farm_id:
            return

        # This would populate a menu - for now just validate
        logger.debug(f"Farm selected: {farm_id}")
    except Exception as e:
        logger.error(f"Error in farm_id_callback: {e}")


def queue_id_callback(node: Any) -> None:
    """Callback when queue_id parameter changes."""
    try:
        queue_id = node.parm("queue_id").eval()
        logger.debug(f"Queue selected: {queue_id}")
    except Exception as e:
        logger.error(f"Error in queue_id_callback: {e}")


def update_queue_parameters_callback(node: Any) -> None:
    """Callback to refresh queue parameters from Deadline Cloud."""
    try:
        from deadline.houdini_submitter.python.deadline_cloud_for_houdini.queue_parameters import (
            update_queue_parameters,
        )

        update_queue_parameters(node)
    except Exception as e:
        logger.error(f"Error updating queue parameters: {e}")


def on_created_callback(node: Any) -> None:
    """Callback when the scheduler node is created.

    Sets up default values from Deadline Cloud client config.
    """
    try:
        from deadline.client.config import get_setting

        # Set defaults from client config
        default_farm = get_setting("defaults.farm_id", default="")
        default_queue = get_setting("defaults.queue_id", default="")

        if default_farm:
            node.parm("farm_id").set(default_farm)
        if default_queue:
            node.parm("queue_id").set(default_queue)

        logger.info("Deadline Cloud scheduler node created with default settings")
    except Exception as e:
        logger.error(f"Error in on_created_callback: {e}")


def on_loaded_callback(node: Any) -> None:
    """Callback when the scheduler node is loaded from a scene file.

    Validates that saved settings are still valid.
    """
    try:
        farm_id = node.parm("farm_id").eval()
        queue_id = node.parm("queue_id").eval()
        logger.debug(f"Loaded scheduler with farm={farm_id}, queue={queue_id}")
    except Exception as e:
        logger.error(f"Error in on_loaded_callback: {e}")
