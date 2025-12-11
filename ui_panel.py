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
from . import custom_icons
from . import workflow_manager

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

        By default, panels inheriting from this will only appear if:
        1. A workflow has been loaded.
        2. A job is NOT currently running.
        This prevents users from changing inputs or accessing outputs mid-process.
        """
        state = context.window_manager.atlas_workflow_state
        # Panels are only drawn if state exists, a workflow is loaded, AND no job is running.
        return state and state.active_api_id and not state.job_running


# -------------------------------------------------------------------
# --- UI Panels ---
# -------------------------------------------------------------------

class ATLAS_PT_MainControlPanel(ATLAS_PT_BasePanel):
    """
    The main addon panel for loading workflows and viewing job status.

    This panel is always visible and appears at the top of the category.
    """
    bl_idname = "ATLAS_PT_main_control_panel"
    bl_label = "MLXAR Workflow Control"
    bl_order = 0  # Ensures this panel is at the top

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Overrides the base class poll to ensure this panel is always visible."""
        return True

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        if state.job_running:
            box = layout.box()
            box.label(text="Job is running...")
            box.prop(state, "job_progress", text=state.job_status, slider=True)
            box.label(text=f"Elapsed Time: {state.job_elapsed_time}")
            return

        # --- IMPLEMENTING YOUR NEW 3-PART LAYOUT ---

        # --- Group Box 1: Load from File ---
        box_file = layout.box()

        # row.label(text="Load New Workflow:")
        box_file.operator("atlas.load_workflow", text="Load from File...", icon='FILE_FOLDER')
        # if state.is_active_workflow_savable:
        #     box_file.operator("atlas.save_active_workflow", text="Save to Library", icon='ADD')
        box_file.label(text="Workflow Library", icon='DOCUMENTS')

        # box_library.label(text="Load from Library:")
        box_file.prop(state, "saved_workflows_enum", text="")

        # layout.separator()

        # --- Group Box 3: Loaded Workflow ---
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

        # --- Final Global Action ---
        if state.active_api_id:
            layout.operator("atlas.clear_cache", text="Clear Cache", icon='TRASH')


class ATLAS_PT_WorkflowDetailsPanel(ATLAS_PT_BasePanel):
    """
    Displays the metadata for the currently loaded workflow.

    This panel only appears after a workflow has been loaded and is hidden
    during job execution.
    """
    bl_idname = "ATLAS_PT_workflow_details_panel"
    bl_label = "Workflow Details"  # Default label
    bl_order = 1  # Appears below the main control panel
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context: bpy.types.Context):
        """Draws a dynamic header title for the panel."""
        state = context.window_manager.atlas_workflow_state
        label = "Workflow Details"
        if state and state.active_name:
            label = f"Workflow: {state.active_name}"
        self.layout.label(text=label)

    def draw(self, context: bpy.types.Context):
        """Draws the metadata of the loaded workflow."""
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        box = layout.box()
        col = box.column(align=True)
        col.label(text=f"API ID: {state.active_api_id}")
        col.label(text=f"Base URL: {state.base_url or 'Not set'}")
        col.label(text=f"Version: {state.version or 'Not set'}")


class ATLAS_PT_InputsPanel(ATLAS_PT_BasePanel):
    """
    Displays all the input parameters for the currently loaded workflow.

    This panel is hidden when a job is running.
    """
    bl_idname = "ATLAS_PT_inputs_panel"
    bl_label = "Inputs"
    bl_order = 2  # Appears below the details panel

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        state = context.window_manager.atlas_workflow_state

        # Loop through each input parameter and draw its corresponding UI widget
        for item in state.inputs:
            draw_input_param(context, layout, item)

        layout.separator()
        # The main "Run" button is at the bottom of the inputs
        layout.operator("atlas.run_workflow", text="Run Workflow", icon='PLAY')


class ATLAS_PT_OutputsPanel(ATLAS_PT_BasePanel):
    """
    Displays the results from the last completed workflow run.

    This panel is hidden when a job is running.
    """
    bl_idname = "ATLAS_PT_outputs_panel"
    bl_label = "Outputs"
    bl_order = 3  # Appears below the inputs panel

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
    ATLAS_PT_MainControlPanel,
    ATLAS_PT_WorkflowDetailsPanel,  # Added the new panel
    ATLAS_PT_InputsPanel,
    ATLAS_PT_OutputsPanel,

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