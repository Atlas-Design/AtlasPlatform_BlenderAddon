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
import json
import textwrap
import bpy
from datetime import datetime, timezone, timedelta
try:
    from . import custom_icons
    from . import workflow_manager
    from . import job_manager
    from . import native_assets
    from . import operators
    from .asset_types import FILE_FORMATS, PRIMITIVE_TYPES, RASTER_TYPES, SCENE_INPUT_TYPES
except ImportError:
    import custom_icons
    import workflow_manager
    import job_manager
    import native_assets
    import operators
    from asset_types import FILE_FORMATS, PRIMITIVE_TYPES, RASTER_TYPES, SCENE_INPUT_TYPES


def draw_collapsible_box(layout, state, prop_name: str, label: str, icon: str):
    """Draw a compact collapsible section and return (box, expanded)."""
    box = layout.box()
    expanded = bool(getattr(state, prop_name))
    row = box.row(align=True)
    row.prop(
        state,
        prop_name,
        text=label,
        icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    row.label(text="", icon=icon)
    return box, expanded


def draw_run_actions(layout, state, job):
    """Actions bind to a stable run ID, regardless of list order and filters."""
    running = next((r for r in state.running_jobs if r.job_id == job.job_id), None)
    if running:
        row = layout.row()
        row.enabled = not running.stop_requested
        row.operator('atlas.stop_tracking', text='Stopping…' if running.stop_requested else 'Stop Tracking',
                     icon='PAUSE').job_id = job.job_id
    elif job.status in (2, 3, 4, 5):
        layout.operator('atlas.delete_job', text='Delete Run', icon='TRASH').job_id = job.job_id


def draw_start_feedback(layout, state):
    job = next((j for j in state.job_history if j.job_id == state.last_started_job_id), None)
    if not job:
        return
    running = next((r for r in state.running_jobs if r.job_id == job.job_id), None)
    box = layout.box()
    title = box.row()
    title.scale_y = 1.3
    title.label(text=f'Run #{job.run_number} started' if running else f'Run #{job.run_number}: {job.get_status_name()}',
                icon='TIME' if running else job.get_status_icon())
    box.label(text=job.workflow_name)
    if running:
        for line in textwrap.wrap(running.status, 34):
            box.label(text=line)
        box.label(text=f'Elapsed: {running.elapsed_time}')
    box.operator('atlas.select_job', text='View Job' if running else 'View Results', icon='FORWARD').job_id = job.job_id


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
    bl_category = "Atlas"

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

class ATLAS_PT_MainControlPanel(ATLAS_PT_BasePanel):
    """
    The main addon panel for loading workflows.

    This panel is always visible and appears at the top of the category.
    Shows workflow library controls and loaded workflow info.
    """
    bl_idname = "ATLAS_PT_main_control_panel"
    bl_label = "Atlas"
    bl_order = 0  # Ensures this panel is at the top

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Always visible - this is the main entry point."""
        return True

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state
        layout.prop(state, 'view_mode', expand=True)
        if not state.history_loaded and not JobsView._auto_load_scheduled:
            JobsView._auto_load_scheduled = True
            bpy.app.timers.register(JobsView._deferred_load_history, first_interval=0.1)
        unread = [job for job in state.job_history if not job.reviewed and job.status in (2, 3, 4, 5)]
        row = layout.row(align=True)
        row.label(text=f'{len(state.running_jobs)} running', icon='TIME')
        if unread:
            label = '1 new result' if len(unread) == 1 else f'{len(unread)} new results'
            row.operator('atlas.select_job', text=label, icon='FORWARD').job_id = unread[0].job_id
        else:
            row.label(text='No new results')
        layout.separator()
        if state.view_mode == 'RUN':
            self.draw_run_controls(context)
            if state.active_api_id:
                WorkflowForm.draw(self, context)
            else:
                layout.label(text='Choose or import a workflow to start.', icon='INFO')
        else:
            view = JobsView()
            view.layout = layout
            view.draw(context)

    def draw_run_controls(self, context):
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


class WorkflowForm:
    """
    Combined panel showing the selected workflow's inputs, outputs preview, and run button.
    Only visible when a workflow is selected.
    """
    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        if state.draft_notice:
            for line in textwrap.wrap(state.draft_notice, width=45):
                layout.label(text=line)

        # --- INPUTS SECTION ---
        if state.inputs:
            inputs_box, expanded = draw_collapsible_box(
                layout, state, "selected_inputs_expanded", "Inputs", 'IMPORT'
            )
            if expanded:
                for item in state.inputs:
                    draw_input_param(context, inputs_box, item)
        
        # --- EXPECTED OUTPUTS (schema labels, not result controls) ---
        if state.outputs:
            outputs_box, expanded = draw_collapsible_box(
                layout, state, "selected_outputs_expanded", f"Expected Outputs ({len(state.outputs)})", 'INFO'
            )
            outputs_box.label(text="Results from each run appear", icon='INFO')
            outputs_box.label(text="in Jobs.")
            if expanded:
                # Plain labels describe the contract even before a run exists.
                col = outputs_box.column(align=True)
                
                for item in state.outputs:
                    row = col.row(align=True)
                    icon_id = custom_icons.get_icon_id(item.param_type)
                    row.label(text="", icon_value=icon_id)
                    row.label(text=item.label + (' []' if item.is_array else ''))
                    row.label(text=item.file_format or item.param_type)

        # --- RUN BUTTON ---
        layout.separator()
        draw_start_feedback(layout, state)
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
            run_id = str(item.run_number) if item.run_number else item.job_id[:8]
            row.label(text=f'#{run_id} · {item.user_label or item.workflow_name}')
            running = next((job for job in context.window_manager.atlas_workflow_state.running_jobs
                            if job.job_id == item.job_id), None)
            if running:
                row.label(text=running.elapsed_time)
            if not item.reviewed and item.status in (2, 3, 4, 5):
                row.label(text='', icon='REC')
            
            op = row.operator("atlas.select_job", text="", icon='FORWARD')
            op.job_id = item.job_id
            
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
            status_map = {'COMPLETED': 2, 'FAILED': 3, 'RUNNING': 1, 'STOPPED': 5}
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


class JobsView:
    """
    Two-state panel for browsing job history.
    - List View: Shows filters + job list
    - Detail View: Shows full details of selected job
    """
    # Class variable to track if we've scheduled auto-load
    _auto_load_scheduled = False
    
    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # Auto-load job history if empty (first time panel is opened)
        if not state.history_loaded and not JobsView._auto_load_scheduled:
            JobsView._auto_load_scheduled = True
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
        if not state.job_history:
            layout.label(text='Your runs and results will appear here.', icon='INFO')
        
        # Job list - each row has its own view button
        row = layout.row()
        row.template_list(
            "ATLAS_UL_job_history_list",
            "",
            state,
            "job_history",
            state,
            "job_history_index",
            rows=5,
            maxrows=8,
        )
        if 0 <= state.job_history_index < len(state.job_history):
            selected = state.job_history[state.job_history_index]
            layout.label(text=f'{selected.created_at_display} · {selected.result_summary}')
            layout.operator('atlas.select_job', text='View Results' if selected.status in (2, 3) else 'View Job',
                            icon='FORWARD').job_id = selected.job_id
            draw_run_actions(layout, state, selected)
        
        # Just refresh button at bottom
        layout.operator("atlas.refresh_job_history", text="", icon='FILE_REFRESH')
    
    def _draw_detail_view(self, context, layout, state):
        """Draw the detailed view of a selected job."""
        # Verify valid selection
        if state.job_history_index < 0 or state.job_history_index >= len(state.job_history):
            state.job_history_detail_mode = False
            return
        
        selected_job = state.job_history[state.job_history_index]
        
        layout.operator("atlas.back_to_job_list", text="← Back to History", icon='LOOP_BACK')
        
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
        elif selected_job.status == 0:
            header_row.label(text="", icon='PAUSE')
            status_text = "Queued"
        elif selected_job.status in (4, 5):
            header_row.label(text="", icon='PAUSE')
            status_text = selected_job.get_status_name()
        else:
            header_row.label(text="", icon='TIME')
            status_text = "Running"
        running_job = next((job for job in state.running_jobs
                            if job.job_id == selected_job.job_id), None)
        if running_job:
            status_text = f"{running_job.status} · {running_job.elapsed_time}"
        
        header_col = header_row.column()
        run_id = str(full_job.RunNumber) if full_job.RunNumber else full_job.JobId[:8]
        header_col.label(text=f'Run {run_id} · {selected_job.workflow_name}')
        if full_job.UserLabel:
            header_col.label(text=full_job.UserLabel)
        try:
            timestamp = datetime.fromisoformat(full_job.CreatedAtUtc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            timestamp = full_job.CreatedAtUtc
        header_col.label(text=timestamp)
        header_col.label(text=status_text)
        header_col.label(text=job_manager.result_summary(full_job))
        draw_run_actions(layout, state, selected_job)
        if running_job and running_job.stop_requested:
            for line in textwrap.wrap('Waiting for the current request to return. Remote execution may continue.', 34):
                layout.label(text=line)
        if full_job.StopMessage:
            for line in textwrap.wrap(full_job.StopMessage, 34):
                layout.label(text=line)
        row = layout.row(align=True)
        row.operator('atlas.rename_job', text='', icon='GREASEPENCIL').job_folder_path = full_job.JobFolderPath
        restore_row = row.row(align=True)
        restore_row.enabled = bool(full_job.WorkflowSnapshot)
        restore_row.operator('atlas.use_job_inputs', text='Use These Inputs', icon='LOOP_BACK').job_folder_path = full_job.JobFolderPath
        if full_job.OutputCopyFolder:
            layout.operator('atlas.open_job_folder', text='Open Output Copies',
                            icon='FILE_FOLDER').job_folder_path = full_job.OutputCopyFolder
        
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
            outputs_box, expanded = draw_collapsible_box(
                layout, state, "job_detail_outputs_expanded", f"Outputs ({len(full_job.OutputsSnapshot)})", 'EXPORT'
            )
            if expanded:
                for out in full_job.OutputsSnapshot:
                    self._draw_output_param(outputs_box, out, full_job.JobFolderPath)
        elif full_job.Status == 2:  # Completed
            outputs_box = layout.box()
            outputs_box.label(text="Outputs", icon='EXPORT')
            outputs_box.label(text="No outputs were saved for this job.", icon='INFO')
        
        # === INPUTS SECTION (disabled/read-only) ===
        if full_job.InputsSnapshot:
            inputs_box, expanded = draw_collapsible_box(
                layout, state, "job_detail_inputs_expanded", f"Inputs ({len(full_job.InputsSnapshot)})", 'IMPORT'
            )
            if expanded:
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
        if not param.get('Provided', True):
            row.label(text='Omitted (server default if allowed)')
        elif param_type in FILE_FORMATS:
            records = param.get('Items', []) if param.get('IsArray') else [param]
            if param.get('IsArray'):
                row.label(text=f'{len(records)} assets')
            for index, record in enumerate(records):
                value = (record.get('AssetId') or os.path.basename(record.get('FilePath') or '')
                         or record.get('ImageValue') or record.get('MeshValue') or record.get('SceneValue') or '(no asset)')
                if record.get('FrameStart') is not None:
                    value += f" (frames {record['FrameStart']}–{record['FrameEnd']})"
                target = layout.row() if param.get('IsArray') else row
                target.label(text=f'{index + 1}. {value}' if param.get('IsArray') else value)
        elif param_type == 'boolean':
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
        else:
            row.label(text=f'Unsupported type: {param_type}')
    
    def _draw_output_param(self, layout, param, job_folder):
        param_type = param.get('ParamType', 'string')
        label = param.get('Label') or param.get('ParamId', 'Output')
        if param_type in FILE_FORMATS:
            records = param.get('Items') or ([] if param.get('IsArray') else [{
                'FilePath': param.get('FilePath'), 'AssetId': param.get('AssetId', ''),
                'ApiOrigin': param.get('ApiOrigin', ''), 'Index': 0,
            }])
            box = layout.box()
            box.label(text=f"{label} ({len(records)})" if param.get('IsArray') else label)
            for record in records:
                draw_asset_result(box, param_type, record)
            if param.get('IsArray') and records:
                reusable = [r for r in records if r.get('AssetId')]
                if reusable:
                    op = box.operator('atlas.reuse_asset', text='Use All as Input', icon='FORWARD')
                    op.param_type = param_type
                    op.asset_data = json.dumps(reusable)
                paths = [r['FilePath'] for r in records if r.get('FilePath') and os.path.isfile(r['FilePath'])]
                if param_type == 'mesh' and paths:
                    op = box.operator('atlas.import_mesh_list', text='Import All Meshes', icon='IMPORT')
                    op.paths_json = json.dumps(paths)
            if not records:
                box.label(text='Empty list' if param.get('IsArray') else 'No asset returned')
            return
        row = layout.row(align=True)
        row.label(text=label)
        if param_type == 'boolean':
            row.label(text='Yes' if param.get('BoolValue') else 'No')
            return
        if param_type == 'number':
            value = str(param.get('NumberValue', 0))
        elif param_type == 'string':
            value = param.get('StringValue') or ''
        else:
            value = json.dumps(param.get('RawValue'), ensure_ascii=False)
        row.label(text=value[:32] + ('...' if len(value) > 32 else ''))
        op = row.operator('atlas.view_text_output', text='', icon='TEXT')
        op.title, op.value = label, value
        op = row.operator('atlas.copy_to_clipboard', text='', icon='COPYDOWN')
        op.value = value

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
        JobsView._auto_load_scheduled = False
        return None  # Don't repeat


# -------------------------------------------------------------------
# --- Parameter Drawing Helper Functions (Unchanged) ---
# -------------------------------------------------------------------

def draw_asset_result(layout, param_type, record):
    path = record.get('FilePath') or ''
    row = layout.row(align=True)
    row.label(text=f"{record.get('Index', 0) + 1}. {os.path.basename(path) or record.get('Filename') or 'Asset'}")
    if path and os.path.isfile(path):
        # AVIF was added after our oldest supported Blender versions.
        can_preview = not path.lower().endswith('.avif') or bpy.app.version >= (5, 1, 0)
        if param_type in RASTER_TYPES and can_preview:
            preview = operators.get_image_preview(path)
            if preview:
                layout.template_icon(icon_value=preview.icon_id, scale=5.0)
            layout.operator('atlas.view_job_output_image', text='Preview', icon='IMAGE_DATA').file_path = path
            image_actions = layout.row(align=True)
            for operator, text in [('atlas.add_image_plane', 'Add Plane'),
                                   ('atlas.apply_job_output_image', 'Apply Material')]:
                op = image_actions.operator(operator, text=text)
                op.file_path = path
        elif param_type == 'mesh' and path.lower().endswith(('.glb', '.gltf')):
            op = row.operator('atlas.import_job_output_mesh', text='Import', icon='IMPORT')
            op.file_path = path
        elif param_type == 'scene':
            op = row.operator('atlas.append_scene_collection', text='Append Collection')
            op.file_path = path
            op = layout.operator('atlas.open_scene_separately', text='Open in New Blender')
            op.file_path = path
        elif param_type in ('usdz', 'rig_animation', 'svg'):
            importer = {'usdz': 'wm.usd_import', 'rig_animation': 'import_scene.gltf', 'svg': 'import_curve.svg'}[param_type]
            if native_assets.operator_available(importer):
                op = row.operator('atlas.import_native_asset', text='Import Curves' if param_type == 'svg' else 'Import')
                op.file_path, op.asset_type = path, param_type
            else:
                layout.label(text='Native importer unavailable; use the downloaded file.', icon='INFO')
        elif param_type in ('audio', 'video'):
            op = row.operator('atlas.add_media', text='Add to Sequencer')
            op.file_path, op.asset_type = path, param_type
        elif param_type == 'agent_context':
            op = row.operator('atlas.view_context', text='View Context')
            op.file_path = path
        op = row.operator('atlas.open_job_folder', text='', icon='FILE_FOLDER')
        op.job_folder_path = os.path.dirname(path)
        if param_type in RASTER_TYPES and not can_preview:
            layout.label(text='AVIF preview requires Blender 5.1+. File is available in the job folder.', icon='INFO')
    if record.get('AssetId'):
        op = row.operator('atlas.reuse_asset', text='Use as Input', icon='FORWARD')
        op.param_type = param_type
        op.asset_data = json.dumps([record])
        op = row.operator('atlas.copy_to_clipboard', text='', icon='COPYDOWN')
        op.value = record['AssetId']
    if record.get('Error'):
        layout.label(text=record['Error'][:100], icon='ERROR')


def draw_asset_input(context, layout, param, entry, index=-1, show_source=True):
    if show_source:
        layout.prop(entry, 'source_type', text='Source')
    if entry.source_type == 'FILE':
        row = layout.row(align=True)
        row.prop(entry, 'file_path', text='')
        op = row.operator('atlas.pick_input_file', text='', icon='FILE_FOLDER')
        op.param_id, op.file_type, op.item_index = param.param_id, param.param_type, index
    elif entry.source_type == 'ASSET':
        layout.prop(entry, 'asset_id', text='Asset ID')
    elif param.param_type in ('image', 'exr'):
        layout.prop_search(entry, 'image_name', bpy.data, 'images', text='Image')
    elif param.param_type == 'mesh':
        layout.prop_search(entry, 'mesh_name', context.scene, 'objects', text='Object')
    elif param.param_type == 'scene':
        layout.label(text='Snapshot current scene with packed dependencies.')
        layout.label(text='Linked libraries and unpacked caches/media must be resolved first.')
    elif param.param_type in ('usdz', 'rig_animation'):
        layout.prop_search(entry, 'mesh_name', context.scene, 'objects', text='Armature' if param.param_type == 'rig_animation' else 'Root Object')
        if param.param_type == 'usdz':
            layout.label(text='Exports root object and descendants with textures.')
        else:
            layout.label(text='Exports active action and bound meshes.')
            row = layout.row(align=True)
            row.prop(entry, 'frame_start')
            row.prop(entry, 'frame_end')
    else:
        layout.label(text='Choose File or Existing Asset for this type.', icon='INFO')


def draw_input_param(context, layout, item):
    box = layout.box()
    row = box.row(align=True)
    row.prop(item, 'provided', text='')
    suffix = ' *' if item.required == 'REQUIRED' else ''
    row.label(text=item.label + (' []' if item.is_array else '') + suffix)
    if not item.provided:
        box.label(text='Omitted; Atlas checks requirements and optional defaults.', icon='INFO')
        return
    if item.param_type in FILE_FORMATS:
        if item.is_array:
            for index, entry in enumerate(item.asset_items):
                sub = box.box()
                controls = sub.row(align=True)
                index_label = controls.row(align=True)
                index_label.alignment = 'LEFT'
                index_label.label(text=str(index + 1))
                controls.prop(entry, 'source_type', text='')
                actions = controls.row(align=True)
                actions.alignment = 'RIGHT'
                for action, icon in [('UP', 'TRIA_UP'), ('DOWN', 'TRIA_DOWN'), ('REMOVE', 'X')]:
                    button = actions.row(align=True)
                    button.enabled = not ((action == 'UP' and index == 0) or
                                          (action == 'DOWN' and index == len(item.asset_items) - 1))
                    op = button.operator('atlas.edit_asset_list', text='', icon=icon)
                    op.param_id, op.item_index, op.action = item.param_id, index, action
                draw_asset_input(context, sub, item, entry, index, show_source=False)
            row = box.row(align=True)
            op = row.operator('atlas.edit_asset_list', text='Add Item', icon='ADD')
            op.param_id = item.param_id
            op = row.operator('atlas.pick_input_file', text='Add Files', icon='FILE_FOLDER')
            op.param_id, op.file_type = item.param_id, item.param_type
            if not item.asset_items:
                box.label(text='Empty list')
        else:
            draw_asset_input(context, box, item, item)
    elif item.param_type in PRIMITIVE_TYPES and not item.is_array:
        prop = {'boolean': 'bool_value', 'number': 'number_value', 'string': 'string_value'}[item.param_type]
        box.prop(item, prop, text='')
    else:
        box.label(text=f'Unsupported input type: {item.param_type}', icon='ERROR')
        box.label(text='Omit only if this workflow allows it.')


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
)


def register():
    """Registers all UI panel classes with Blender."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregisters all UI panel classes from Blender."""
    if bpy.app.timers.is_registered(JobsView._deferred_load_history):
        bpy.app.timers.unregister(JobsView._deferred_load_history)
    JobsView._auto_load_scheduled = False
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
