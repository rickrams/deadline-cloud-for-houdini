# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Data models for PDG integration."""

from dataclasses import dataclass, field
from typing import Optional

from deadline.client.job_bundle.submission import AssetReferences

from .constants import (
    DEFAULT_MAX_CONCURRENT_JOBS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PRIORITY,
    DEFAULT_JOB_NAME_PREFIX,
)


@dataclass
class SchedulerConfig:
    """Configuration from the Houdini scheduler node parameters."""

    farm_id: str = ""
    queue_id: str = ""
    priority: int = DEFAULT_PRIORITY
    job_name_prefix: str = DEFAULT_JOB_NAME_PREFIX
    job_description: str = ""
    aws_profile: str = "default"
    max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS
    poll_interval: int = DEFAULT_POLL_INTERVAL


@dataclass
class PackageResult:
    """Output of the scene packaging step."""

    hip_file: str
    top_network_path: str
    scheduler_node_path: str
    asset_references: AssetReferences = field(default_factory=AssetReferences)
    warnings: list[str] = field(default_factory=list)


@dataclass
class JobStatus:
    """Status of a Deadline Cloud job."""

    job_id: str
    status: str  # CREATING, READY, RUNNING, SUCCEEDED, FAILED, CANCELED
    status_message: str = ""
    task_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class WorkItemMapping:
    """Maps a PDG work item to its Deadline Cloud child job."""

    work_item_id: int
    top_node_name: str
    child_job_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, SUBMITTED, SUCCEEDED, FAILED, CANCELED
    output_files: list[str] = field(default_factory=list)
    output_attributes: dict[str, str] = field(default_factory=dict)
