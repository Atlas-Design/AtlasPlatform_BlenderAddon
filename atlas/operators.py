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
import json
from types import SimpleNamespace
from array import array
from dataclasses import dataclass, field
log = logging.getLogger("atlas_workflow")

# --- Blender and Addon-Specific Imports ---
import bpy
from bpy.props import StringProperty, IntProperty, CollectionProperty, EnumProperty
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
    from . import native_assets
    from .asset_types import (FILE_FORMATS, PRIMITIVE_TYPES, RASTER_TYPES, SCENE_INPUT_TYPES,
                              normalize_asset, output_extension, safe_file_key, compatible_asset, file_extension)
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
    import native_assets
    from asset_types import (FILE_FORMATS, PRIMITIVE_TYPES, RASTER_TYPES, SCENE_INPUT_TYPES,
                             normalize_asset, output_extension, safe_file_key, compatible_asset, file_extension)


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


_owned_temp_dirs = set()
_active_temp_dirs = set()


def create_job_temp_dir() -> str:
    """Allocate a directory owned by this session and protect it while in use."""
    path = os.path.realpath(tempfile.mkdtemp(prefix="atlas_workflow_"))
    _owned_temp_dirs.add(path)
    _active_temp_dirs.add(path)
    return path


def release_job_temp_dir(path: str) -> None:
    """Remove only this job's directory, after uploads and persistence finish."""
    if path not in _owned_temp_dirs:
        return
    _active_temp_dirs.discard(path)
    # Never follow a replaced directory outside the path we allocated.
    if os.path.realpath(path) != path:
        log.warning(f"[Atlas] Refusing to remove replaced temp directory: {path}")
        return
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning(f"[Atlas] Could not remove temp directory {path}: {exc}")
        return
    _owned_temp_dirs.discard(path)


def cleanup_old_temp_dirs() -> None:
    """Retry cleanup of inactive directories owned by this Blender session.

    Other jobs and other Blender processes may still need their files. Do not
    sweep the system temp directory based on a shared filename prefix.
    """
    for path in _owned_temp_dirs.copy() - _active_temp_dirs.copy():
        release_job_temp_dir(path)


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
    """Clean this session's unused temporary folders, preserving active jobs."""
    bl_idname = "atlas.clear_cache"
    bl_label = "Clear Addon Cache"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Runs the cleanup utility and reports the result."""
        cleanup_old_temp_dirs()
        self.report({'INFO'}, "Unused Atlas temporary files cleared; active jobs preserved.")
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
        
        # Preserve the inspected run when another job finishes or the list reorders.
        selected_id = ""
        if 0 <= state.job_history_index < len(state.job_history):
            selected_id = state.job_history[state.job_history_index].job_id
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
            if job.JobId == selected_id:
                state.job_history_index = len(state.job_history) - 1
            
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
        
        if state.job_history_index < 0:
            state.job_history_detail_mode = False
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


def _assign_image_material(obj, material) -> None:
    """Replace the active slot so its existing faces use the new material."""
    if obj.material_slots:
        obj.active_material = material
    else:
        obj.data.materials.append(material)
        obj.active_material_index = 0


def _save_image_as_png(image, path: str, file_format='PNG') -> None:
    """Save current pixels in a controlled format, without display transforms."""
    if file_format == 'OPEN_EXR':
        # Image.save applies the image's output conversion in Blender 5.1.
        # Render-save to EXR writes linear floats; a separate scene keeps the
        # user's render settings untouched and avoids quantization to PNG.
        export_scene = bpy.data.scenes.new('Atlas EXR Export')
        try:
            export_scene.render.image_settings.file_format = 'OPEN_EXR'
            export_scene.render.image_settings.color_depth = '32'
            export_scene.render.image_settings.color_mode = 'RGBA'
            image.save_render(path, scene=export_scene)
        finally:
            bpy.data.scenes.remove(export_scene)
        return
    export_image = image.copy()
    try:
        # Image.copy alone does not reliably copy unsaved pixel edits.
        pixels = array('f', [0.0]) * len(image.pixels)
        image.pixels.foreach_get(pixels)
        export_image.pixels.foreach_set(pixels)
        export_image.filepath_raw = path
        export_image.file_format = file_format
        export_image.save()
    finally:
        bpy.data.images.remove(export_image)


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
            _assign_image_material(active_obj, material)
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
    bl_description = "Select this run in Job History; expand the panel if it is collapsed"
    bl_options = {'REGISTER'}
    
    job_index: bpy.props.IntProperty(
        description="Index of the job to select", default=-1
    )
    job_id: bpy.props.StringProperty(description="Stable ID of the run to inspect")

    def execute(self, context: bpy.types.Context) -> set[str]:
        state = context.window_manager.atlas_workflow_state
        index = self.job_index
        if self.job_id:
            bpy.ops.atlas.refresh_job_history()
            index = next((i for i, job in enumerate(state.job_history)
                          if job.job_id == self.job_id), -1)
        if 0 <= index < len(state.job_history):
            state.filter_status = 'ALL'
            state.filter_workflow = 'ALL'
            state.filter_date = 'ALL'
            state.job_history_index = index
            state.job_history_detail_mode = True
            state.job_detail_outputs_expanded = True
            state.job_detail_inputs_expanded = False
            redraw_view3d_ui()
        else:
            self.report({'WARNING'}, "This job is no longer available in Job History.")
            return {'CANCELLED'}
        return {'FINISHED'}


class ATLAS_OT_DismissJobNotice(Operator):
    """Dismiss this notice; the run and its results remain in Job History"""
    bl_idname = "atlas.dismiss_job_notice"
    bl_label = "Dismiss Notification"
    job_id: bpy.props.StringProperty()

    def execute(self, context):
        notices = context.window_manager.atlas_workflow_state.job_notices
        for index, notice in enumerate(notices):
            if notice.job_id == self.job_id:
                notices.remove(index)
                break
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
    item_index: IntProperty(default=-1)
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')

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
        elif self.file_type == 'audio':
            self.filter_glob = '*.mp3;*.wav;*.ogg;*.flac;*.m4a'
        elif self.file_type == 'video':
            self.filter_glob = '*.mp4;*.webm;*.mov;*.avi'
        else:
            ext = FILE_FORMATS.get(self.file_type)
            self.filter_glob = f'*.{ext}' if ext else '*'

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        state = context.window_manager.atlas_workflow_state

        # Find the parameter in the state list by its ID
        target_param = next((p for p in state.inputs if p.param_id == self.param_id), None)

        if target_param:
            if target_param.is_array and self.item_index < 0:
                paths = [os.path.join(self.directory, entry.name) for entry in self.files] or [self.filepath]
                for path in paths:
                    entry = target_param.asset_items.add()
                    entry.source_type, entry.file_path = 'FILE', path
            else:
                if target_param.is_array and self.item_index >= len(target_param.asset_items):
                    return {'CANCELLED'}
                entry = target_param.asset_items[self.item_index] if target_param.is_array else target_param
                entry.source_type, entry.file_path = 'FILE', self.filepath

        return {'FINISHED'}


class ATLAS_OT_EditAssetList(Operator):
    """Edit an ordered input list without merging its assets."""
    bl_idname = 'atlas.edit_asset_list'
    bl_label = 'Edit Asset List'
    param_id: StringProperty()
    action: StringProperty(default='ADD')
    item_index: IntProperty(default=-1)

    def execute(self, context):
        state = context.window_manager.atlas_workflow_state
        param = next((p for p in state.inputs if p.param_id == self.param_id), None)
        if not param or not param.is_array:
            return {'CANCELLED'}
        items = param.asset_items
        if self.action == 'ADD':
            item = items.add()
            item.source_type = 'SCENE' if param.param_type in SCENE_INPUT_TYPES else 'FILE'
            item.frame_start, item.frame_end = context.scene.frame_start, context.scene.frame_end
        elif 0 <= self.item_index < len(items):
            if self.action == 'REMOVE':
                items.remove(self.item_index)
            else:
                destination = self.item_index + (-1 if self.action == 'UP' else 1)
                if 0 <= destination < len(items):
                    items.move(self.item_index, destination)
        return {'FINISHED'}


_reuse_targets = []


def _get_reuse_targets(self, context):
    global _reuse_targets
    state = context.window_manager.atlas_workflow_state
    _reuse_targets = [(p.param_id, p.label, p.param_type) for p in state.inputs
                      if compatible_asset(self.param_type, p.param_type)]
    return _reuse_targets


class ATLAS_OT_ReuseAsset(Operator):
    """Send a result asset ID to a compatible input without uploading again."""
    bl_idname = 'atlas.reuse_asset'
    bl_label = 'Use as Input'
    param_type: StringProperty()
    asset_data: StringProperty(options={'HIDDEN'})
    target_param: EnumProperty(name='Input', items=_get_reuse_targets)

    def invoke(self, context, event):
        if not _get_reuse_targets(self, context):
            self.report({'WARNING'}, 'Load a workflow with a compatible input first.')
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        state = context.window_manager.atlas_workflow_state
        target = next((p for p in state.inputs if p.param_id == self.target_param), None)
        if not target or not compatible_asset(self.param_type, target.param_type):
            return {'CANCELLED'}
        records = json.loads(self.asset_data)
        if any(r.get('ApiOrigin', '').rstrip('/') not in ('', state.base_url.rstrip('/')) for r in records):
            self.report({'ERROR'}, 'This asset belongs to a different Atlas API environment.')
            return {'CANCELLED'}
        if not records or any(not r.get('AssetId') for r in records):
            self.report({'ERROR'}, 'This result has no reusable asset ID.')
            return {'CANCELLED'}
        if not target.is_array and len(records) != 1:
            self.report({'ERROR'}, 'Choose an array input or reuse one item.')
            return {'CANCELLED'}
        for record in records:
            entry = target.asset_items.add() if target.is_array else target
            entry.source_type = 'ASSET'
            entry.asset_id = record['AssetId']
        target.provided = True
        return {'FINISHED'}


class ATLAS_OT_ImportMeshList(Operator):
    """Import downloaded meshes into separate collections."""
    bl_idname = 'atlas.import_mesh_list'
    bl_label = 'Import All Meshes'
    bl_options = {'REGISTER', 'UNDO'}
    paths_json: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        failures = []
        for index, path in enumerate(json.loads(self.paths_json)):
            try:
                previous = set(context.scene.objects)
                result = bpy.ops.import_scene.gltf(filepath=path)
                if 'FINISHED' not in result:
                    raise RuntimeError('Importer cancelled')
                collection = bpy.data.collections.new(f'Atlas Mesh {index + 1}')
                context.scene.collection.children.link(collection)
                for obj in set(context.scene.objects) - previous:
                    for owner in list(obj.users_collection):
                        owner.objects.unlink(obj)
                    collection.objects.link(obj)
            except Exception as exc:
                failures.append(f'{index + 1}: {exc}')
        if failures:
            self.report({'WARNING'}, '; '.join(failures))
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
        _assign_image_material(active_obj, material)
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


@dataclass
class WorkflowOutputResult:
    """Job-owned output schema and values, independent of Blender's UI state."""
    param_id: str
    label: str
    param_type: str
    bool_value: bool = False
    number_value: float = 0.0
    string_value: str = ""
    image_name: str = ""
    mesh_name: str = ""
    temp_file_path: str = ""
    is_array: bool = False
    file_format: str = ''
    items: list = field(default_factory=list)
    raw_value: object = None


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
    _output_params: list | None = None
    _workflow_key: tuple | None = None
    _cancelled: bool = False
    
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
                self._current_status = "uploading"
                for i, item in enumerate(upload_plan):
                    self._status_message = f"Uploading {os.path.basename(item['path'])} ({i + 1}/{len(upload_plan)})..."
                    file_id = client.upload_file(api_id, item['path'])
                    if item.get('index') is None:
                        payload[item['param_id']] = file_id
                    else:
                        payload[item['param_id']][item['index']] = file_id
                    log.info(f"[Atlas] Uploaded {item['param_id']}: {file_id}")

            # STAGE 2: EXECUTE WORKFLOW (ASYNC)
            self._status_message = "Submitting workflow..."
            self._current_status = "submitting"
            execution_id = client.execute_async(api_id, payload)
            log.info(f"[Atlas] Execution started: {execution_id}")

            # STAGE 3: POLL FOR COMPLETION
            self._status_message = "Waiting for execution..."
            self._current_status = "pending"
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
            errors = []
            for param_index, param in enumerate(self._output_params):
                param.raw_value = self._outputs_result.get(param.param_id)
                if param.param_type not in FILE_FORMATS or param.raw_value is None:
                    continue
                values = param.raw_value if param.is_array else [param.raw_value]
                if not isinstance(values, list):
                    errors.append(f'{param.label}: expected an array of assets')
                    continue
                for index, value in enumerate(values):
                    record = {'Index': index, 'AssetId': '', 'FilePath': '', 'Error': '',
                              'ApiOrigin': self._api_origin, 'Format': param.file_format}
                    param.items.append(record)
                    try:
                        asset = normalize_asset(value)
                        record.update(AssetId=asset.fid, DownloadUrl=asset.download_url,
                                      Mime=asset.mime, Filename=asset.filename, Size=asset.size)
                        ext = output_extension(param.param_type, param.file_format, asset.mime, asset.filename)
                        name = f'{param_index}_{safe_file_key(param.param_id)}_{index}.{ext}'
                        path = os.path.join(self._temp_dir, name)
                        self._status_message = f'Downloading {param.label} [{index + 1}/{len(values)}]...'
                        self._current_status = "downloading"
                        record['FilePath'] = client.download_file(api_id, value, path)
                        record['Format'] = file_extension(record['FilePath'])
                        self._import_plan.append({'param_id': param.param_id, 'type': param.param_type.upper(),
                                                  'path': record['FilePath'], 'index': index})
                    except Exception as exc:
                        record['Error'] = str(exc)
                        errors.append(f'{param.label}[{index}]: {exc}')

            if errors:
                self._error = '; '.join(errors)

            self._status_message = self._error or "Workflow finished successfully."
            self._current_status = "failed" if self._error else "completed"

        except Exception as e:
            # If anything goes wrong, record the error for the main thread.
            self._error = str(e)
            self._status_message = f"Error: {e}"
            self._current_status = "failed"
            log.error(f"[Atlas] Job failed: {e}")
        finally:
            # Signal to the main thread that the job is done.
            self._done = True
            if self._cancelled:
                release_job_temp_dir(self._temp_dir)

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

        # --- 1. Capture the workflow and allocate job-owned storage ---
        cleanup_old_temp_dirs()
        self._temp_dir = create_job_temp_dir()
        self._cancelled = False
        self._workflow_key = self._get_workflow_key(state)
        self._output_params = [
            WorkflowOutputResult(p.param_id, p.label, p.param_type,
                                 is_array=p.is_array, file_format=p.file_format)
            for p in state.outputs
        ]
        self._api_origin = state.base_url.rstrip('/')
        output_file_types = {}  # Output definitions are captured per job above.

        # --- 2. Build payload and upload plan from input parameters ---
        try:
            output_copy_root = preferences.prepare_output_copy_root(context)
            payload, upload_plan = self._build_payload(context, state)

        except Exception as e:
            self.report({'ERROR'}, str(e))
            release_job_temp_dir(self._temp_dir)
            return {'CANCELLED'}

        # --- 3. Create API client with preferences ---
        base_url = state.base_url.strip()
        preferences.configure_logging(context)
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
            release_job_temp_dir(self._temp_dir)
            return {'CANCELLED'}
        
        # Check storage limit warning
        if preferences.check_storage_limit(context):
            prefs = preferences.get_preferences(context)
            if prefs and prefs.warn_on_storage_limit:
                self.report({'WARNING'}, "Job storage warning threshold exceeded. Consider cleaning up old jobs.")

        # --- 4. Create job record for persistence ---
        inputs_snapshot = self._create_inputs_snapshot(state)
        try:
            self._job = job_manager.create_job(
                workflow_id=state.active_api_id,
                workflow_name=state.active_name,
                workflow_version=state.version,
                inputs_snapshot=inputs_snapshot,
                output_copy_root=output_copy_root,
            )
        except Exception as exc:
            release_job_temp_dir(self._temp_dir)
            self.report({'ERROR'}, f"Could not create job: {exc}")
            return {'CANCELLED'}
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
        self._current_status = "initializing"
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
        running_job.current_phase = "initializing"
        
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
        self.report({'INFO'}, f"{self._workflow_name}: Run started. View in Job History from Running Jobs.")
        
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

            if self._error and self._outputs_result is None:
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
                
                if preferences.should_notify(context, on_error=True):
                    self.report({'ERROR'}, f"{self._workflow_name}: {error_report}")
                log.error(f"[Atlas] Workflow failed: {error_report}")
                
                # Refresh job history so failed job appears
                bpy.ops.atlas.refresh_job_history()
                self._notify_completion(state, failed=True)
                
                redraw_view3d_ui()
                release_job_temp_dir(self._temp_dir)
                return {'CANCELLED'}

            # Persist this job's results even if another workflow is selected.
            try:
                self._update_primitive_outputs()
                self._process_import_plan(context)
                outputs_snapshot = self._create_outputs_snapshot()
                job_manager.complete_job(self._job, outputs_snapshot)
                try:
                    job_manager.export_output_copies(self._job)
                except OSError as exc:
                    self._error = '; '.join(filter(None, (self._error, str(exc))))
                if self._error:
                    job_manager.fail_job(self._job, self._error)
                self._publish_outputs(state)
            except Exception as exc:
                job_manager.fail_job(self._job, f"Could not save results: {exc}")
                if preferences.should_notify(context, on_error=True):
                    self.report({'ERROR'}, f"{self._workflow_name}: Could not save results: {exc}")
                bpy.ops.atlas.refresh_job_history()
                self._notify_completion(state, failed=True)
                redraw_view3d_ui()
                return {'CANCELLED'}
            finally:
                release_job_temp_dir(self._temp_dir)

            state.job_status = self._error or "Workflow complete"
            state.job_progress = 1.0
            if preferences.should_notify(context, on_error=bool(self._error)):
                self.report({'ERROR'} if self._error else {'INFO'},
                            f"{self._workflow_name}: {self._error or 'Completed successfully'}")
            log.info(f"[Atlas] Workflow {self._workflow_name}: {self._error or 'completed successfully'}")
            
            # Refresh job history so completed job appears
            bpy.ops.atlas.refresh_job_history()
            self._notify_completion(state, failed=bool(self._error))
            
            redraw_view3d_ui()
            return {'CANCELLED'} if self._error else {'FINISHED'}

        else:
            # --- JOB STILL RUNNING ---
            elapsed = time.time() - self._start_time
            elapsed_str = f"{elapsed:.1f}s"
            
            # Update running_job entry in collection
            self._update_running_job(state, self._status_message, elapsed_str, self._current_status)
            
            # Legacy state update
            state.job_elapsed_time = elapsed_str
            state.job_status = self._status_message
            state.job_progress = 0.0  # Server does not supply measured progress.

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
        self._cancelled = True
        if self._done:
            release_job_temp_dir(self._temp_dir)
        
        log.info(f"[Atlas] Workflow {self._workflow_name} cancelled by user")
        # Note: The background thread is not forcefully stopped, but it will
        # complete without affecting the Blender state further.

    def _notify_completion(self, state, failed=False):
        """Leave navigation to the user; each notice belongs to one run."""
        if not self._job or not preferences.should_notify(on_error=failed):
            return
        # Bound sidebar space; older runs always remain available in history.
        if len(state.job_notices) >= 5:
            state.job_notices.remove(0)
        notice = state.job_notices.add()
        notice.job_id = self._job.JobId
        notice.workflow_name = self._workflow_name
        notice.failed = failed

    def _update_running_job(self, state, status: str, elapsed: str, phase: str):
        """Update this job's entry in the running_jobs collection."""
        for job in state.running_jobs:
            if job.job_id == self._running_job_id:
                job.status = status
                job.progress = 0.0
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

    def _build_payload(self, context, state):
        payload, uploads = {}, []
        for position, item in enumerate(state.inputs):
            if not item.provided:
                if item.required == 'REQUIRED':
                    raise ValueError(f'{item.label} is required')
                continue
            if item.param_type in PRIMITIVE_TYPES and not item.is_array:
                attr = {'boolean': 'bool_value', 'number': 'number_value', 'string': 'string_value'}[item.param_type]
                payload[item.param_id] = getattr(item, attr)
                continue
            if item.param_type not in FILE_FORMATS:
                raise ValueError(f'{item.label}: unsupported input type {item.param_type}; omit it only if the API allows it')
            entries = item.asset_items if item.is_array else [item]
            if item.is_array:
                payload[item.param_id] = [None] * len(entries)
            for index, entry in enumerate(entries):
                if entry.source_type == 'ASSET':
                    fid = entry.asset_id.strip()
                    if not fid:
                        raise ValueError(f'{item.label}[{index}]: asset ID is empty')
                    if item.is_array:
                        payload[item.param_id][index] = fid
                    else:
                        payload[item.param_id] = fid
                    continue
                source = SimpleNamespace(
                    source_type=entry.source_type, file_path=entry.file_path,
                    image_name=entry.image_name, mesh_name=entry.mesh_name,
                    param_type=item.param_type, label=f'{item.label}[{index}]' if item.is_array else item.label,
                    param_id=f'{position}_{safe_file_key(item.param_id)}_{index}',
                    frame_start=entry.frame_start, frame_end=entry.frame_end,
                )
                path = self._prepare_datablock_for_upload(context, source)
                uploads.append({'param_id': item.param_id, 'path': path,
                                'index': index if item.is_array else None})
        return payload, uploads

    def _prepare_datablock_for_upload(self, context, item) -> str:
        """
        Gets the file path for an image or mesh input, creating a temporary
        file if necessary (e.g., for scene data).
        Returns the path to the file that should be uploaded.
        """
        if item.source_type == 'FILE':
            path = bpy.path.abspath(item.file_path)
            if not os.path.isfile(path):
                raise ValueError(f"Input file not found for '{item.label}': {item.file_path}")
            return path

        elif item.source_type == 'SCENE':
            if item.param_type == 'scene':
                return native_assets.export_scene_snapshot(context, os.path.join(self._temp_dir, f'{item.param_id}.blend'))
            if item.param_type == 'usdz':
                return native_assets.export_usdz(context, context.scene.objects.get(item.mesh_name),
                                                 os.path.join(self._temp_dir, f'{item.param_id}.usdz'))
            if item.param_type == 'rig_animation':
                return native_assets.export_animation(context, context.scene.objects.get(item.mesh_name),
                    os.path.join(self._temp_dir, f'{item.param_id}.glb'), item.frame_start, item.frame_end)
            if item.param_type in ('image', 'exr'):
                img = bpy.data.images.get(item.image_name)
                if not img:
                    raise ValueError(f"Input image not found in scene for '{item.label}': {item.image_name}")
                ext = 'exr' if item.param_type == 'exr' else 'png'
                temp_path = os.path.join(self._temp_dir, f"{item.param_id}.{ext}")
                _save_image_as_png(img, temp_path, 'OPEN_EXR' if ext == 'exr' else 'PNG')
                return temp_path

            elif item.param_type == "mesh":
                obj = context.scene.objects.get(item.mesh_name)
                if not obj:
                    raise ValueError(f"Input object not found for '{item.label}': {item.mesh_name}")

                # Export the specific object to a temporary GLB file
                temp_path = os.path.join(self._temp_dir, f"{item.param_id}.glb")

                view_layer = context.view_layer
                if obj.name not in view_layer.objects:
                    raise ValueError(f"Input object is excluded from the active view layer: {obj.name}")
                selected = [o for o in view_layer.objects if o.select_get()]
                active = view_layer.objects.active
                mode = active.mode if active else 'OBJECT'
                hidden, viewport_hidden, selection_locked = obj.hide_get(), obj.hide_viewport, obj.hide_select
                try:
                    if mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode='OBJECT')
                    for selected_obj in selected:
                        selected_obj.select_set(False)
                    obj.hide_viewport = False
                    obj.hide_set(False)
                    obj.hide_select = False
                    obj.select_set(True)
                    view_layer.objects.active = obj
                    result = bpy.ops.export_scene.gltf(
                        filepath=temp_path, use_selection=True, export_format='GLB'
                    )
                    if 'FINISHED' not in result:
                        raise RuntimeError(f"Could not export input object: {obj.name}")
                finally:
                    obj.select_set(False)
                    obj.hide_set(hidden)
                    obj.hide_viewport = viewport_hidden
                    obj.hide_select = selection_locked
                    for selected_obj in selected:
                        selected_obj.select_set(True)
                    view_layer.objects.active = active
                    if active and mode != 'OBJECT' and active.mode != mode:
                        bpy.ops.object.mode_set(mode=mode)
                return temp_path
        raise ValueError(f'{item.label}: select a file or existing asset; Blender data is not supported for {item.param_type}')

    def _update_primitive_outputs(self):
        """Updates the state properties for primitive output types (str, bool, num)."""
        if self._outputs_result is None:
            return
        for out_param in self._output_params:
            if out_param.param_id in self._outputs_result:
                value = self._outputs_result[out_param.param_id]
                out_param.raw_value = value
                try:
                    if out_param.param_type == "boolean":
                        out_param.bool_value = bool(value)
                    elif out_param.param_type == "number":
                        out_param.number_value = float(value)
                    elif out_param.param_type == "string":
                        out_param.string_value = str(value)
                except (ValueError, TypeError) as e:
                    log.warning(f"[Atlas] Could not set output '{out_param.param_id}': {e}")

    def _process_import_plan(self, context):
        """Processes the downloaded files, importing them into Blender."""
        auto_import_meshes = preferences.should_auto_import_meshes(context)
        auto_apply_images = preferences.should_auto_apply_images(context)
        
        for item in self._import_plan:
            out_param = next((p for p in self._output_params if p.param_id == item['param_id']), None)
            if not out_param:
                continue
            if out_param.is_array:
                continue  # Large result lists stay on disk until explicitly opened.
            # Persist downloads even if their Blender import fails.
            out_param.temp_file_path = item['path']

            if out_param.param_type in RASTER_TYPES:
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
                IsArray=getattr(item, 'is_array', False),
                Provided=getattr(item, 'provided', True),
                AssetId=getattr(item, 'asset_id', ''),
            )
            if snapshot.IsArray:
                snapshot.Items = [dict(Index=i, SourceType=entry.source_type, AssetId=entry.asset_id,
                                       FilePath=bpy.path.abspath(entry.file_path) if entry.source_type == 'FILE' else '',
                                       ImageValue=entry.image_name, MeshValue=entry.mesh_name,
                                       SceneValue=bpy.context.scene.name if item.param_type == 'scene' and entry.source_type == 'SCENE' else '',
                                       FrameStart=entry.frame_start if item.param_type == 'rig_animation' and entry.source_type == 'SCENE' else None,
                                       FrameEnd=entry.frame_end if item.param_type == 'rig_animation' and entry.source_type == 'SCENE' else None)
                                  for i, entry in enumerate(item.asset_items)]
            elif item.source_type == 'SCENE':
                if item.param_type == 'scene':
                    snapshot.SceneValue = bpy.context.scene.name
                elif item.param_type == 'rig_animation':
                    snapshot.FrameStart, snapshot.FrameEnd = item.frame_start, item.frame_end
            
            # Set values based on type
            if item.param_type == "boolean":
                snapshot.BoolValue = item.bool_value
            elif item.param_type == "number":
                snapshot.NumberValue = item.number_value
            elif item.param_type == "string":
                snapshot.StringValue = item.string_value
            elif item.param_type in FILE_FORMATS:
                snapshot.ImageValue = item.image_name
                snapshot.MeshValue = item.mesh_name
                snapshot.FilePath = bpy.path.abspath(item.file_path) if item.source_type == 'FILE' else None
            
            snapshots.append(snapshot)
        return snapshots

    def _create_outputs_snapshot(self) -> list:
        """Create a snapshot of all output parameters after job completion."""
        snapshots = []
        for position, item in enumerate(self._output_params):
            snapshot = ParamSnapshot(
                ParamId=item.param_id,
                Label=item.label,
                ParamType=item.param_type,
                IsArray=item.is_array,
                Format=item.file_format,
                ApiOrigin=getattr(self, '_api_origin', ''),
                RawValue=item.raw_value,
            )
            
            # Set values based on type
            if item.param_type == "boolean":
                snapshot.BoolValue = item.bool_value
            elif item.param_type == "number":
                snapshot.NumberValue = item.number_value
            elif item.param_type == "string":
                snapshot.StringValue = item.string_value
            elif item.param_type in FILE_FORMATS:
                snapshot.ImageValue = item.image_name
                snapshot.MeshValue = item.mesh_name
                for record in item.items:
                    if self._job and record.get('FilePath'):
                        key = f'{position}_{safe_file_key(item.param_id)}_{record["Index"]}'
                        record['FilePath'] = job_manager.save_output_file_to_job(self._job, key, record['FilePath'])
                snapshot.Items = [dict(r) for r in item.items]
                if not item.is_array and item.items:
                    first = item.items[0]
                    snapshot.FilePath = first.get('FilePath')
                    snapshot.AssetId = first.get('AssetId', '')
                    item.temp_file_path = snapshot.FilePath or ''
            
            snapshots.append(snapshot)
        return snapshots

    @staticmethod
    def _get_workflow_key(state) -> tuple:
        return (
            state.active_api_id, state.base_url, state.version,
            state.active_workflow_filepath,
            tuple((p.param_id, p.param_type, p.is_array, p.file_format) for p in state.outputs),
        )

    def _publish_outputs(self, state) -> None:
        """Update the selected workflow only when it still matches this job."""
        if self._get_workflow_key(state) != self._workflow_key:
            return
        fields = ('bool_value', 'number_value', 'string_value',
                  'image_name', 'mesh_name', 'temp_file_path')
        for target, result in zip(state.outputs, self._output_params):
            for name in fields:
                setattr(target, name, getattr(result, name))
            target.asset_id = result.items[0].get('AssetId', '') if result.items and not result.is_array else ''


# -------------------------------------------------------------------
# --- Blender Registration ---
# -------------------------------------------------------------------

classes = (
    *native_assets.classes,
    ATLAS_OT_EditAssetList,
    ATLAS_OT_ReuseAsset,
    ATLAS_OT_ImportMeshList,
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
    ATLAS_OT_DismissJobNotice,
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
