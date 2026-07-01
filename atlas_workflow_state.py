# In atlas_workflow_state.py
"""
Manages the state of a workflow within the Blender UI.

This file defines the data structures that hold the current state of an active
workflow. This includes all input and output parameters, their current values,
and the status of any running job.

The state is managed using Blender's PropertyGroup system, which allows the
data to be integrated directly into Blender's UI and data system. The main
classes are:

- AtlasWorkflowParamState: Holds the state for a single input or output parameter.
- AtlasWorkflowState: The global container for the entire workflow's state,
  including collections of input and output parameters and job status.

Helper functions are provided to synchronize this state with an abstract
WorkflowDefinition.
"""
import os

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

# Adjust this import to wherever you put workflow_definition.py
from .workflow_definition import WorkflowDefinition, ParamType
from . import workflow_manager


# -------------------------------------------------------------------
# --- Property Groups ---
# -------------------------------------------------------------------

class AtlasJobHistoryItem(PropertyGroup):
    """
    Represents a single job in the history list.
    Lightweight summary data loaded from job.json files.
    """
    job_id: StringProperty(name="Job ID")
    workflow_name: StringProperty(name="Workflow Name")
    created_at: StringProperty(name="Created At")  # ISO format for sorting
    created_at_display: StringProperty(name="Display Time")  # "just now", "5m ago", etc.
    status: IntProperty(name="Status", default=0)  # 0=pending, 1=running, 2=completed, 3=failed
    job_folder_path: StringProperty(name="Job Folder Path", subtype='DIR_PATH')
    
    def get_status_icon(self) -> str:
        """Return appropriate icon for status."""
        if self.status == 2:  # Completed
            return 'CHECKMARK'
        elif self.status == 3:  # Failed
            return 'ERROR'
        elif self.status == 1:  # Running
            return 'TIME'
        return 'PAUSE'  # Pending
    
    def get_status_name(self) -> str:
        """Return status as string."""
        names = {0: "Pending", 1: "Running", 2: "Completed", 3: "Failed", 4: "Cancelled"}
        return names.get(self.status, "Unknown")


class AtlasRunningJobItem(PropertyGroup):
    """
    Represents a single running job in the Running Jobs panel.
    Multiple jobs can run concurrently on the server.
    """
    job_id: StringProperty(
        name="Job ID",
        description="Unique identifier for this running job"
    )
    workflow_name: StringProperty(
        name="Workflow Name",
        description="Name of the workflow being executed"
    )
    status: StringProperty(
        name="Status",
        description="Current status message",
        default="Initializing..."
    )
    progress: FloatProperty(
        name="Progress",
        description="Job progress 0.0 to 1.0",
        default=0.0, min=0.0, max=1.0
    )
    started_at: StringProperty(
        name="Started At",
        description="Time when job started (HH:MM:SS)"
    )
    elapsed_time: StringProperty(
        name="Elapsed Time",
        description="Time elapsed since start",
        default="0.0s"
    )
    current_phase: StringProperty(
        name="Current Phase",
        description="Current execution phase: pending, running, uploading, downloading",
        default="pending"
    )


class AtlasWorkflowParamState(PropertyGroup):
    """
    Holds the current value and configuration for a single workflow parameter.

    This class stores the data for one input or output, such as its ID, type,
    label, and current value. It is used within a CollectionProperty in the
    main AtlasWorkflowState.
    """

    # --- Schema / Identity ---
    # These properties identify the parameter based on the workflow definition.
    param_id: StringProperty(
        name="Param ID",
        description="Stable ID from the workflow JSON definition",
    )
    label: StringProperty(
        name="Label",
        description="UI label for this parameter",
    )
    param_type: EnumProperty(
        name="Type",
        description="The data type of this parameter",
        items=[
            ("boolean", "Boolean", "A true/false value"),
            ("number", "Number", "A floating-point or integer value"),
            ("string", "String", "A text value"),
            ("image", "Image", "A Blender Image datablock"),
            ("mesh", "Mesh", "A Blender Mesh datablock"),
        ],
    )

    # --- Input Source Configuration (for Image/Mesh) ---
    # Determines whether the data comes from the current scene or an external file.
    source_type: EnumProperty(
        name="Source",
        description="Where to get the data for this input",
        items=[
            ('SCENE', 'Scene', 'Use a datablock from the current Blender file'),
            ('FILE', 'File', 'Use an external file from disk'),
        ],
        default='SCENE',
    )
    file_path: StringProperty(
        name="File Path",
        description="Path to the external file for this parameter",
        subtype='FILE_PATH',
    )

    # --- Parameter Value Storage ---
    # Properties to store the actual values, used based on 'param_type'.
    bool_value: BoolProperty(name="Bool Value")
    number_value: FloatProperty(name="Number Value")
    int_value: IntProperty(name="Int Value")
    string_value: StringProperty(name="String Value")

    # --- Blender Datablock and File References ---
    # Stores names of Blender data-blocks or temporary file paths.
    image_name: StringProperty(
        name="Image Name",
        description="Name of the Image datablock used/produced by this param",
    )
    mesh_name: StringProperty(
        name="Mesh Name",
        description="Name of the Mesh datablock used/produced by this param",
    )
    temp_file_path: StringProperty(
        name="Temp File Path",
        description="Internal: Path to a downloaded temporary file for this output",
        subtype='FILE_PATH',
    )


class AtlasWorkflowState(PropertyGroup):
    """
    Global state for the currently loaded workflow in Blender.

    This class acts as a central container for all workflow-related data,
    including metadata, collections of input and output parameters, and job
    status information. An instance of this class is registered on Blender's
    WindowManager, making it accessible throughout the UI.
    """

    # --- Workflow Metadata ---
    active_api_id: StringProperty()
    active_name: StringProperty()
    base_url: StringProperty()
    version: StringProperty()

    # --- Parameter Collections ---
    inputs: CollectionProperty(
        type=AtlasWorkflowParamState,
        description="Collection of input parameters for the workflow"
    )
    outputs: CollectionProperty(
        type=AtlasWorkflowParamState,
        description="Collection of output parameters for the workflow"
    )

    # --- Running Jobs (supports multiple concurrent jobs) ---
    running_jobs: CollectionProperty(
        type=AtlasRunningJobItem,
        description="Collection of currently running jobs"
    )
    
    # --- Job History ---
    job_history: CollectionProperty(
        type=AtlasJobHistoryItem,
        description="Collection of past jobs for history panel"
    )
    job_history_index: IntProperty(
        name="Selected Job",
        description="Index of selected job in history list",
        default=-1
    )
    
    # Filter properties with update callbacks to trigger refresh
    def _on_filter_changed(self, context):
        """Called when any filter changes - triggers UI refresh."""
        # Force redraw of the UI
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    filter_status: EnumProperty(
        name="Status Filter",
        description="Filter jobs by status",
        items=[
            ('ALL', "All", "Show all jobs"),
            ('COMPLETED', "Success", "Show only completed jobs"),
            ('FAILED', "Failed", "Show only failed jobs"),
            ('RUNNING', "Running", "Show only running jobs"),
        ],
        default='ALL',
        update=_on_filter_changed
    )
    
    def _get_workflow_filter_items(self, context):
        """Dynamically generate workflow filter items from job history."""
        items = [('ALL', "All Workflows", "Show all workflows")]
        
        # Get unique workflow names from job history
        seen = set()
        for job in self.job_history:
            if job.workflow_name and job.workflow_name not in seen:
                seen.add(job.workflow_name)
                items.append((job.workflow_name, job.workflow_name, f"Show only {job.workflow_name} jobs"))
        
        return items
    
    filter_workflow: EnumProperty(
        name="Workflow Filter",
        description="Filter by workflow type",
        items=_get_workflow_filter_items,
        update=_on_filter_changed
    )
    
    filter_date: EnumProperty(
        name="Date Filter",
        description="Filter jobs by date",
        items=[
            ('ALL', "All Time", "Show all jobs"),
            ('TODAY', "Today", "Show jobs from today"),
            ('WEEK', "Last 7 Days", "Show jobs from last 7 days"),
            ('MONTH', "Last 30 Days", "Show jobs from last 30 days"),
        ],
        default='ALL',
        update=_on_filter_changed
    )
    
    # Job history detail view mode (for two-state panel)
    job_history_detail_mode: BoolProperty(
        name="Detail Mode",
        description="True when viewing job details, False when viewing list",
        default=False
    )
    
    # Legacy single-job properties (kept for backwards compatibility during transition)
    job_running: BoolProperty(
        default=False,
        description="True if at least one job is currently executing"
    )
    job_status: StringProperty(
        default="",
        description="A user-facing message describing the current job status"
    )
    job_progress: FloatProperty(
        default=0.0, min=0.0, max=1.0,
        description="Job progress from 0.0 (started) to 1.0 (complete)"
    )
    job_elapsed_time: StringProperty(
        default="0.0s",
        description="The elapsed time since the job started"
    )
    job_started_at: StringProperty(
        default="",
        description="Formatted time when the job started (HH:MM:SS)"
    )

    active_workflow_filepath: StringProperty(
        name="Active Workflow File Path",
        description="Internal: The original file path of the loaded workflow",
        subtype='FILE_PATH',
    )

    is_active_workflow_savable: BoolProperty(
        name="Is Savable",
        description="True if the active workflow was loaded from a file and is not yet in the library",
        default=False,
    )

    def _load_workflow_from_library(self, context):
        """Called when the user selects a workflow from the dropdown."""
        workflow_id = self.saved_workflows_enum

        if not workflow_id or workflow_id == '__NONE__':
            return

        library_dir = workflow_manager.get_library_dir()
        filepath = os.path.join(library_dir, workflow_id)

        if os.path.exists(filepath):
            try:
                wf = WorkflowDefinition.from_json_file(filepath)

                populate_state_from_definition(context, self, wf, source_filepath=filepath)

                if context and context.screen:
                    for area in context.screen.areas:
                        area.tag_redraw()
            except Exception as e:
                self.report({'INFO'}, f"[MLXAR] Failed to load workflow '{workflow_id}': {e}")

        bpy.app.timers.call_soon(lambda: setattr(self, 'saved_workflows_enum', '__NONE__'))

    saved_workflows_enum: EnumProperty(
        name="Saved Workflows",
        description="Select a workflow to load it from the library",
        items=workflow_manager.get_saved_workflows_for_enum,
        update=_load_workflow_from_library,
    )

# -------------------------------------------------------------------
# --- State Management Functions ---
# -------------------------------------------------------------------

def clear_workflow_state(state: AtlasWorkflowState) -> None:
    """
    Resets the workflow state to its default (empty) values.

    Args:
        state: The AtlasWorkflowState instance to clear.
    """
    state.inputs.clear()
    state.outputs.clear()
    state.active_api_id = ""
    state.active_name = ""
    state.base_url = ""
    state.version = ""
    state.job_running = False
    state.job_status = ""
    state.job_progress = 0.0
    state.job_elapsed_time = "0.0s"


def populate_state_from_definition(
        context: bpy.types.Context,
        state: AtlasWorkflowState,
        wf: WorkflowDefinition,
        source_filepath: str = ""
) -> None:
    """
    Configures the Blender state based on a workflow definition.

    This function clears any existing state and then populates the input and
    output parameter collections from the provided WorkflowDefinition object,
    setting their default values.

    Args:
        state: The AtlasWorkflowState instance to populate.
        wf: The WorkflowDefinition object containing the schema.
    """
    clear_workflow_state(state)

    # Copy basic workflow metadata
    state.active_api_id = wf.api_id
    state.active_name = wf.name
    state.base_url = wf.base_url
    state.version = wf.version

    # --- Track the source file and savable status ---
    state.active_workflow_filepath = source_filepath
    if source_filepath and not workflow_manager.is_workflow_in_library(source_filepath):
        state.is_active_workflow_savable = True
    else:
        state.is_active_workflow_savable = False
    # Create and configure input parameters
    for p in wf.inputs:
        item = state.inputs.add()
        item.param_id = p.id
        item.label = p.label
        item.param_type = p.type.value

        # Set default values based on parameter type
        default = p.default_value
        if p.type == ParamType.BOOL:
            item.bool_value = bool(default) if default is not None else False
        elif p.type == ParamType.NUMBER:
            if isinstance(default, int):
                item.int_value = default
                item.number_value = float(default)
            elif isinstance(default, float):
                item.number_value = default
            else:
                item.number_value = 0.0
        elif p.type == ParamType.STRING:
            item.string_value = str(default) if default is not None else ""
        elif p.type in (ParamType.IMAGE, ParamType.MESH):
            # For datablock types, default to using data from the current scene.
            # The user will select the specific datablock in the UI.
            item.source_type = 'SCENE'

    # Create output parameter placeholders
    for p in wf.outputs:
        item = state.outputs.add()
        item.param_id = p.id
        item.label = p.id  # Outputs typically use their ID as the label
        item.param_type = p.type.value


# -------------------------------------------------------------------
# --- Blender Registration ---
# -------------------------------------------------------------------

classes = (
    AtlasJobHistoryItem,  # Must be registered before AtlasWorkflowState
    AtlasRunningJobItem,  # Must be registered before AtlasWorkflowState
    AtlasWorkflowParamState,
    AtlasWorkflowState,
)


def register():
    """
    Registers the addon's classes and properties with Blender.

    This function registers the PropertyGroup classes and attaches the main
    AtlasWorkflowState to Blender's WindowManager, making it globally
    accessible.
    """
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.atlas_workflow_state = PointerProperty(
        name="MLXAR Workflow State",
        type=AtlasWorkflowState,
        description="Stores the global state for the Atlas workflow addon",
    )


def unregister():
    """
    Unregisters the addon's classes and properties from Blender.

    This function is called when the addon is disabled. It removes the
    global state from the WindowManager and unregisters the classes in
    reverse order.
    """
    del bpy.types.WindowManager.atlas_workflow_state

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    # This block allows the script to be run directly in Blender's text editor
    # for quick testing and registration.
    register()