# In job_manager.py
"""
Atlas Job Manager - Persistence Layer for Workflow Jobs

This module handles the creation, storage, and retrieval of job records.
Each job execution is persisted to disk in a structured folder format
matching the Unity plugin's pattern for cross-platform consistency.

Folder Structure:
    {addon_dir}/atlas_jobs/{workflow_name}/{timestamp}_{job_id_short}/
        ├── job.json          # Full job metadata
        ├── inputs/           # Copies of input files
        └── outputs/          # Downloaded output files

Job Lifecycle:
    1. create_job() - Called when workflow starts, creates folder + initial job.json
    2. update_job() - Called during execution to update status/progress
    3. complete_job() - Called when done, saves final state + outputs
    4. fail_job() - Called on error, saves error details
"""

import json
import os
import shutil
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional
from pathlib import Path

log = logging.getLogger("atlas_workflow")


def get_addon_root_dir() -> str:
    """Return the installable addon package root directory."""
    module_dir = os.path.dirname(__file__)
    if os.path.basename(module_dir) == "atlas":
        return os.path.dirname(module_dir)
    return module_dir


# ---------------------------------------------------------------------------
# Enums matching Unity's job status values
# ---------------------------------------------------------------------------

class JobStatus(IntEnum):
    """Overall job status (matches Unity's Status enum)"""
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    CANCELLED = 4


class ExecutionStatus(IntEnum):
    """API execution status (matches Unity's ExecutionStatus enum)"""
    NONE = 0
    PENDING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ParamSnapshot:
    """Snapshot of a parameter's value at job creation/completion time"""
    ParamId: str
    Label: str
    ParamType: str  # "boolean", "number", "string", "image", "mesh"
    SourceType: int = 0  # 0 = direct value, 1 = file
    BoolValue: bool = False
    NumberValue: float = 0.0
    StringValue: Optional[str] = None
    ImageValue: Optional[str] = None  # Image name in Blender
    MeshValue: Optional[str] = None   # Object name in Blender
    FilePath: Optional[str] = None    # Path to file (for inputs/outputs)


@dataclass
class JobRecord:
    """
    Complete job record matching Unity's job.json schema.
    
    This structure ensures workflow identity across platforms -
    the same job data format is used in Unity, Unreal, and Blender.
    """
    # --- Identity ---
    JobId: str
    WorkflowId: str  # api_id
    WorkflowName: str
    WorkflowVersion: str
    
    # --- Timestamps ---
    CreatedAtUtc: str  # ISO8601 format
    CompletedAtUtc: Optional[str] = None
    
    # --- Status ---
    Status: int = JobStatus.PENDING  # JobStatus enum value
    ExecutionStatus: int = ExecutionStatus.NONE
    ExecutionId: Optional[str] = None
    Progress01: float = 0.0  # 0.0 to 1.0
    
    # --- Error Info ---
    ErrorMessage: Optional[str] = None
    ErrorNodeName: Optional[str] = None
    ErrorNodeType: Optional[str] = None
    ErrorNodeId: Optional[str] = None
    
    # --- Parameter Snapshots ---
    InputsSnapshot: List[Dict[str, Any]] = field(default_factory=list)
    OutputsSnapshot: List[Dict[str, Any]] = field(default_factory=list)
    
    # --- File System ---
    JobFolderPath: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "JobRecord":
        """Create JobRecord from dictionary"""
        return JobRecord(**data)
    
    def save(self) -> None:
        """Save job record to job.json in the job folder"""
        if not self.JobFolderPath:
            raise ValueError("JobFolderPath not set")
        
        job_file = os.path.join(self.JobFolderPath, "job.json")
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        
        log.debug(f"[Atlas Jobs] Saved job {self.JobId[:8]} to {job_file}")


# ---------------------------------------------------------------------------
# Job Manager Functions
# ---------------------------------------------------------------------------

def get_jobs_root_dir() -> str:
    """
    Get the root directory for all job folders.
    Creates the directory if it doesn't exist.
    
    Returns:
        Path like: {addon_dir}/atlas_jobs/
    """
    addon_dir = get_addon_root_dir()
    jobs_dir = os.path.join(addon_dir, "atlas_jobs")
    
    if not os.path.exists(jobs_dir):
        os.makedirs(jobs_dir)
        log.info(f"[Atlas Jobs] Created jobs directory: {jobs_dir}")
    
    return jobs_dir


def _sanitize_folder_name(name: str) -> str:
    """Sanitize a string for use as a folder name"""
    # Replace problematic characters with underscores
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Limit length
    return name[:50]


def create_job(
    workflow_id: str,
    workflow_name: str,
    workflow_version: str,
    inputs_snapshot: List[ParamSnapshot]
) -> JobRecord:
    """
    Create a new job record and folder structure.
    
    This is called at the START of workflow execution.
    
    Args:
        workflow_id: The API ID of the workflow
        workflow_name: Human-readable workflow name
        workflow_version: API version string
        inputs_snapshot: List of input parameter snapshots
        
    Returns:
        JobRecord with folder created and initial job.json saved
    """
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    job_id_short = job_id[:8]
    
    # Create timestamp for folder name
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    created_at = now.isoformat()
    
    # Build folder path: atlas_jobs/{workflow_name}/{timestamp}_{job_id_short}/
    jobs_root = get_jobs_root_dir()
    workflow_folder = os.path.join(jobs_root, _sanitize_folder_name(workflow_name))
    job_folder_name = f"{timestamp}_{job_id_short}"
    job_folder = os.path.join(workflow_folder, job_folder_name)
    
    # Create folder structure
    os.makedirs(job_folder, exist_ok=True)
    os.makedirs(os.path.join(job_folder, "inputs"), exist_ok=True)
    os.makedirs(os.path.join(job_folder, "outputs"), exist_ok=True)
    
    log.info(f"[Atlas Jobs] Created job folder: {job_folder}")
    
    # Convert ParamSnapshot objects to dicts
    inputs_dict = [asdict(p) if isinstance(p, ParamSnapshot) else p for p in inputs_snapshot]
    
    # Create job record
    job = JobRecord(
        JobId=job_id,
        WorkflowId=workflow_id,
        WorkflowName=workflow_name,
        WorkflowVersion=workflow_version,
        CreatedAtUtc=created_at,
        Status=JobStatus.PENDING,
        ExecutionStatus=ExecutionStatus.NONE,
        InputsSnapshot=inputs_dict,
        OutputsSnapshot=[],
        JobFolderPath=job_folder,
    )
    
    # Save initial state
    job.save()
    
    return job


def update_job_status(
    job: JobRecord,
    status: JobStatus,
    execution_status: ExecutionStatus,
    execution_id: Optional[str] = None,
    progress: float = 0.0
) -> None:
    """
    Update job status during execution.
    
    Args:
        job: The JobRecord to update
        status: New job status
        execution_status: New execution status
        execution_id: API execution ID (if available)
        progress: Progress 0.0 to 1.0
    """
    job.Status = status
    job.ExecutionStatus = execution_status
    if execution_id:
        job.ExecutionId = execution_id
    job.Progress01 = progress
    job.save()


def complete_job(
    job: JobRecord,
    outputs_snapshot: List[ParamSnapshot]
) -> None:
    """
    Mark job as completed and save final state.
    
    Args:
        job: The JobRecord to complete
        outputs_snapshot: List of output parameter snapshots with values/paths
    """
    now = datetime.now(timezone.utc)
    
    job.Status = JobStatus.COMPLETED
    job.ExecutionStatus = ExecutionStatus.COMPLETED
    job.CompletedAtUtc = now.isoformat()
    job.Progress01 = 1.0
    
    # Convert ParamSnapshot objects to dicts
    outputs_dict = [asdict(p) if isinstance(p, ParamSnapshot) else p for p in outputs_snapshot]
    job.OutputsSnapshot = outputs_dict
    
    job.save()
    log.info(f"[Atlas Jobs] Job {job.JobId[:8]} completed successfully")


def fail_job(
    job: JobRecord,
    error_message: str,
    node_name: Optional[str] = None,
    node_type: Optional[str] = None,
    node_id: Optional[str] = None
) -> None:
    """
    Mark job as failed and save error details.
    
    Args:
        job: The JobRecord to mark as failed
        error_message: The error message
        node_name: Name of the node that failed (if available)
        node_type: Type of the node that failed (if available)
        node_id: ID of the node that failed (if available)
    """
    now = datetime.now(timezone.utc)
    
    job.Status = JobStatus.FAILED
    job.ExecutionStatus = ExecutionStatus.FAILED
    job.CompletedAtUtc = now.isoformat()
    job.ErrorMessage = error_message
    job.ErrorNodeName = node_name
    job.ErrorNodeType = node_type
    job.ErrorNodeId = node_id
    
    job.save()
    log.info(f"[Atlas Jobs] Job {job.JobId[:8]} failed: {error_message}")


def copy_input_file_to_job(job: JobRecord, param_id: str, source_path: str) -> str:
    """
    Copy an input file to the job's inputs folder.
    
    Args:
        job: The JobRecord
        param_id: Parameter ID for naming
        source_path: Path to the source file
        
    Returns:
        Path to the copied file in the job folder
    """
    if not os.path.exists(source_path):
        log.warning(f"[Atlas Jobs] Input file not found: {source_path}")
        return source_path
    
    # Determine destination path
    ext = os.path.splitext(source_path)[1]
    dest_filename = f"Input_{param_id}{ext}"
    dest_path = os.path.join(job.JobFolderPath, "inputs", dest_filename)
    
    # Copy file
    shutil.copy2(source_path, dest_path)
    log.debug(f"[Atlas Jobs] Copied input {param_id} to {dest_path}")
    
    return dest_path


def save_output_file_to_job(job: JobRecord, param_id: str, source_path: str) -> str:
    """
    Copy/move an output file to the job's outputs folder.
    
    Args:
        job: The JobRecord
        param_id: Parameter ID for naming
        source_path: Path to the downloaded output file
        
    Returns:
        Path to the file in the job folder
    """
    if not os.path.exists(source_path):
        log.warning(f"[Atlas Jobs] Output file not found: {source_path}")
        return source_path
    
    # Determine destination path
    ext = os.path.splitext(source_path)[1]
    dest_filename = f"Output_{param_id}{ext}"
    dest_path = os.path.join(job.JobFolderPath, "outputs", dest_filename)
    
    # Copy file (keep original in temp for immediate use)
    shutil.copy2(source_path, dest_path)
    log.debug(f"[Atlas Jobs] Saved output {param_id} to {dest_path}")
    
    return dest_path


# ---------------------------------------------------------------------------
# Job Retrieval Functions
# ---------------------------------------------------------------------------

def get_job(job_folder_path: str) -> Optional[JobRecord]:
    """
    Load a job record from a job folder.
    
    Args:
        job_folder_path: Path to the job folder
        
    Returns:
        JobRecord or None if not found/invalid
    """
    job_file = os.path.join(job_folder_path, "job.json")
    
    if not os.path.exists(job_file):
        log.warning(f"[Atlas Jobs] job.json not found in {job_folder_path}")
        return None
    
    try:
        with open(job_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JobRecord.from_dict(data)
    except Exception as e:
        log.error(f"[Atlas Jobs] Failed to load job from {job_file}: {e}")
        return None


def get_all_jobs() -> List[JobRecord]:
    """
    Scan all job folders and return all job records.
    
    Returns:
        List of JobRecord objects, sorted by creation time (newest first)
    """
    jobs_root = get_jobs_root_dir()
    jobs = []
    
    # Iterate through workflow folders
    if not os.path.exists(jobs_root):
        return jobs
    
    for workflow_name in os.listdir(jobs_root):
        workflow_path = os.path.join(jobs_root, workflow_name)
        if not os.path.isdir(workflow_path):
            continue
        
        # Iterate through job folders within each workflow
        for job_folder_name in os.listdir(workflow_path):
            job_folder = os.path.join(workflow_path, job_folder_name)
            if not os.path.isdir(job_folder):
                continue
            
            job = get_job(job_folder)
            if job:
                jobs.append(job)
    
    # Sort by creation time (newest first)
    jobs.sort(key=lambda j: j.CreatedAtUtc, reverse=True)
    
    log.debug(f"[Atlas Jobs] Found {len(jobs)} jobs")
    return jobs


def get_jobs_for_workflow(workflow_name: str) -> List[JobRecord]:
    """
    Get all jobs for a specific workflow.
    
    Args:
        workflow_name: Name of the workflow
        
    Returns:
        List of JobRecord objects for that workflow
    """
    all_jobs = get_all_jobs()
    return [j for j in all_jobs if j.WorkflowName == workflow_name]


def delete_job(job: JobRecord) -> bool:
    """
    Delete a job and its folder.
    
    Args:
        job: The JobRecord to delete
        
    Returns:
        True if successful, False otherwise
    """
    if not job.JobFolderPath or not os.path.exists(job.JobFolderPath):
        log.warning(f"[Atlas Jobs] Job folder not found: {job.JobFolderPath}")
        return False
    
    try:
        shutil.rmtree(job.JobFolderPath)
        log.info(f"[Atlas Jobs] Deleted job {job.JobId[:8]}")
        return True
    except Exception as e:
        log.error(f"[Atlas Jobs] Failed to delete job: {e}")
        return False


def get_jobs_storage_size() -> tuple[int, int]:
    """
    Calculate total storage used by jobs.
    
    Returns:
        Tuple of (file_count, total_bytes)
    """
    jobs_root = get_jobs_root_dir()
    total_size = 0
    file_count = 0
    
    for dirpath, dirnames, filenames in os.walk(jobs_root):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            total_size += os.path.getsize(filepath)
            file_count += 1
    
    return file_count, total_size


def cleanup_old_jobs(max_age_days: int = 30) -> int:
    """
    Delete jobs older than specified days.
    
    Args:
        max_age_days: Maximum age in days
        
    Returns:
        Number of jobs deleted
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 24 * 60 * 60)
    deleted_count = 0
    
    for job in get_all_jobs():
        try:
            created = datetime.fromisoformat(job.CreatedAtUtc.replace('Z', '+00:00'))
            if created.timestamp() < cutoff:
                if delete_job(job):
                    deleted_count += 1
        except Exception as e:
            log.warning(f"[Atlas Jobs] Error checking job age: {e}")
    
    if deleted_count > 0:
        log.info(f"[Atlas Jobs] Cleaned up {deleted_count} old jobs")
    
    return deleted_count
