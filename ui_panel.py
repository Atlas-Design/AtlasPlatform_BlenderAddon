# In ui_panel.py
"""
Defines the user interface panels for the Atlas Workflow addon.

This module contains all the bpy.types.Panel classes that create the UI in
the 3D View's sidebar. The panels are responsible for displaying:
- The main controls for loading a workflow and clearing the cache.
- The status of a currently running job.
- Details about the currently loaded workflow.
- A list of all input and output parameters.

Helper functions are used to draw the individual UI widgets for each
parameter type, keeping the panel classes clean and focused.
"""

import bpy
from datetime import datetime, timezone, timedelta
from . import custom_icons
from . import workflow_manager
from . import job_manager

# -------------------------------------------------------------------
# --- Base Panel Class ---
# -------------------------------------------------------------------

class ATLAS_PT_BasePanel(bpy.types.Panel):
    """
    A base class for all Atlas panels to share common settings.

    This avoids repeating the bl_space_type, bl_region_type, and bl_category
    in every panel class, making the code more maintainable.
    """
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MLXAR"  # This creates the "Atlas" tab in the sidebar

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """
        Controls whether the panel is visible.

        Panels are visible when a workflow is loaded.
        They remain visible during job execution (matching Unity behavior).
        """
        state = context.window_manager.atlas_workflow_state
        # Panels are visible if state exists and a workflow is loaded
        return state and state.active_api_id


# -------------------------------------------------------------------
# --- UI Panels ---
# -------------------------------------------------------------------

class ATLAS_PT_RunningJobsPanel(bpy.types.Panel):
    """
    Dedicated panel for displaying all running jobs.
    
    Supports multiple concurrent jobs running on the server.
    Only visible when at least one job is running.
    """
    bl_idname = "ATLAS_PT_running_jobs_panel"
    bl_label = "Running Jobs"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MLXAR"
    bl_order = 1  # Appears right after main control panel

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Only show this panel when at least one job is running."""
        state = context.window_manager.atlas_workflow_state
        return state and len(state.running_jobs) > 0

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # Draw each running job
        for job in state.running_jobs:
            self._draw_running_job(layout, job)
    
    def _draw_running_job(self, layout, job):
        """Draw a single running job entry (compact layout)."""
        box = layout.box()
        
        # Row 1: Status icon + Workflow name + Elapsed time
        row1 = box.row(align=True)
        
        # Status icon based on phase
        phase = job.current_phase.lower()
        if phase == "running":
            row1.label(text="", icon='PLAY')
        elif phase == "pending":
            row1.label(text="", icon='PAUSE')
        elif phase == "uploading":
            row1.label(text="", icon='EXPORT')
        elif phase == "downloading":
            row1.label(text="", icon='IMPORT')
        else:
            row1.label(text="", icon='SORTTIME')
        
        row1.label(text=job.workflow_name or "Workflow")
        row1.label(text=job.elapsed_time)
        
        # Row 2: Progress bar + percentage + short status
        row2 = box.row(align=True)
        row2.prop(job, "progress", text="", slider=True)
        progress_pct = int(job.progress * 100)
        
        # Short status text
        if phase == "pending":
            status_text = "Queued"
        elif phase == "uploading":
            status_text = "Uploading"
        elif phase == "downloading":
            status_text = "Downloading"
        elif phase == "running":
            status_text = "Running"
        else:
            status_text = f"{progress_pct}%"
        
        row2.label(text=status_text)


class ATLAS_PT_MainControlPanel(ATLAS_PT_BasePanel):
    """
    The main addon panel for loading workflows.

    This panel is always visible and appears at the top of the category.
    Shows workflow library controls and loaded workflow info.
    """
    bl_idname = "ATLAS_PT_main_control_panel"
    bl_label = "Workflow Library"
    bl_order = 0  # Ensures this panel is at the top

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Always visible - this is the main entry point."""
        return True

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # --- Group Box 1: Load from File ---
        box_file = layout.box()

        box_file.operator("atlas.load_workflow", text="Load from File...", icon='FILE_FOLDER')
        box_file.label(text="Workflow Library", icon='DOCUMENTS')
        box_file.prop(state, "saved_workflows_enum", text="")

        # --- Group Box 2: Loaded Workflow ---
        box_loaded = layout.box()

        if not state.active_api_id:
            # Empty state for the "Loaded" panel
            box_loaded.label(text="No workflow is loaded.", icon='INFO')
        else:
            # Display info and management buttons for the loaded workflow
            header_row = box_loaded.row(align=True)
            header_row.label(text="Loaded:", icon='FILE_TICK')
            header_row.label(text=state.active_name)

            # Management buttons only make sense if the loaded workflow is in the library
            is_in_library = workflow_manager.is_workflow_in_library(state.active_workflow_filepath)
            if state.is_active_workflow_savable:
                box_loaded.operator("atlas.save_active_workflow", text="Save to Library", icon='ADD')

            if is_in_library:
                button_row = box_loaded.row(align=True)
                button_row.operator("atlas.rename_workflow", text="Rename")
                button_row.operator("atlas.delete_workflow", text="Delete")

        # --- Final Global Actions ---
        row = layout.row(align=True)
        if state.active_api_id:
            row.operator("atlas.clear_cache", text="Clear Cache", icon='TRASH')
        row.operator("atlas.open_preferences", text="", icon='PREFERENCES')


class ATLAS_PT_InputsPanel(ATLAS_PT_BasePanel):
    """
    Displays all the input parameters for the currently loaded workflow.
    """
    bl_idname = "ATLAS_PT_inputs_panel"
    bl_label = "Inputs"
    bl_order = 2  # Appears below running jobs panel

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # Loop through each input parameter and draw its corresponding UI widget
        for item in state.inputs:
            draw_input_param(context, layout, item)

        layout.separator()
        # The main "Run" button shows workflow name (workflow identity!)
        # Always enabled - users can run multiple jobs concurrently
        run_text = f"Run {state.active_name}" if state.active_name else "Run Workflow"
        layout.operator("atlas.run_workflow", text=run_text, icon='PLAY')


class ATLAS_PT_OutputsPanel(ATLAS_PT_BasePanel):
    """
    Displays the results from the last completed workflow run.
    """
    bl_idname = "ATLAS_PT_outputs_panel"
    bl_label = "Outputs"
    bl_order = 3  # Appears below inputs panel

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        if not state.outputs:
            layout.label(text="(No outputs defined in workflow)")
        else:
            # Loop through each output parameter and draw its UI
            for item in state.outputs:
                draw_output_param(context, layout, item)


# -------------------------------------------------------------------
# --- Job History UIList ---
# -------------------------------------------------------------------

class ATLAS_UL_JobHistoryList(bpy.types.UIList):
    """UIList for displaying job history entries."""
    bl_idname = "ATLAS_UL_job_history_list"
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw a single job history item."""
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Status icon
            if item.status == 2:  # Completed
                row.label(text="", icon='CHECKMARK')
            elif item.status == 3:  # Failed
                row.label(text="", icon='CANCEL')
            elif item.status == 1:  # Running
                row.label(text="", icon='TIME')
            else:
                row.label(text="", icon='PAUSE')
            
            # Workflow name
            row.label(text=item.workflow_name)
            
            # Time display
            row.label(text=item.created_at_display)
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.workflow_name, icon='FILE')
    
    def filter_items(self, context, data, propname):
        """Filter and sort job history items."""
        items = getattr(data, propname)
        state = context.window_manager.atlas_workflow_state
        
        # Initialize filter flags
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = []
        
        # Apply status filter
        if state.filter_status != 'ALL':
            status_map = {'COMPLETED': 2, 'FAILED': 3, 'RUNNING': 1}
            target_status = status_map.get(state.filter_status, -1)
            for i, item in enumerate(items):
                if item.status != target_status:
                    flt_flags[i] = 0
        
        # Apply workflow filter (now an enum, not text search)
        if state.filter_workflow and state.filter_workflow != 'ALL':
            for i, item in enumerate(items):
                if item.workflow_name != state.filter_workflow:
                    flt_flags[i] = 0
        
        # Apply date filter
        if state.filter_date != 'ALL':
            now = datetime.now(timezone.utc)
            for i, item in enumerate(items):
                try:
                    created = datetime.fromisoformat(item.created_at.replace('Z', '+00:00'))
                    age = now - created
                    
                    if state.filter_date == 'TODAY' and age.days > 0:
                        flt_flags[i] = 0
                    elif state.filter_date == 'WEEK' and age.days > 7:
                        flt_flags[i] = 0
                    elif state.filter_date == 'MONTH' and age.days > 30:
                        flt_flags[i] = 0
                except:
                    pass
        
        return flt_flags, flt_neworder


class ATLAS_PT_JobHistoryPanel(bpy.types.Panel):
    """
    Panel for browsing job history.
    Shows filterable list of past jobs.
    """
    bl_idname = "ATLAS_PT_job_history_panel"
    bl_label = "Jobs History"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MLXAR"
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Always show history panel."""
        return True

    # Class variable to track if we've scheduled auto-load
    _auto_load_scheduled = False
    
    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state
        
        # Auto-load job history if empty (first time panel is opened)
        # Use timer to avoid modifying data during draw
        if len(state.job_history) == 0 and not ATLAS_PT_JobHistoryPanel._auto_load_scheduled:
            ATLAS_PT_JobHistoryPanel._auto_load_scheduled = True
            bpy.app.timers.register(self._deferred_load_history, first_interval=0.1)
        
        # Filter row 1: Status and Date
        filter_row1 = layout.row(align=True)
        filter_row1.prop(state, "filter_status", text="")
        filter_row1.prop(state, "filter_date", text="")
        
        # Filter row 2: Workflow dropdown
        layout.prop(state, "filter_workflow", text="")
        
        # Job list
        row = layout.row()
        row.template_list(
            "ATLAS_UL_job_history_list",  # UIList class name
            "",  # List ID (empty for default)
            state,  # Data pointer
            "job_history",  # Property name for collection
            state,  # Active data pointer
            "job_history_index",  # Property name for active index
            rows=6,
            maxrows=10,
        )
        
        # Refresh button (small, at bottom)
        layout.operator("atlas.refresh_job_history", text="", icon='FILE_REFRESH')
        
        # Show selected job details
        if state.job_history_index >= 0 and state.job_history_index < len(state.job_history):
            selected_job = state.job_history[state.job_history_index]
            self._draw_job_details(layout, selected_job)
    
    def _draw_job_details(self, layout, selected_job):
        """Draw detailed view of the selected job."""
        # Load full job data
        full_job = job_manager.get_job(selected_job.job_folder_path)
        if not full_job:
            layout.label(text="Could not load job details", icon='ERROR')
            return
        
        box = layout.box()
        
        # === HEADER ===
        header_row = box.row()
        if selected_job.status == 2:  # Completed
            header_row.label(text="", icon='CHECKMARK')
            status_text = "Succeeded"
        elif selected_job.status == 3:  # Failed
            header_row.label(text="", icon='CANCEL')
            status_text = "Failed"
        else:
            header_row.label(text="", icon='TIME')
            status_text = "Running"
        
        header_col = header_row.column()
        header_col.label(text=selected_job.workflow_name)
        header_col.label(text=f"{selected_job.created_at_display} • {status_text}")
        
        box.separator()
        
        # === ERROR INFO (if failed) ===
        if full_job.Status == 3 and full_job.ErrorMessage:
            error_box = box.box()
            error_box.alert = True
            error_box.label(text="Error:", icon='ERROR')
            
            # Wrap long error messages
            error_msg = full_job.ErrorMessage
            if len(error_msg) > 50:
                words = error_msg.split()
                lines = []
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) < 45:
                        current_line += (" " if current_line else "") + word
                    else:
                        lines.append(current_line)
                        current_line = word
                if current_line:
                    lines.append(current_line)
                for line in lines[:3]:  # Max 3 lines
                    error_box.label(text=line)
            else:
                error_box.label(text=error_msg)
            
            if full_job.ErrorNodeName:
                error_box.label(text=f"Node: {full_job.ErrorNodeName}")
        
        # === INPUTS ===
        if full_job.InputsSnapshot:
            inputs_box = box.box()
            inputs_header = inputs_box.row()
            inputs_header.label(text="Inputs", icon='IMPORT')
            
            for inp in full_job.InputsSnapshot:
                self._draw_param_snapshot(inputs_box, inp, is_input=True)
        
        # === OUTPUTS ===
        if full_job.OutputsSnapshot:
            outputs_box = box.box()
            outputs_header = outputs_box.row()
            outputs_header.label(text="Outputs", icon='EXPORT')
            
            for out in full_job.OutputsSnapshot:
                self._draw_param_snapshot(outputs_box, out, is_input=False, job_folder=full_job.JobFolderPath)
        
        # === ACTION BUTTONS ===
        box.separator()
        actions_row = box.row(align=True)
        op = actions_row.operator("atlas.open_job_folder", text="Open Folder", icon='FILE_FOLDER')
        op.job_folder_path = selected_job.job_folder_path
    
    def _draw_param_snapshot(self, layout, param, is_input=True, job_folder=None):
        """Draw a single parameter from input/output snapshot."""
        row = layout.row(align=True)
        
        param_type = param.get('ParamType', 'string')
        param_id = param.get('ParamId', 'unknown')
        label = param.get('Label', param_id)
        
        # Type icon
        icon_id = custom_icons.get_icon_id(param_type)
        row.label(text="", icon_value=icon_id)
        
        # Label
        row.label(text=label)
        
        # Value based on type
        if param_type == 'boolean':
            value = "✓" if param.get('BoolValue', False) else "✗"
            row.label(text=value)
        elif param_type == 'number':
            value = param.get('NumberValue', 0.0)
            row.label(text=f"{value:.2f}" if isinstance(value, float) else str(value))
        elif param_type == 'string':
            value = param.get('StringValue', '')
            # Truncate long strings
            if value and len(value) > 30:
                value = value[:27] + "..."
            row.label(text=value or "(empty)")
        elif param_type in ('image', 'mesh'):
            file_path = param.get('FilePath', '')
            if file_path:
                import os
                filename = os.path.basename(file_path)
                row.label(text=filename)
                
                # Add view/import button for outputs
                if not is_input and job_folder and os.path.exists(file_path):
                    if param_type == 'image':
                        op = row.operator("atlas.view_job_output_image", text="", icon='IMAGE_DATA')
                        op.file_path = file_path
                    elif param_type == 'mesh':
                        op = row.operator("atlas.import_job_output_mesh", text="", icon='IMPORT')
                        op.file_path = file_path
            else:
                row.label(text="(no file)")
    
    @staticmethod
    def _deferred_load_history():
        """Load job history after a short delay (called by timer)."""
        try:
            bpy.ops.atlas.refresh_job_history()
        except:
            pass
        ATLAS_PT_JobHistoryPanel._auto_load_scheduled = False
        return None  # Don't repeat


# -------------------------------------------------------------------
# --- Parameter Drawing Helper Functions (Unchanged) ---
# -------------------------------------------------------------------

def draw_input_param(context: bpy.types.Context, layout: bpy.types.UILayout, item: bpy.types.PropertyGroup):
    """Draws the appropriate UI widget for a single input parameter."""
    ptype = item.param_type
    icon_id = custom_icons.get_icon_id(ptype)  # <-- Get icon from our new module

    if ptype == "image" or ptype == "mesh":
        row = layout.row(align=True)
        # Use icon_value for custom icons
        row.label(text="", icon_value=icon_id)
        row.label(text=item.label)

        box = layout.box()
        # (Rest of this block is unchanged)
        box.row().prop(item, "source_type", expand=True)
        if item.source_type == 'SCENE':
            if ptype == "image":
                box.prop_search(item, "image_name", bpy.data, "images", text="")
            elif ptype == "mesh":
                box.prop_search(item, "mesh_name", context.scene, "objects", text="")
        elif item.source_type == 'FILE':
            # 1. Draw standard Blender file picker
            box.prop(item, "file_path", text="")

            # 2. POST-SELECTION VALIDATION (The "Filter")
            # If the user picks a file, we check the extension immediately.
            path = item.file_path.lower()
            if path:
                import os
                valid = True
                ext = os.path.splitext(path)[1]

                # Check Image
                if ptype == "image" and ext not in ['.png', '.jpg', '.jpeg', '.webp']:
                    valid = False
                    msg = "Selected file is not an image!"

                # Check Mesh
                elif ptype == "mesh" and ext not in ['.glb', '.gltf']:
                    valid = False
                    msg = "Selected file is not a GLB/GLTF mesh!"

                # Draw Warning if invalid
                if not valid:
                    row = box.row()
                    row.alert = True  # Makes the text red
                    row.label(text=msg, icon='ERROR')

        return


    # For simple types
    row = layout.row(align=True)
    row.label(text="", icon_value=icon_id)
    row.label(text=item.label)
    if ptype == "boolean":
        row.prop(item, "bool_value", text="")
    elif ptype == "number":
        row.prop(item, "number_value", text="")
    elif ptype == "string":
        row.prop(item, "string_value", text="")
    else:
        row.label(text=f"(Unsupported type: {ptype})")


def draw_output_param(context: bpy.types.Context, layout: bpy.types.UILayout, item: bpy.types.PropertyGroup):
    """Draws the UI for a single, read-only output parameter."""
    ptype = item.param_type
    icon_id = custom_icons.get_icon_id(ptype)

    # Base row for alignment
    row = layout.row(align=True)
    row.label(text="", icon_value=icon_id)

    # Use a sub-layout for the rest of the content
    content_col = row.column()

    # --- (The 'image' and 'mesh' blocks ) ---
    if ptype == "image":
        row_text = content_col.row()
        row_text.enabled = False
        row_text.prop(item, "image_name", text=item.label)
        row_buttons = content_col.row(align=True)
        row_buttons.enabled = bool(item.image_name)
        op_save = row_buttons.operator("atlas.save_output_image", text="Save As...", icon='FILE_TICK')
        op_save.image_name = item.image_name
        op_apply = row_buttons.operator("atlas.apply_output_image", text="Apply", icon='TEXTURE')
        op_apply.image_name = item.image_name
        return

    if ptype == "mesh":
        row_text = content_col.row()
        row_text.enabled = False
        row_text.prop(item, "mesh_name", text=item.label)
        row_buttons = content_col.row(align=True)
        row_buttons.enabled = bool(item.temp_file_path)
        op_import = row_buttons.operator("atlas.import_output_mesh", text="Import", icon='IMPORT')
        op_import.param_id = item.param_id
        op_replace = row_buttons.operator("atlas.replace_active_with_mesh", text="Replace", icon='CON_OBJECTSOLVER')
        op_replace.param_id = item.param_id
        return

    # Create a new row for the label and widget.
    output_row = content_col.row(align=True)
    output_row.enabled = False  # Make the entire row read-only at once.

    # 1. Draw the label explicitly first.
    output_row.label(text=item.label)

    # 2. Draw the property widget second, with its own label suppressed.
    if ptype == "boolean":
        output_row.prop(item, "bool_value", text="")
    elif ptype == "number":
        output_row.prop(item, "number_value", text="")
    elif ptype == "string":
        output_row.prop(item, "string_value", text="")
    else:
        # Fallback for unsupported types
        output_row.label(text=f"(Unsupported type: {ptype})")


# -------------------------------------------------------------------
# --- Blender Registration ---
# -------------------------------------------------------------------

classes = (
    ATLAS_UL_JobHistoryList,  # UIList must be registered first
    ATLAS_PT_MainControlPanel,
    ATLAS_PT_RunningJobsPanel,
    ATLAS_PT_InputsPanel,
    ATLAS_PT_OutputsPanel,
    ATLAS_PT_JobHistoryPanel,
)


def register():
    """Registers all UI panel classes with Blender."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregisters all UI panel classes from Blender."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()