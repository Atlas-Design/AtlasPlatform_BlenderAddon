# In api_client.py
"""
Atlas Platform API Client

A clean abstraction for communicating with the Atlas Platform API.
Implements the async execution pattern with polling.

API Flow:
1. upload_file() - Upload binary files (images, meshes) → returns file_id
2. execute_async() - Submit workflow execution → returns execution_id
3. poll_status() - Check execution status → returns status_data
4. download_file() - Download output files by file_id

All functions are designed to be called from a background thread.
"""

import os
import logging
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Try to import requests
try:
    import requests
except ImportError:
    requests = None

log = logging.getLogger("atlas_workflow")


# ---------------------------------------------------------------------------
# Data Classes & Enums
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    """Status values returned by the API"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExecutionError:
    """Structured error information from a failed execution"""
    message: str
    node_name: Optional[str] = None
    node_type: Optional[str] = None
    node_id: Optional[str] = None

    def format_message(self) -> str:
        """Format error with node context for display"""
        msg = self.message
        if self.node_name or self.node_type:
            node_info = self.node_name or self.node_type
            msg += f" (node: {node_info})"
        if self.node_id:
            msg += f" [id: {self.node_id[:8]}...]"
        return msg


@dataclass
class StatusResult:
    """Result from polling the status endpoint"""
    status: ExecutionStatus
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[ExecutionError] = None
    progress: float = 0.0  # 0.0 to 1.0, if available from API

    @property
    def is_complete(self) -> bool:
        return self.status == ExecutionStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == ExecutionStatus.FAILED

    @property
    def is_terminal(self) -> bool:
        return self.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED)


# ---------------------------------------------------------------------------
# API Client Class
# ---------------------------------------------------------------------------

class AtlasAPIClient:
    """
    Client for the Atlas Platform API.
    
    Usage:
        client = AtlasAPIClient(base_url="https://api.prod.atlas.design", version="0.1")
        
        # Upload files first
        file_id = client.upload_file(api_id, "/path/to/image.png")
        
        # Execute workflow
        execution_id = client.execute_async(api_id, {"input_image": file_id, "prompt": "hello"})
        
        # Poll for completion
        while True:
            result = client.poll_status(execution_id)
            if result.is_terminal:
                break
            time.sleep(2.0)
        
        # Download outputs
        if result.is_complete:
            client.download_file(api_id, result.outputs["output_mesh"], "/path/to/output.glb")
    """

    def __init__(self, base_url: str, version: str = "0.1", timeout: int = 300):
        """
        Initialize the API client.
        
        Args:
            base_url: The API base URL (e.g., "https://api.prod.atlas.design")
            version: API version string (e.g., "0.1")
            timeout: Request timeout in seconds
        """
        if requests is None:
            raise RuntimeError("The 'requests' library is not installed. Please install it to use the Atlas API.")
        
        # Normalize base URL
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith("http"):
            self.base_url = f"https://{self.base_url}"
        
        self.version = version
        self.timeout = timeout

    def _build_url(self, *parts: str) -> str:
        """Build a full URL from path parts"""
        return f"{self.base_url}/{self.version}/{'/'.join(parts)}"

    # ---------------------------------------------------------------------------
    # API Methods
    # ---------------------------------------------------------------------------

    def upload_file(self, api_id: str, file_path: str) -> str:
        """
        Upload a file to the API.
        
        Args:
            api_id: The workflow API ID
            file_path: Path to the file to upload
            
        Returns:
            The file_id for use in execute_async payload
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            requests.HTTPError: If the upload fails
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        url = self._build_url("upload", api_id)
        file_name = os.path.basename(file_path)

        log.debug(f"[Atlas API] Uploading {file_name} to {url}")

        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            response = requests.post(url, files=files, timeout=self.timeout)

        response.raise_for_status()
        result = response.json()
        file_id = result.get("file_id")

        log.debug(f"[Atlas API] Upload complete: {file_id}")
        return file_id

    def execute_async(self, api_id: str, payload: Dict[str, Any]) -> str:
        """
        Submit a workflow for async execution.
        
        Args:
            api_id: The workflow API ID
            payload: Dictionary of input parameters (primitives and file_ids)
            
        Returns:
            The execution_id for polling status
            
        Raises:
            requests.HTTPError: If submission fails
        """
        url = self._build_url("api_execute_async", api_id)

        log.debug(f"[Atlas API] Executing workflow {api_id}")
        log.debug(f"[Atlas API] Payload: {payload}")

        response = requests.post(url, json=payload, timeout=self.timeout)

        if not response.ok:
            error_text = response.text
            log.error(f"[Atlas API] Execution failed ({response.status_code}): {error_text}")
            raise requests.HTTPError(
                f"API submission failed ({response.status_code}): {error_text}",
                response=response
            )

        result = response.json()
        execution_id = result.get("execution_id")

        log.debug(f"[Atlas API] Execution started: {execution_id}")
        return execution_id

    def poll_status(self, execution_id: str) -> StatusResult:
        """
        Poll the status of an async execution.
        
        Args:
            execution_id: The execution ID from execute_async()
            
        Returns:
            StatusResult with current status, outputs (if complete), or error (if failed)
            
        Raises:
            requests.HTTPError: If the status request fails
        """
        url = self._build_url("api_status", execution_id)

        log.debug(f"[Atlas API] Polling status for {execution_id}")

        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()

        data = response.json()
        status_str = data.get("status", "").lower()

        log.debug(f"[Atlas API] Status: {status_str}")

        # Parse status
        try:
            status = ExecutionStatus(status_str)
        except ValueError:
            log.warning(f"[Atlas API] Unknown status: {status_str}")
            # Treat unknown as still running
            return StatusResult(status=ExecutionStatus.RUNNING)

        # Handle completed
        if status == ExecutionStatus.COMPLETED:
            outputs = data.get("result", {}).get("outputs", {})
            return StatusResult(
                status=status,
                outputs=outputs,
                progress=1.0
            )

        # Handle failed
        if status == ExecutionStatus.FAILED:
            error_data = data.get("error", {})
            error = ExecutionError(
                message=error_data.get("error", "Unknown error"),
                node_name=error_data.get("node_name"),
                node_type=error_data.get("node_type"),
                node_id=error_data.get("node_id"),
            )
            return StatusResult(
                status=status,
                error=error,
                progress=0.0
            )

        # Still running/pending
        progress = data.get("progress", 0.0)
        return StatusResult(
            status=status,
            progress=progress
        )

    def download_file(self, api_id: str, file_id: str, output_path: str) -> str:
        """
        Download an output file from the API.
        
        Args:
            api_id: The workflow API ID
            file_id: The file_id from the outputs
            output_path: Local path to save the file
            
        Returns:
            The output_path (for convenience)
            
        Raises:
            requests.HTTPError: If download fails
        """
        url = self._build_url("download_binary_result", api_id, file_id)

        log.debug(f"[Atlas API] Downloading {file_id} to {output_path}")

        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()

        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "wb") as f:
            f.write(response.content)

        log.debug(f"[Atlas API] Download complete: {output_path}")
        return output_path


# ---------------------------------------------------------------------------
# Convenience function for quick client creation
# ---------------------------------------------------------------------------

def create_client(base_url: str, version: str = "0.1", timeout: int = 300) -> AtlasAPIClient:
    """Create an AtlasAPIClient instance"""
    return AtlasAPIClient(base_url=base_url, version=version, timeout=timeout)


# ---------------------------------------------------------------------------
# Module-level check for requests availability
# ---------------------------------------------------------------------------

def is_requests_available() -> bool:
    """Check if the requests library is available"""
    return requests is not None
