#!/usr/bin/env python
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Script to create the Deadline Cloud PDG Scheduler HDA.

Run this script inside Houdini's Python shell or via hython:
    hython create_scheduler_hda.py

Or from Houdini's Python Source Editor:
    exec(open('/path/to/create_scheduler_hda.py').read())
"""

import os
import hou

# Configuration
HDA_NAME = "deadline_cloud_scheduler"
HDA_LABEL = "Deadline Cloud"
HDA_FILENAME = "deadline_cloud_scheduler.hda"
NODE_TYPE_NAME = "deadline_cloud_scheduler"


def create_scheduler_hda(output_dir: str = None) -> str:
    """Create the Deadline Cloud PDG Scheduler HDA.
    
    Args:
        output_dir: Directory to save the HDA. Defaults to current directory.
        
    Returns:
        Path to the created HDA file.
    """
    if output_dir is None:
        output_dir = os.getcwd()
    
    hda_path = os.path.join(output_dir, HDA_FILENAME)
    
    # Create a temporary TOP network to work in
    obj = hou.node("/obj")
    topnet = obj.createNode("topnet", "temp_topnet_for_hda")
    
    try:
        # Create a Python Scheduler as the base
        base_scheduler = topnet.createNode("pythonscheduler", "base_scheduler")
        
        # Create the HDA from this node
        hda_node = base_scheduler.createDigitalAsset(
            name=NODE_TYPE_NAME,
            hda_file_name=hda_path,
            description=HDA_LABEL,
            min_num_inputs=0,
            max_num_inputs=0,
        )
        
        # Get the HDA definition to modify it
        hda_def = hda_node.type().definition()
        
        # Set up the parameter interface
        ptg = hda_node.parmTemplateGroup()
        
        # Clear existing parameters (keep only essential scheduler ones)
        # We'll add our custom parameters
        
        # === Deadline Cloud Settings Folder ===
        dc_folder = hou.FolderParmTemplate(
            "deadline_cloud_settings",
            "Deadline Cloud",
            folder_type=hou.folderType.Tabs,
            parm_templates=[
                hou.StringParmTemplate(
                    "farm_id", "Farm", 1,
                    default_value=("",),
                    help="AWS Deadline Cloud Farm ID",
                    string_type=hou.stringParmType.Regular,
                ),
                hou.StringParmTemplate(
                    "queue_id", "Queue", 1,
                    default_value=("",),
                    help="AWS Deadline Cloud Queue ID",
                    string_type=hou.stringParmType.Regular,
                ),
                hou.IntParmTemplate(
                    "priority", "Priority", 1,
                    default_value=(50,),
                    min=0, max=100,
                    min_is_strict=True, max_is_strict=True,
                    help="Job priority (0-100, higher is more urgent)",
                ),
            ],
        )
        ptg.append(dc_folder)
        
        # === Job Settings Folder ===
        job_folder = hou.FolderParmTemplate(
            "job_settings",
            "Job Settings",
            folder_type=hou.folderType.Tabs,
            parm_templates=[
                hou.StringParmTemplate(
                    "job_name_prefix", "Job Name Prefix", 1,
                    default_value=("PDG",),
                    help="Prefix for submitted job names",
                ),
                hou.StringParmTemplate(
                    "job_description", "Description", 1,
                    default_value=("",),
                    help="Description for submitted jobs",
                ),
                hou.StringParmTemplate(
                    "aws_profile", "AWS Profile", 1,
                    default_value=("default",),
                    help="AWS profile name for credentials",
                ),
            ],
        )
        ptg.append(job_folder)
        
        # === Advanced Settings Folder ===
        adv_folder = hou.FolderParmTemplate(
            "advanced_settings",
            "Advanced",
            folder_type=hou.folderType.Tabs,
            parm_templates=[
                hou.IntParmTemplate(
                    "max_concurrent_jobs", "Max Concurrent Jobs", 1,
                    default_value=(10,),
                    min=1, max=100,
                    help="Maximum number of concurrent child jobs",
                ),
                hou.IntParmTemplate(
                    "poll_interval", "Poll Interval (seconds)", 1,
                    default_value=(30,),
                    min=5, max=300,
                    help="Seconds between status polls",
                ),
            ],
        )
        ptg.append(adv_folder)
        
        # Apply the parameter template group
        hda_node.setParmTemplateGroup(ptg)
        
        # Set up the Python module for scheduler callbacks
        python_module = '''
# Deadline Cloud PDG Scheduler - Python Module
# This module implements the PDG scheduler callbacks

import os

_scheduler = None

def _get_scheduler():
    """Get or create the scheduler instance."""
    global _scheduler
    if _scheduler is None:
        from deadline.houdini_submitter.python.deadline_cloud_for_houdini.pdg.scheduler import (
            DeadlineCloudScheduler,
        )
        import hou
        _scheduler = DeadlineCloudScheduler(hou_module=hou)
    return _scheduler

def onSchedule(self, work_item):
    """Called by PDG when a work item is ready to be scheduled."""
    scheduler = _get_scheduler()
    return scheduler.on_schedule(work_item)

def onStart(self):
    """Called when the scheduler starts cooking."""
    global _scheduler
    _scheduler = None  # Reset for fresh start
    scheduler = _get_scheduler()
    return scheduler.on_start(self)

def onStop(self):
    """Called when the scheduler stops."""
    scheduler = _get_scheduler()
    result = scheduler.on_stop()
    
    # Log the job ID for the user
    if scheduler.orchestrator_job_id:
        print(f"\\n{'='*60}")
        print(f"Deadline Cloud Orchestrator Job Submitted!")
        print(f"Job ID: {scheduler.orchestrator_job_id}")
        print(f"Farm: {scheduler.config.farm_id}")
        print(f"Queue: {scheduler.config.queue_id}")
        print(f"{'='*60}\\n")
    
    return result

def onStartCook(self, static, cook_set):
    """Called when a cook starts."""
    return True

def onStopCook(self, cancel):
    """Called when a cook stops."""
    return True

def onConfigureFromParameters(self):
    """Called to configure the scheduler from node parameters."""
    scheduler = _get_scheduler()
    return scheduler.configure_from_node(self)
'''
        
        # Save the Python module to the HDA
        hda_def.addSection("PythonModule", python_module)
        
        # Set the Python module as the script
        hda_def.setExtraFileOption("PythonModule/IsPython", True)
        
        # Add event handlers
        event_handlers = '''
PythonModule/onSchedule	onSchedule
PythonModule/onStart	onStart
PythonModule/onStop	onStop
PythonModule/onStartCook	onStartCook
PythonModule/onStopCook	onStopCook
'''
        
        # Set node type properties
        hda_def.setIcon("MISC_deadline")  # Or use a custom icon
        hda_def.setDefaultColor(hou.Color((0.2, 0.4, 0.8)))  # Blue color
        
        # Save the HDA
        hda_def.save(hda_path)
        
        print(f"Created HDA: {hda_path}")
        return hda_path
        
    finally:
        # Clean up the temporary network
        topnet.destroy()


def install_hda(hda_path: str) -> None:
    """Install the HDA so it's available in Houdini.
    
    Args:
        hda_path: Path to the HDA file.
    """
    hou.hda.installFile(hda_path)
    print(f"Installed HDA: {hda_path}")
    print(f"The 'Deadline Cloud' scheduler is now available in TOP networks.")


def main():
    """Main entry point."""
    import sys
    
    # Determine output directory
    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
    else:
        # Default to otls directory in the project
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(
            script_dir, 
            "src", "deadline", "houdini_submitter", "otls"
        )
        
        # Create directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
    
    # Create the HDA
    hda_path = create_scheduler_hda(output_dir)
    
    # Install it
    install_hda(hda_path)
    
    print("\nDone! You can now:")
    print("1. Open a TOP network")
    print("2. Press Tab and search for 'Deadline Cloud'")
    print("3. Create the scheduler node and configure your farm/queue")


if __name__ == "__main__":
    main()
