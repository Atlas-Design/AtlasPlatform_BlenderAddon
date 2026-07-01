# In operators.py
"""
Defines all the Blender Operators for the Atlas Workflow addon.

This module contains the classes that represent user-initiated actions, such as
loading a workflow, running it, and handling the resulting outputs (e.g.,
applying images, importing meshes).

The most significant operator is `ATLAS_OT_RunWorkflow`, a modal operator that
manages a background thread to perform network requests without freezing
Blender's user interface.
"""

# --- Standard Library Imports ---
import os
import shutil
import tempfile
import threading
import time
import logging
import uuid
log = logging.getLogger("atlas_workflow")

# --- Blender and Addon-Specific Imports ---
import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

try:
    from .atlas_workflow_state import populate_state_from_definition
    from .workflow_definition import WorkflowDefinition
    from . import workflow_manager
    from . import atlas_workflow_state
    from . import api_client
    from .api_client import AtlasAPIClient, ExecutionStatus
    from . import job_manager
    from .job_manager import JobRecord, JobStatus, ParamSnapshot
    from .job_manager import ExecutionStatus as JobExecutionStatus
    from . import preferences
except ImportError:
    from atlas_workflow_state import populate_state_from_definition
    from workflow_definition import WorkflowDefinition
    import workflow_manager
    import atlas_workflow_state
    import api_client
    from api_client import AtlasAPIClient, ExecutionStatus
    import job_manager
    from job_manager import JobRecord, JobStatus, ParamSnapshot
    from job_manager import ExecutionStatus as JobExecutionStatus
    import preferences


# -------------------------------------------------------------------
# --- Utility Functions ---
# -------------------------------------------------------------------

def redraw_view3d_ui() -> None:
    """
    Forces a redraw of all 3D View UI regions in the current window.

    This is useful for updating panels after a background operation completes.
    """
    if not bpy.context or not bpy.context.window_manager:
        return
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()


def cleanup_old_temp_dirs() -> None:
    """
    Finds and deletes all temporary directories created by this addon.

    This helps prevent clutter in the system's temporary folder from previous
    addon sessions.
    """
    temp_dir = tempfile.gettempdir()
    deleted_count = 0
    for dirname in os.listdir(temp_dir):
        if dirname.startswith("atlas_workflow_"):
            dirpath = os.path.join(temp_dir, dirname)
            try:
                shutil.rmtree(dirpath)
                deleted_count += 1
            except OSError as e:
                log.warning(f"Failed to delete old temp dir {dirpath}: {e}")

    if deleted_count > 0:
        log.warning(f"[AtlasWorkflow] Cleaned up {deleted_count} old temp directories.")


# -------------------------------------------------------------------
# --- Cache and File Operators ---
# -------------------------------------------------------------------

class ATLAS_OT_LoadWorkflow(Operator, ImportHelper):
    """Opens a file dialog to load and parse a workflow JSON file."""
    bl_idname = "atlas.load_workflow"
    bl_label = "Load Workflow from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper properties
    filename_ext: StringProperty(default=".json")
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Parses the selected file and populates the addon state."""
        state = context.window_manager.atlas_workflow_state
        try:
            workflow_def = WorkflowDefinition.from_json_file(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse workflow JSON: {e}")
            return {'CANCELLED'}

        try:
            populate_state_from_definition(context,state, workflow_def, source_filepath=self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to populate workflow state: {e}")
            return {'CANCELLED'}

        redraw_view3d_ui()
        self.report({'INFO'}, f"Loaded workflow: {workflow_def.name}")
        return {'FINISHED'}


class ATLAS_OT_ClearCache(Operator):
    """Deletes all temporary folders created by the Atlas addon."""
    bl_idname = "atlas.clear_cache"
    bl_label = "Clear Addon Cache"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Runs the cleanup utility and reports the result."""
        cleanup_old_temp_dirs()
        self.report({'INFO'}, "Atlas temporary cache cleared.")
        return {'FINISHED'}


class ATLAS_OT_SaveActiveWorkflow(Operator):
    """Saves the currently loaded workflow to the addon's persistent library."""
    bl_idname = "atlas.save_active_workflow"
    bl_label = "Save to Library"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.window_manager.atlas_workflow_state

        if not state.active_workflow_filepath:
            self.report({'ERROR'}, "No active workflow file to save.")
            return {'CANCELLED'}

        # Save the file to the library
        saved_path = workflow_manager.save_workflow_to_library(state.active_workflow_filepath)

        if saved_path:
            self.report({'INFO'}, f"Workflow '{os.path.basename(saved_path)}' saved.")
            # After saving, mark it as no longer needing to be saved
            state.is_active_workflow_savable = False
            # Force a redraw to update the UI (e.g., hide the save button)
            redraw_view3d_ui()
        else:
            self.report({'ERROR'}, "Failed to save workflow to library.")
            return {'CANCELLED'}

        return {'FINISHED'}


class ATLAS_OT_DeleteWorkflow(bpy.types.Operator):
    """Deletes the currently loaded workflow from the persistent library."""
    bl_idname = "atlas.delete_workflow"
    bl_label = "Delete Loaded Workflow"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Only allow running if the loaded workflow is in the library."""
        state = context.window_manager.atlas_workflow_state
        return state and workflow_manager.is_workflow_in_library(state.active_workflow_filepath)

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.window_manager.atlas_workflow_state
        # --- NOTE THE LOGIC CHANGE ---
        # Get the filename from the active state, not the dropdown.
        filename_to_delete = os.path.basename(state.active_workflow_filepath)

        if workflow_manager.delete_workflow_from_library(filename_to_delete):
            self.report({'INFO'}, f"Deleted '{filename_to_delete}'.")
            # Clear the entire state since the loaded workflow no longer exists.
            atlas_workflow_state.clear_workflow_state(state)
        else:
            self.report({'ERROR'}, "Failed to delete workflow.")
            return {'CANCELLED'}

        return {'FINISHED'}


class ATLAS_OT_RenameWorkflow(bpy.types.Operator):
    """Renames the currently loaded workflow in the persistent library."""
    bl_idname = "atlas.rename_workflow"
    bl_label = "Rename Loaded Workflow"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: bpy.props.StringProperty(name="New Name", description="Enter the new name")

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        """Only allow running if the loaded workflow is in the library."""
        state = context.window_manager.atlas_workflow_state
        return state and workflow_manager.is_workflow_in_library(state.active_workflow_filepath)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        state = context.window_manager.atlas_workflow_state
        current_filename = os.path.basename(state.active_workflow_filepath)
        self.new_name, _ = os.path.splitext(current_filename)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.window_manager.atlas_workflow_state
        old_filename = os.path.basename(state.active_workflow_filepath)

        new_filename = workflow_manager.rename_workflow_in_library(old_filename, self.new_name)

        if new_filename:
            # Update the state to point to the new file path
            new_path = os.path.join(workflow_manager.get_library_dir(), new_filename)
            state.active_workflow_filepath = new_path
            self.report({'INFO'}, f"Renamed to '{new_filename}'.")
        else:
            self.report({'ERROR'}, "Failed to rename workflow.")
            return {'CANCELLED'}

        return {'FINISHED'}


class ATLAS_OT_RefreshJobHistory(Operator):
    """Refresh the job history list from disk"""
    bl_idname = "atlas.refresh_job_history"
    bl_label = "Refresh Job History"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        from datetime import datetime, timezone
        
        state = context.window_manager.atlas_workflow_state
        
        # Clear existing history
        state.job_history.clear()
        state.job_history_index = -1
        
        # Load all jobs from disk
        jobs = job_manager.get_all_jobs()
        
        now = datetime.now(timezone.utc)
        
        for job in jobs:
            item = state.job_history.add()
            item.job_id = job.JobId
            item.workflow_name = job.WorkflowName
            item.created_at = job.CreatedAtUtc
            item.status = job.Status
            item.job_folder_path = job.JobFolderPath
            
            # Calculate display time
            try:
                created = datetime.fromisoformat(job.CreatedAtUtc.replace('Z', '+00:00'))
                age = now - created
                
                if age.total_seconds() < 60:
                    item.created_at_display = "just now"
                elif age.total_seconds() < 3600:
                    mins = int(age.total_seconds() / 60)
                    item.created_at_display = f"{mins}m ago"
                elif age.total_seconds() < 86400:
                    hours = int(age.total_seconds() / 3600)
                    item.created_at_display = f"{hours}h ago"
                elif age.days == 1:
                    item.created_at_display = "Yesterday"
                elif age.days < 7:
                    item.created_at_display = f"{age.days}d ago"
                else:
                    item.created_at_display = created.strftime("%b %d")
            except:
                item.created_at_display = "Unknown"
        
        self.report({'INFO'}, f"Loaded {len(jobs)} jobs")
        return {'FINISHED'}


class ATLAS_OT_OpenJobFolder(Operator):
    """Open the job folder in file explorer"""
    bl_idname = "atlas.open_job_folder"
    bl_label = "Open Job Folder"
    bl_options = {'REGISTER'}
    
    job_folder_path: StringProperty(
        description="Path to the job folder"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        import subprocess
        import sys
        
        if not self.job_folder_path or not os.path.exists(self.job_folder_path):
            self.report({'ERROR'}, "Job folder not found")
            return {'CANCELLED'}
        
        # Open folder in system file explorer
        if sys.platform == 'win32':
            os.startfile(self.job_folder_path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', self.job_folder_path])
        else:
            subprocess.run(['xdg-open', self.job_folder_path])
        
        return {'FINISHED'}


def _load_image_from_path(file_path: str):
    """Load an image file into Blender, reusing an existing datablock when possible."""
    return bpy.data.images.load(file_path, check_existing=True)


def _create_image_material(image_datablock, name_prefix: str = "Atlas Image"):
    """Create a new node material that displays the given image."""
    material_name = f"{name_prefix}: {image_datablock.name}"
    material = bpy.data.materials.new(material_name)
    material.use_nodes = True
    material.blend_method = 'BLEND'

    nodes = material.node_tree.nodes
    bsdf_node = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf_node:
        bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')

    tex_node = nodes.new('ShaderNodeTexImage')
    tex_node.image = image_datablock
    tex_node.location = (bsdf_node.location.x - 400, bsdf_node.location.y)
    material.node_tree.links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
    if 'Alpha' in tex_node.outputs and 'Alpha' in bsdf_node.inputs:
        material.node_tree.links.new(tex_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])

    return material


def _set_viewports_to_material_preview(context: bpy.types.Context) -> None:
    """Switch wireframe/solid 3D viewports to Material Preview so image textures are visible."""
    if not context.screen:
        return

    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type == 'VIEW_3D' and space.shading.type in {'WIREFRAME', 'SOLID'}:
                space.shading.type = 'MATERIAL'


class ATLAS_OT_ViewJobOutputImage(Operator):
    """Create a textured preview plane from a job output image."""
    bl_idname = "atlas.view_job_output_image"
    bl_label = "View Image"
    bl_options = {'REGISTER', 'UNDO'}
    
    file_path: StringProperty(
        description="Path to the image file"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not self.file_path or not os.path.exists(self.file_path):
            self.report({'ERROR'}, "Image file not found")
            return {'CANCELLED'}
        
        try:
            img = _load_image_from_path(self.file_path)
            width, height = img.size
            aspect = (width / height) if width > 0 and height > 0 else 1.0

            plane_height = 2.0
            plane_width = plane_height * aspect
            bpy.ops.mesh.primitive_plane_add(size=1, location=context.scene.cursor.location)
            plane = context.object
            plane.name = f"Atlas Image Preview: {os.path.splitext(os.path.basename(self.file_path))[0]}"
            plane.dimensions = (plane_width, plane_height, 0.0)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

            material = _create_image_material(img, "Atlas Preview")
            plane.data.materials.append(material)

            _set_viewports_to_material_preview(context)
            self.report({'INFO'}, f"Created image preview plane: {img.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create image preview: {e}")
            return {'CANCELLED'}
        
        return {'FINISHED'}


class ATLAS_OT_ApplyJobOutputImage(Operator):
    """Apply a job output image as a new material on the selected object."""
    bl_idname = "atlas.apply_job_output_image"
    bl_label = "Apply Image"
    bl_options = {'REGISTER', 'UNDO'}

    file_path: StringProperty(
        description="Path to the image file"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not self.file_path or not os.path.exists(self.file_path):
            self.report({'ERROR'}, "Image file not found")
            return {'CANCELLED'}

        active_obj = context.active_object
        if not active_obj or not hasattr(active_obj.data, "materials"):
            self.report({'ERROR'}, "Select an object before applying this image.")
            return {'CANCELLED'}

        try:
            img = _load_image_from_path(self.file_path)
            material = _create_image_material(img, "Atlas Output")
            active_obj.data.materials.append(material)
            active_obj.active_material_index = len(active_obj.data.materials) - 1
            _set_viewports_to_material_preview(context)
            self.report({'INFO'}, f"Applied '{img.name}' to '{active_obj.name}'.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to apply image: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class ATLAS_OT_ImportJobOutputMesh(Operator):
    """Import a mesh from job output"""
    bl_idname = "atlas.import_job_output_mesh"
    bl_label = "Import Mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    file_path: StringProperty(
        description="Path to the mesh file"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not self.file_path or not os.path.exists(self.file_path):
            self.report({'ERROR'}, "Mesh file not found")
            return {'CANCELLED'}
        
        try:
            # Import the GLB file
            bpy.ops.import_scene.gltf(filepath=self.file_path)
            self.report({'INFO'}, f"Imported mesh from: {os.path.basename(self.file_path)}")
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import mesh: {e}")
            return {'CANCELLED'}
        
        return {'FINISHED'}


class ATLAS_OT_OpenPreferences(Operator):
    """Open Atlas addon preferences"""
    bl_idname = "atlas.open_preferences"
    bl_label = "Atlas Settings"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        # Open the preferences window and navigate to add-ons
        bpy.ops.screen.userpref_show()
        
        # Try to navigate to our addon
        try:
            # Set the preferences section to Add-ons
            context.preferences.active_section = 'ADDONS'
        except:
            pass
        
        self.report({'INFO'}, "Opened preferences. Navigate to Add-ons > Atlas Workflow Integration")
        return {'FINISHED'}


class ATLAS_OT_CopyToClipboard(Operator):
    """Copy value to clipboard"""
    bl_idname = "atlas.copy_to_clipboard"
    bl_label = "Copy to Clipboard"
    bl_options = {'REGISTER'}
    
    value: StringProperty(
        description="Value to copy"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        context.window_manager.clipboard = self.value
        self.report({'INFO'}, f"Copied: {self.value[:50]}{'...' if len(self.value) > 50 else ''}")
        return {'FINISHED'}


class ATLAS_OT_ViewTextOutput(Operator):
    """Show a full text output in a dialog."""
    bl_idname = "atlas.view_text_output"
    bl_label = "View Text Output"
    bl_options = {'REGISTER'}

    title: StringProperty(
        default="Text Output",
        description="Text output label"
    )
    value: StringProperty(
        description="Full text value"
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text=self.title, icon='TEXT')

        box = layout.box()
        lines = self._wrap_text(self.value or "(empty)", 70)
        for line in lines:
            box.label(text=line)

        row = layout.row()
        op = row.operator("atlas.copy_to_clipboard", text="Copy Text", icon='COPYDOWN')
        op.value = self.value

    def execute(self, context: bpy.types.Context) -> set[str]:
        return {'FINISHED'}

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        wrapped_lines = []
        for raw_line in text.splitlines() or [""]:
            words = raw_line.split()
            if not words:
                wrapped_lines.append("")
                continue

            current = ""
            for word in words:
                if len(current) + len(word) + 1 <= max_chars:
                    current += (" " if current else "") + word
                else:
                    wrapped_lines.append(current)
                    current = word
            if current:
                wrapped_lines.append(current)
        return wrapped_lines


class ATLAS_OT_SelectJob(Operator):
    """View job details"""
    bl_idname = "atlas.select_job"
    bl_label = "View Job Details"
    bl_options = {'REGISTER'}
    
    job_index: bpy.props.IntProperty(
        description="Index of the job to select"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.window_manager.atlas_workflow_state
        if 0 <= self.job_index < len(state.job_history):
            state.job_history_index = self.job_index
            state.job_history_detail_mode = True
            state.job_detail_outputs_expanded = True
            state.job_detail_inputs_expanded = False
        return {'FINISHED'}


class ATLAS_OT_BackToJobList(Operator):
    """Return to job history list"""
    bl_idname = "atlas.back_to_job_list"
    bl_label = "Back to List"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.window_manager.atlas_workflow_state
        state.job_history_detail_mode = False
        return {'FINISHED'}


class ATLAS_OT_PickInputFile(Operator, ImportHelper):
    """Select a file with specific format filtering"""
    bl_idname = "atlas.pick_input_file"
    bl_label = "Select File"

    # We pass these arguments from the UI to tell the operator what to look for
    param_id: StringProperty()
    file_type: StringProperty()  # 'image' or 'mesh'

    # This is updated dynamically in invoke() based on file_type
    filter_glob: StringProperty(
        default="*",
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        # Set the filter based on whether it is an Image or a Mesh
        if self.file_type == 'image':
            self.filter_glob = "*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tif;*.tiff;*.webp"
        elif self.file_type == 'mesh':
            self.filter_glob = "*.glb;*.gltf"  # Restrict to GLB/GLTF as requested
        else:
            self.filter_glob = "*"

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        state = context.window_manager.atlas_workflow_state

        # Find the parameter in the state list by its ID
        target_param = next((p for p in state.inputs if p.param_id == self.param_id), None)

        if target_param:
            target_param.file_path = self.filepath
            # Optional: Report success to log
            # self.report({'INFO'}, f"Selected: {self.filepath}")

        return {'FINISHED'}

# -------------------------------------------------------------------
# --- Output Handling Operators ---
# -------------------------------------------------------------------

class ATLAS_OT_ApplyOutputImage(Operator):
    """Applies a generated image to the active object's material."""
    bl_idname = "atlas.apply_output_image"
    bl_label = "Apply to Active Object"
    bl_options = {'REGISTER', 'UNDO'}

    image_name: StringProperty(
        description="Name of the image datablock to apply"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Creates a new image material and assigns it to the active object."""
        active_obj = context.active_object
        if not active_obj or not hasattr(active_obj.data, "materials"):
            self.report({'ERROR'}, "Select an object before applying this image.")
            return {'CANCELLED'}

        if not self.image_name:
            self.report({'ERROR'}, "Internal error: No image name provided.")
            return {'CANCELLED'}

        image_datablock = bpy.data.images.get(self.image_name)
        if not image_datablock:
            self.report({'ERROR'}, f"Image '{self.image_name}' not found.")
            return {'CANCELLED'}

        material = _create_image_material(image_datablock, "Atlas Output")
        active_obj.data.materials.append(material)
        active_obj.active_material_index = len(active_obj.data.materials) - 1
        _set_viewports_to_material_preview(context)

        self.report({'INFO'}, f"Applied '{self.image_name}' to '{active_obj.name}'.")
        return {'FINISHED'}


class ATLAS_OT_ReplaceActiveWithMesh(Operator):
    """Replaces the active object with an imported GLB mesh."""
    bl_idname = "atlas.replace_active_with_mesh"
    bl_label = "Replace Active Object"
    bl_options = {'REGISTER', 'UNDO'}

    param_id: StringProperty(
        description="The parameter ID of the mesh output to use for replacement"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        active_obj = context.active_object
        if not active_obj:
            self.report({'ERROR'}, "No active object selected to replace.")
            return {'CANCELLED'}

        # Find the output parameter state to get the file path
        state = context.window_manager.atlas_workflow_state
        output_param = next((p for p in state.outputs if p.param_id == self.param_id), None)
        if not output_param or not output_param.temp_file_path or not os.path.exists(output_param.temp_file_path):
            self.report({'ERROR'}, "Downloaded file not found for this output.")
            return {'CANCELLED'}

        # 1. Store the transform of the old object
        original_transform = active_obj.matrix_world.copy()

        # 2. Import the new object(s) from the downloaded GLB
        bpy.ops.import_scene.gltf(filepath=output_param.temp_file_path)
        imported_objs = context.selected_objects
        if not imported_objs:
            self.report({'ERROR'}, "GLB import failed to create any objects.")
            bpy.data.objects.remove(active_obj, do_unlink=True)
            return {'CANCELLED'}

        # 3. Apply the original transform to all newly imported objects
        for obj in imported_objs:
            obj.matrix_world = original_transform

        # 4. Delete the original object
        bpy.data.objects.remove(active_obj, do_unlink=True)

        self.report({'INFO'}, "Replaced active object with imported mesh.")
        return {'FINISHED'}


class ATLAS_OT_SaveOutputImage(Operator, ImportHelper):
    """Saves a generated image datablock to an external file."""
    bl_idname = "atlas.save_output_image"
    bl_label = "Save Image As..."
    bl_options = {'REGISTER'}

    # --- Properties for Operator and ImportHelper ---
    image_name: StringProperty(
        description="Name of the Blender image datablock to save"
    )
    filename_ext: StringProperty(default=".png")
    filter_glob: StringProperty(default="*.png;*.jpg;*.bmp", options={'HIDDEN'})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        """Sets a default filename and opens the file browser."""
        if self.image_name:
            base_name, _ = os.path.splitext(self.image_name)
            self.filepath = base_name + self.filename_ext
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not self.image_name:
            self.report({'ERROR'}, "Internal error: No image name provided.")
            return {'CANCELLED'}

        image_datablock = bpy.data.images.get(self.image_name)
        if not image_datablock:
            self.report({'ERROR'}, f"Image '{self.image_name}' not found in Blender data.")
            return {'CANCELLED'}

        try:
            # save_render handles path and format details.
            image_datablock.save_render(filepath=self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save image: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Image saved to {self.filepath}")
        return {'FINISHED'}


class ATLAS_OT_ImportOutputMesh(Operator):
    """Imports a downloaded GLB file into the current scene."""
    bl_idname = "atlas.import_output_mesh"
    bl_label = "Import GLB"
    bl_options = {'REGISTER', 'UNDO'}

    param_id: StringProperty(
        description="The parameter ID of the mesh output to import"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not self.param_id:
            self.report({'ERROR'}, "Internal error: No parameter ID provided.")
            return {'CANCELLED'}

        # Find the corresponding output parameter in the addon state
        state = context.window_manager.atlas_workflow_state
        output_param = next((p for p in state.outputs if p.param_id == self.param_id), None)
        if not output_param:
            self.report({'ERROR'}, f"Output parameter '{self.param_id}' not found.")
            return {'CANCELLED'}

        file_path = output_param.temp_file_path
        if not file_path or not os.path.exists(file_path):
            self.report({'ERROR'}, f"Downloaded file for '{self.param_id}' not found.")
            return {'CANCELLED'}

        # Import the GLB file
        try:
            bpy.ops.import_scene.gltf(filepath=file_path)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import GLB: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Imported mesh for {self.param_id}")
        return {'FINISHED'}


# -------------------------------------------------------------------
# --- Main Workflow Execution Operator (Modal) ---
# -------------------------------------------------------------------


class ATLAS_OT_RunWorkflow(Operator):
    """
    Executes the full Atlas workflow using a modal, background-threaded process.

    This operator prepares input data, uploads necessary files, triggers the
    remote workflow via async API, polls for completion, and then downloads 
    the results. It uses a modal timer to keep the UI responsive and a 
    separate thread for all network operations.
    
    NEW API FLOW (async with polling):
    1. Upload files → get file_ids
    2. Execute async → get execution_id
    3. Poll status until completed/failed
    4. Download output files
    """
    bl_idname = "atlas.run_workflow"
    bl_label = "Run Workflow"
    bl_options = {'REGISTER'}

    # --- Modal Operator State ---
    # These are managed by the main Blender thread.
    _timer: bpy.types.Timer | None = None
    _thread: threading.Thread | None = None
    _start_time: float = 0.0
    _temp_dir: str = ""

    # --- Thread-safe Communication State ---
    # These variables are written to by the background thread and read by the
    # main thread's modal() method.
    _done: bool = False
    _error: str | None = None
    _error_details: str | None = None  # Additional error context (node info)
    _error_node_name: str | None = None
    _error_node_type: str | None = None
    _error_node_id: str | None = None
    _status_message: str = ""
    _current_status: str = ""  # pending, running, completed, failed
    _import_plan: list = []  # A list of dicts describing downloaded files
    _outputs_result: dict | None = None
    
    # --- Job Persistence ---
    _job: JobRecord | None = None
    
    # --- Running Job UI Tracking ---
    _running_job_id: str = ""  # ID to find this job in running_jobs collection
    _workflow_name: str = ""  # Store workflow name for UI
    
    # --- Settings (from preferences) ---
    _poll_interval: float = 2.0  # Polling interval in seconds

    # --- Orchestrator (runs in background thread) ---

    def _job_thread(self, client: AtlasAPIClient, api_id: str, payload: dict, 
                    upload_plan: list, output_file_types: dict):
        """
        Orchestrates the entire API flow in the background using the new async pattern.
        
        Flow:
        1. Upload files → get file_ids
        2. Execute async → get execution_id  
        3. Poll status until completed/failed
        4. Download output files
        """
        try:
            # STAGE 1: UPLOAD FILES
            if upload_plan:
                for i, item in enumerate(upload_plan):
                    self._status_message = f"Uploading {os.path.basename(item['path'])} ({i + 1}/{len(upload_plan)})..."
                    file_id = client.upload_file(api_id, item['path'])
                    payload[item['param_id']] = file_id  # Replace local path with remote file_id
                    log.info(f"[Atlas] Uploaded {item['param_id']}: {file_id}")

            # STAGE 2: EXECUTE WORKFLOW (ASYNC)
            self._status_message = "Submitting workflow..."
            self._current_status = "pending"
            execution_id = client.execute_async(api_id, payload)
            log.info(f"[Atlas] Execution started: {execution_id}")

            # STAGE 3: POLL FOR COMPLETION
            self._status_message = "Waiting for execution..."
            while True:
                time.sleep(self._poll_interval)
                
                result = client.poll_status(execution_id)
                self._current_status = result.status.value
                
                # Update status message based on state
                if result.status == ExecutionStatus.PENDING:
                    self._status_message = "Queued, waiting to start..."
                elif result.status == ExecutionStatus.RUNNING:
                    self._status_message = "Workflow running..."
                
                log.debug(f"[Atlas] Poll status: {result.status.value}")
                
                # Check for terminal states
                if result.is_failed:
                    error_msg = "Workflow execution failed"
                    if result.error:
                        error_msg = result.error.format_message()
                        self._error_details = f"Node: {result.error.node_name or 'unknown'}"
                        self._error_node_name = result.error.node_name
                        self._error_node_type = result.error.node_type
                        self._error_node_id = result.error.node_id
                    raise RuntimeError(error_msg)
                
                if result.is_complete:
                    self._outputs_result = result.outputs
                    log.info(f"[Atlas] Execution completed. Outputs: {list(result.outputs.keys())}")
                    break

            # STAGE 4: DOWNLOAD RESULTING FILES
            self._import_plan = []
            output_ids_to_download = {
                k: v for k, v in self._outputs_result.items() 
                if k in output_file_types and v  # Only download if we have a file_id
            }

            if output_ids_to_download:
                count = len(output_ids_to_download)
                for i, (param_id, file_id) in enumerate(output_ids_to_download.items()):
                    self._status_message = f"Downloading result ({i + 1}/{count})..."
                    file_type = output_file_types[param_id]
                    ext = ".png" if file_type == 'IMAGE' else ".glb"
                    temp_path = os.path.join(self._temp_dir, f"{param_id}{ext}")

                    client.download_file(api_id, file_id, temp_path)
                    self._import_plan.append({
                        'param_id': param_id, 
                        'type': file_type, 
                        'path': temp_path
                    })
                    log.info(f"[Atlas] Downloaded {param_id} to {temp_path}")

            self._status_message = "Workflow finished successfully."
            self._current_status = "completed"

        except Exception as e:
            # If anything goes wrong, record the error for the main thread.
            self._error = str(e)
            self._status_message = f"Error: {e}"
            self._current_status = "failed"
            log.error(f"[Atlas] Job failed: {e}")
        finally:
            # Signal to the main thread that the job is done.
            self._done = True

    # --- Modal Operator Methods (run in main thread) ---

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Prepares data, starts the background thread, and enters modal mode."""
        # Check if api_client module is available
        if not api_client.is_requests_available():
            self.report({'ERROR'}, "Bundled HTTP client missing. Reinstall the complete Atlas addon package.")
            return {'CANCELLED'}

        state = context.window_manager.atlas_workflow_state
        if not state.active_api_id:
            self.report({'ERROR'}, "No workflow loaded.")
            return {'CANCELLED'}

        # --- 1. Pre-run cleanup and setup ---
        cleanup_old_temp_dirs()
        self._temp_dir = tempfile.mkdtemp(prefix="atlas_workflow_")
        payload = {}
        upload_plan = []
        output_file_types = {
            p.param_id: p.param_type.upper() 
            for p in state.outputs 
            if p.param_type in ('image', 'mesh')
        }

        # --- 2. Build payload and upload plan from input parameters ---
        try:
            for item in state.inputs:
                if item.param_type == "boolean":
                    payload[item.param_id] = item.bool_value
                elif item.param_type == "number":
                    payload[item.param_id] = item.number_value
                elif item.param_type == "string":
                    payload[item.param_id] = item.string_value
                elif item.param_type in ("image", "mesh"):
                    path_to_upload = self._prepare_datablock_for_upload(context, item)
                    if path_to_upload:
                        upload_plan.append({'param_id': item.param_id, 'path': path_to_upload})

        except Exception as e:
            self.report({'ERROR'}, str(e))
            shutil.rmtree(self._temp_dir)
            return {'CANCELLED'}

        # --- 3. Create API client with preferences ---
        base_url = state.base_url.strip()
        timeout = preferences.get_effective_timeout(context)
        self._poll_interval = preferences.get_poll_interval(context)
        api_key = preferences.get_workspace_api_key(context)
        
        try:
            client = AtlasAPIClient(
                base_url=base_url,
                version=state.version,
                timeout=timeout if timeout else 0,  # 0 means no timeout in requests
                api_key=api_key
            )
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            shutil.rmtree(self._temp_dir)
            return {'CANCELLED'}
        
        # Check storage limit warning
        if preferences.check_storage_limit(context):
            prefs = preferences.get_preferences(context)
            if prefs and prefs.warn_on_storage_limit:
                self.report({'WARNING'}, "Job storage limit exceeded. Consider cleaning up old jobs.")

        # --- 4. Create job record for persistence ---
        inputs_snapshot = self._create_inputs_snapshot(state)
        self._job = job_manager.create_job(
            workflow_id=state.active_api_id,
            workflow_name=state.active_name,
            workflow_version=state.version,
            inputs_snapshot=inputs_snapshot
        )
        log.info(f"[Atlas] Created job record: {self._job.JobId[:8]}")

        # --- 5. Start the background job and modal timer ---
        self._done = False
        self._error = None
        self._error_details = None
        self._error_node_name = None
        self._error_node_type = None
        self._error_node_id = None
        self._import_plan = []
        self._outputs_result = None
        self._status_message = "Initializing..."
        self._current_status = "pending"
        self._start_time = time.time()
        
        # Store workflow name for this job
        self._workflow_name = state.active_name
        
        # Set formatted start time for UI display
        from datetime import datetime
        started_at = datetime.now().strftime("%H:%M:%S")
        
        # Add this job to the running_jobs collection
        self._running_job_id = self._job.JobId if self._job else str(uuid.uuid4())
        running_job = state.running_jobs.add()
        running_job.job_id = self._running_job_id
        running_job.workflow_name = self._workflow_name
        running_job.status = "Initializing..."
        running_job.progress = 0.0
        running_job.started_at = started_at
        running_job.elapsed_time = "0.0s"
        running_job.current_phase = "pending"
        
        # Legacy single-job state (for backwards compatibility)
        state.job_running = True
        state.job_started_at = started_at

        # Start the background thread with the new API client
        self._thread = threading.Thread(
            target=self._job_thread,
            args=(client, state.active_api_id, payload, upload_plan, output_file_types)
        )
        self._thread.start()

        # Start the modal timer to check for thread completion
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        log.info(f"[Atlas] Started workflow execution: {state.active_name}")
        return {'RUNNING_MODAL'}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        """
        Periodically checks the background thread's status and updates the UI.
        Runs on every timer event until the operator finishes or is cancelled.
        """
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        state = context.window_manager.atlas_workflow_state

        if self._done:
            # --- JOB FINISHED ---
            wm = context.window_manager
            wm.event_timer_remove(self._timer)
            
            # Remove this job from running_jobs collection
            self._remove_running_job(state)
            
            # Update legacy state
            state.job_running = len(state.running_jobs) > 0

            if self._error:
                # Handle errors from the background thread
                state.job_status = self._status_message
                error_report = self._error
                if self._error_details:
                    error_report += f" ({self._error_details})"
                
                # Fail the job record
                if self._job:
                    job_manager.fail_job(
                        self._job,
                        error_message=self._error,
                        node_name=self._error_node_name,
                        node_type=self._error_node_type,
                        node_id=self._error_node_id
                    )
                
                self.report({'ERROR'}, f"{self._workflow_name}: {error_report}")
                log.error(f"[Atlas] Workflow failed: {error_report}")
                
                # Refresh job history so failed job appears
                bpy.ops.atlas.refresh_job_history()
                
                redraw_view3d_ui()
                return {'CANCELLED'}

            # --- SUCCESS: Update state and import results ---
            self._update_primitive_outputs(state)
            self._process_import_plan(state, context)
            
            # Complete the job record with outputs
            if self._job:
                outputs_snapshot = self._create_outputs_snapshot(state)
                job_manager.complete_job(self._job, outputs_snapshot)

            state.job_status = "Workflow complete"
            state.job_progress = 1.0
            self.report({'INFO'}, f"{self._workflow_name}: Completed successfully")
            log.info(f"[Atlas] Workflow {self._workflow_name} completed successfully")
            
            # Refresh job history so completed job appears
            bpy.ops.atlas.refresh_job_history()
            
            redraw_view3d_ui()
            return {'FINISHED'}

        else:
            # --- JOB STILL RUNNING ---
            elapsed = time.time() - self._start_time
            elapsed_str = f"{elapsed:.1f}s"
            
            # Calculate progress for UI
            if self._current_status == "running":
                spinner_period = 2.0
                progress = 0.2 + 0.6 * ((elapsed % spinner_period) / spinner_period)
            else:
                spinner_period = 3.0
                progress = 0.1 * ((elapsed % spinner_period) / spinner_period)
            
            # Update running_job entry in collection
            self._update_running_job(state, self._status_message, progress, elapsed_str, self._current_status)
            
            # Legacy state update
            state.job_elapsed_time = elapsed_str
            state.job_status = self._status_message
            state.job_progress = progress

            redraw_view3d_ui()
            return {'RUNNING_MODAL'}

    def cancel(self, context: bpy.types.Context):
        """Called when the operator is cancelled (e.g., by pressing ESC)."""
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        state = context.window_manager.atlas_workflow_state
        
        # Remove this job from running_jobs
        self._remove_running_job(state)
        state.job_running = len(state.running_jobs) > 0
        
        log.info(f"[Atlas] Workflow {self._workflow_name} cancelled by user")
        # Note: The background thread is not forcefully stopped, but it will
        # complete without affecting the Blender state further.

    def _update_running_job(self, state, status: str, progress: float, elapsed: str, phase: str):
        """Update this job's entry in the running_jobs collection."""
        for job in state.running_jobs:
            if job.job_id == self._running_job_id:
                job.status = status
                job.progress = progress
                job.elapsed_time = elapsed
                job.current_phase = phase
                break

    def _remove_running_job(self, state):
        """Remove this job from the running_jobs collection."""
        for i, job in enumerate(state.running_jobs):
            if job.job_id == self._running_job_id:
                state.running_jobs.remove(i)
                break

    # --- Helper methods for execute() and modal() ---

    def _prepare_datablock_for_upload(self, context, item) -> str:
        """
        Gets the file path for an image or mesh input, creating a temporary
        file if necessary (e.g., for scene data).
        Returns the path to the file that should be uploaded.
        """
        if item.source_type == 'FILE':
            if not os.path.exists(item.file_path):
                raise ValueError(f"Input file not found for '{item.label}': {item.file_path}")
            return item.file_path

        elif item.source_type == 'SCENE':
            if item.param_type == "image":
                img = bpy.data.images.get(item.image_name)
                if not img:
                    raise ValueError(f"Input image not found in scene for '{item.label}': {item.image_name}")
                temp_path = os.path.join(self._temp_dir, f"{item.param_id}.png")
                img.save_render(filepath=temp_path)
                return temp_path

            elif item.param_type == "mesh":
                obj = context.scene.objects.get(item.mesh_name)
                if not obj:
                    raise ValueError(f"Input object not found for '{item.label}': {item.mesh_name}")

                # Export the specific object to a temporary GLB file
                temp_path = os.path.join(self._temp_dir, f"{item.param_id}.glb")

                # Use a context override or temporary selection for precise export
                with context.temp_override(active_object=obj, selected_objects=[obj]):
                    bpy.ops.export_scene.gltf(filepath=temp_path, use_selection=True, export_format='GLB')
                return temp_path
        return ""

    def _update_primitive_outputs(self, state):
        """Updates the state properties for primitive output types (str, bool, num)."""
        if self._outputs_result is None:
            return
        for out_param in state.outputs:
            if out_param.param_id in self._outputs_result:
                value = self._outputs_result[out_param.param_id]
                try:
                    if out_param.param_type == "boolean":
                        out_param.bool_value = bool(value)
                    elif out_param.param_type == "number":
                        out_param.number_value = float(value)
                    elif out_param.param_type == "string":
                        out_param.string_value = str(value)
                except (ValueError, TypeError) as e:
                    log.warning(f"[Atlas] Could not set output '{out_param.param_id}': {e}")

    def _process_import_plan(self, state, context):
        """Processes the downloaded files, importing them into Blender."""
        auto_import_meshes = preferences.should_auto_import_meshes(context)
        auto_apply_images = preferences.should_auto_apply_images(context)
        
        for item in self._import_plan:
            out_param = next((p for p in state.outputs if p.param_id == item['param_id']), None)
            if not out_param:
                continue

            if item['type'] == 'IMAGE':
                try:
                    img = bpy.data.images.load(item['path'])
                    img.pack()  # Pack into the .blend file
                    out_param.image_name = img.name
                    out_param.temp_file_path = item['path']  # Store for job persistence
                    
                    # Auto-apply image to active object if enabled
                    if auto_apply_images and context.active_object:
                        try:
                            bpy.ops.atlas.apply_output_image(image_name=img.name)
                            log.info(f"[Atlas] Auto-applied image to active object")
                        except Exception as e:
                            log.warning(f"[Atlas] Could not auto-apply image: {e}")
                            
                except Exception as e:
                    log.warning(f"[Atlas] Error importing image for {item['param_id']}: {e}")

            elif item['type'] == 'MESH':
                out_param.temp_file_path = item['path']
                out_param.mesh_name = f"Result: {out_param.label}"
                
                # Auto-import mesh if enabled
                if auto_import_meshes:
                    try:
                        bpy.ops.import_scene.gltf(filepath=item['path'])
                        log.info(f"[Atlas] Auto-imported mesh: {item['param_id']}")
                    except Exception as e:
                        log.warning(f"[Atlas] Could not auto-import mesh: {e}")

    def _create_inputs_snapshot(self, state) -> list:
        """Create a snapshot of all input parameters for job persistence."""
        snapshots = []
        for item in state.inputs:
            snapshot = ParamSnapshot(
                ParamId=item.param_id,
                Label=item.label,
                ParamType=item.param_type,
                SourceType=0 if item.source_type == 'SCENE' else 1,
            )
            
            # Set values based on type
            if item.param_type == "boolean":
                snapshot.BoolValue = item.bool_value
            elif item.param_type == "number":
                snapshot.NumberValue = item.number_value
            elif item.param_type == "string":
                snapshot.StringValue = item.string_value
            elif item.param_type == "image":
                snapshot.ImageValue = item.image_name
                snapshot.FilePath = item.file_path if item.source_type == 'FILE' else None
            elif item.param_type == "mesh":
                snapshot.MeshValue = item.mesh_name
                snapshot.FilePath = item.file_path if item.source_type == 'FILE' else None
            
            snapshots.append(snapshot)
        return snapshots

    def _create_outputs_snapshot(self, state) -> list:
        """Create a snapshot of all output parameters after job completion."""
        snapshots = []
        for item in state.outputs:
            snapshot = ParamSnapshot(
                ParamId=item.param_id,
                Label=item.label,
                ParamType=item.param_type,
            )
            
            # Set values based on type
            if item.param_type == "boolean":
                snapshot.BoolValue = item.bool_value
            elif item.param_type == "number":
                snapshot.NumberValue = item.number_value
            elif item.param_type == "string":
                snapshot.StringValue = item.string_value
            elif item.param_type == "image":
                snapshot.ImageValue = item.image_name
                # Save output file to job folder
                if self._job and item.temp_file_path:
                    saved_path = job_manager.save_output_file_to_job(
                        self._job, item.param_id, item.temp_file_path
                    )
                    snapshot.FilePath = saved_path
            elif item.param_type == "mesh":
                snapshot.MeshValue = item.mesh_name
                # Save output file to job folder
                if self._job and item.temp_file_path:
                    saved_path = job_manager.save_output_file_to_job(
                        self._job, item.param_id, item.temp_file_path
                    )
                    snapshot.FilePath = saved_path
            
            snapshots.append(snapshot)
        return snapshots


# -------------------------------------------------------------------
# --- Blender Registration ---
# -------------------------------------------------------------------

classes = (
    ATLAS_OT_LoadWorkflow,
    ATLAS_OT_SaveActiveWorkflow,
    ATLAS_OT_DeleteWorkflow,
    ATLAS_OT_RenameWorkflow,
    ATLAS_OT_ClearCache,
    ATLAS_OT_ApplyOutputImage,
    ATLAS_OT_ReplaceActiveWithMesh,
    ATLAS_OT_SaveOutputImage,
    ATLAS_OT_ImportOutputMesh,
    ATLAS_OT_RunWorkflow,
    ATLAS_OT_PickInputFile,
    ATLAS_OT_RefreshJobHistory,
    ATLAS_OT_OpenJobFolder,
    ATLAS_OT_ViewJobOutputImage,
    ATLAS_OT_ApplyJobOutputImage,
    ATLAS_OT_ImportJobOutputMesh,
    ATLAS_OT_OpenPreferences,
    ATLAS_OT_CopyToClipboard,
    ATLAS_OT_ViewTextOutput,
    ATLAS_OT_SelectJob,
    ATLAS_OT_BackToJobList,
)


def register():
    """Registers all operator classes with Blender."""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregisters all operator classes from Blender."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()