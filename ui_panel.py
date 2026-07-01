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

import os
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
    bl_label = "Atlas Workflow Library"
    bl_order = 0  # Ensures this panel is at the top

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Always visible - this is the main entry point."""
        return True

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # --- Library Row: [Dropdown] [Import] [Delete] ---
        row = layout.row(align=True)
        row.prop(state, "saved_workflows_enum", text="")
        
        # Import button - slightly wider than X button
        import_btn = row.row(align=True)
        import_btn.scale_x = 1.2
        import_btn.operator("atlas.load_workflow", text="", icon='IMPORT')
        
        # Delete button (X icon) - only enabled if workflow is in library
        is_in_library = workflow_manager.is_workflow_in_library(state.active_workflow_filepath)
        delete_row = row.row(align=True)
        delete_row.enabled = is_in_library and bool(state.active_api_id)
        delete_row.operator("atlas.delete_workflow", text="", icon='X')

        # --- Loaded Workflow Info ---
        if state.active_api_id:
            info_row = layout.row(align=True)
            info_row.label(text="Loaded:", icon='CHECKMARK')
            info_row.label(text=state.active_name)
            
            # Save to Library button (only if loaded from file, not already in library)
            if state.is_active_workflow_savable:
                layout.operator("atlas.save_active_workflow", text="Save to Library", icon='ADD')


class ATLAS_PT_SelectedWorkflowPanel(bpy.types.Panel):
    """
    Combined panel showing the selected workflow's inputs, outputs preview, and run button.
    Only visible when a workflow is selected.
    """
    bl_idname = "ATLAS_PT_selected_workflow_panel"
    bl_label = "Selected Workflow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MLXAR"
    bl_order = 2  # Appears below running jobs panel

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Only visible when a workflow is actually selected."""
        state = context.window_manager.atlas_workflow_state
        return state and state.active_api_id

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # --- INPUTS SECTION ---
        if state.inputs:
            inputs_box = layout.box()
            inputs_box.label(text="Inputs", icon='IMPORT')
            
            for item in state.inputs:
                draw_input_param(context, inputs_box, item)
        
        # --- OUTPUTS SECTION (Preview only - disabled) ---
        if state.outputs:
            outputs_box = layout.box()
            outputs_box.label(text="Outputs", icon='EXPORT')
            
            # Draw outputs as disabled preview (just name + type icon)
            col = outputs_box.column(align=True)
            col.enabled = False  # Disable entire section
            
            for item in state.outputs:
                row = col.row(align=True)
                icon_id = custom_icons.get_icon_id(item.param_type)
                row.label(text="", icon_value=icon_id)
                row.label(text=item.label)

        # --- RUN BUTTON ---
        layout.separator()
        run_text = f"Run {state.active_name}" if state.active_name else "Run Workflow"
        layout.operator("atlas.run_workflow", text=run_text, icon='PLAY')


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
                row.label(text="", icon='ERROR')
            elif item.status == 1:  # Running
                row.label(text="", icon='TIME')
            else:
                row.label(text="", icon='PAUSE')
            
            # Workflow name (takes remaining space)
            row.label(text=item.workflow_name)
            
            # Time display (compact)
            row.label(text=item.created_at_display)
            
            # View details button (small arrow icon)
            op = row.operator("atlas.select_job", text="", icon='FORWARD', emboss=False)
            op.job_index = index
            
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
    Two-state panel for browsing job history.
    - List View: Shows filters + job list
    - Detail View: Shows full details of selected job
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
        if len(state.job_history) == 0 and not ATLAS_PT_JobHistoryPanel._auto_load_scheduled:
            ATLAS_PT_JobHistoryPanel._auto_load_scheduled = True
            bpy.app.timers.register(self._deferred_load_history, first_interval=0.1)
        
        # Two-state panel: List View vs Detail View
        if state.job_history_detail_mode and state.job_history_index >= 0:
            self._draw_detail_view(context, layout, state)
        else:
            self._draw_list_view(context, layout, state)
    
    def _draw_list_view(self, context, layout, state):
        """Draw the job history list with filters."""
        # Filter row 1: Status and Date
        filter_row1 = layout.row(align=True)
        filter_row1.prop(state, "filter_status", text="")
        filter_row1.prop(state, "filter_date", text="")
        
        # Filter row 2: Workflow dropdown
        layout.prop(state, "filter_workflow", text="")
        
        # Job list - each row has its own view button
        row = layout.row()
        row.template_list(
            "ATLAS_UL_job_history_list",
            "",
            state,
            "job_history",
            state,
            "job_history_index",
            rows=8,
            maxrows=12,
        )
        
        # Just refresh button at bottom
        layout.operator("atlas.refresh_job_history", text="", icon='FILE_REFRESH')
    
    def _draw_detail_view(self, context, layout, state):
        """Draw the detailed view of a selected job."""
        # Verify valid selection
        if state.job_history_index < 0 or state.job_history_index >= len(state.job_history):
            state.job_history_detail_mode = False
            return
        
        selected_job = state.job_history[state.job_history_index]
        
        # Back button - prominent, full width with highlight
        back_box = layout.box()
        back_row = back_box.row()
        back_row.scale_y = 1.3  # Taller button
        back_row.operator("atlas.back_to_job_list", text="← Back to History", icon='LOOP_BACK')
        
        layout.separator()
        
        # Load full job data
        full_job = job_manager.get_job(selected_job.job_folder_path)
        if not full_job:
            layout.label(text="Could not load job details", icon='ERROR')
            return
        
        # === HEADER ===
        header_box = layout.box()
        header_row = header_box.row()
        
        if selected_job.status == 2:  # Completed
            header_row.label(text="", icon='CHECKMARK')
            status_text = "Completed"
        elif selected_job.status == 3:  # Failed
            header_row.label(text="", icon='ERROR')
            status_text = "Failed"
        else:
            header_row.label(text="", icon='TIME')
            status_text = "Running"
        
        header_col = header_row.column()
        header_col.label(text=selected_job.workflow_name)
        header_col.label(text=f"{selected_job.created_at_display} • {status_text}")
        
        # === ERROR INFO (if failed) ===
        if full_job.Status == 3 and full_job.ErrorMessage:
            error_box = layout.box()
            error_box.alert = True
            error_box.label(text="Error:", icon='ERROR')
            
            # Wrap long error messages
            error_msg = full_job.ErrorMessage
            lines = self._wrap_text(error_msg, 40)
            for line in lines[:4]:  # Max 4 lines
                error_box.label(text=line)
            
            if full_job.ErrorNodeName:
                error_box.label(text=f"Node: {full_job.ErrorNodeName}")
        
        # === OUTPUTS SECTION (with actions) ===
        # Put results before inputs so completed job details surface the useful artifacts first.
        if full_job.OutputsSnapshot:
            outputs_box = layout.box()
            outputs_box.label(text="Outputs", icon='EXPORT')
            
            for out in full_job.OutputsSnapshot:
                self._draw_output_param(outputs_box, out, full_job.JobFolderPath)
        elif full_job.Status == 2:  # Completed
            outputs_box = layout.box()
            outputs_box.label(text="Outputs", icon='EXPORT')
            outputs_box.label(text="No outputs were saved for this job.", icon='INFO')
        
        # === INPUTS SECTION (disabled/read-only) ===
        if full_job.InputsSnapshot:
            inputs_box = layout.box()
            inputs_box.label(text="Inputs", icon='IMPORT')
            
            inputs_col = inputs_box.column(align=True)
            inputs_col.enabled = False  # Disable entire section
            
            for inp in full_job.InputsSnapshot:
                self._draw_input_param(inputs_col, inp)
        
        # === ACTION BUTTONS ===
        layout.separator()
        op = layout.operator("atlas.open_job_folder", text="Open Folder", icon='FILE_FOLDER')
        op.job_folder_path = selected_job.job_folder_path
    
    def _draw_input_param(self, layout, param):
        """Draw a single input parameter (disabled/read-only)."""
        row = layout.row(align=True)
        
        param_type = param.get('ParamType', 'string')
        param_id = param.get('ParamId', 'unknown')
        label = param.get('Label', param_id)
        
        # Type icon
        icon_id = custom_icons.get_icon_id(param_type)
        row.label(text="", icon_value=icon_id)
        row.label(text=label)
        
        # Value display (all disabled since this is historical data)
        if param_type == 'boolean':
            value = "✓ Yes" if param.get('BoolValue', False) else "✗ No"
            row.label(text=value)
        elif param_type == 'number':
            value = param.get('NumberValue', 0.0)
            row.label(text=f"{value:.3f}" if isinstance(value, float) else str(value))
        elif param_type == 'string':
            value = param.get('StringValue', '')
            if value and len(value) > 25:
                value = value[:22] + "..."
            row.label(text=value or "(empty)")
        elif param_type in ('image', 'mesh'):
            file_path = param.get('FilePath', '')
            if file_path:
                filename = os.path.basename(file_path)
                row.label(text=filename)
            else:
                row.label(text="(no file)")
    
    def _draw_output_param(self, layout, param, job_folder):
        """Draw a single output parameter with appropriate actions."""
        param_type = param.get('ParamType', 'string')
        param_id = param.get('ParamId', 'unknown')
        label = param.get('Label', param_id)
        
        row = layout.row(align=True)
        
        # Type icon
        icon_id = custom_icons.get_icon_id(param_type)
        row.label(text="", icon_value=icon_id)
        row.label(text=label)
        
        # Value display + actions based on type
        if param_type == 'boolean':
            # Bool: Just display value (no action makes sense)
            value = "✓ Yes" if param.get('BoolValue', False) else "✗ No"
            row.label(text=value)
            
        elif param_type == 'number':
            # Number: Display + copy button
            value = param.get('NumberValue', 0.0)
            value_str = f"{value:.4f}" if isinstance(value, float) else str(value)
            row.label(text=value_str)
            op = row.operator("atlas.copy_to_clipboard", text="", icon='COPYDOWN')
            op.value = value_str
            
        elif param_type == 'string':
            # String: Show the full generated text in a wrapped box.
            value = param.get('StringValue', '')
            row.label(text="Text")
            if value:
                op = row.operator("atlas.copy_to_clipboard", text="", icon='COPYDOWN')
                op.value = value
                text_box = layout.box()
                for line in self._wrap_text(value, 48):
                    text_box.label(text=line)
            else:
                row.label(text="(empty)")
                
        elif param_type == 'image':
            # Image: filename + View/Apply buttons
            file_path = param.get('FilePath', '')
            if file_path and os.path.exists(file_path):
                filename = os.path.basename(file_path)
                row.label(text=filename)
                
                # Action buttons on new row for more space
                actions_row = layout.row(align=True)
                actions_row.separator()  # Indent
                
                op_view = actions_row.operator("atlas.view_job_output_image", text="View", icon='IMAGE_DATA')
                op_view.file_path = file_path
                
                op_apply = actions_row.operator("atlas.apply_job_output_image", text="Apply", icon='TEXTURE')
                op_apply.file_path = file_path
            else:
                row.label(text="(file not found)")
                
        elif param_type == 'mesh':
            # Mesh: filename + Import button
            file_path = param.get('FilePath', '')
            if file_path and os.path.exists(file_path):
                filename = os.path.basename(file_path)
                row.label(text=filename)
                
                # Action buttons on new row
                actions_row = layout.row(align=True)
                actions_row.separator()  # Indent
                
                op_import = actions_row.operator("atlas.import_job_output_mesh", text="Import", icon='IMPORT')
                op_import.file_path = file_path
            else:
                row.label(text="(file not found)")
    
    def _wrap_text(self, text, max_chars):
        """Wrap text into lines of max_chars length."""
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= max_chars:
                current_line += (" " if current_line else "") + word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines
    
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
    ATLAS_PT_SelectedWorkflowPanel,
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