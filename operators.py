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
log = logging.getLogger("atlas_workflow")

# --- Third-Party Imports ---
# Try to import requests (needs to be installed into Blender's Python env)
try:
    import requests
except ImportError:
    # This variable will be checked in the operator to prevent errors.
    requests = None

# --- Blender and Addon-Specific Imports ---
import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .atlas_workflow_state import populate_state_from_definition
from .workflow_definition import WorkflowDefinition
from . import workflow_manager
from . import atlas_workflow_state


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
        self.report({'INFO'}, "MLXAR  temporary cache cleared.")
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


class ATLAS_OT_PickInputFile(Operator, ImportHelper):
    """Select a file with specific format filtering"""
    bl_idname = "mlxar.pick_input_file"  # Using the new branding
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
        """Finds the active material and adds the image as a texture."""
        active_obj = context.active_object
        if not active_obj:
            self.report({'ERROR'}, "No active object selected.")
            return {'CANCELLED'}

        if not self.image_name:
            self.report({'ERROR'}, "Internal error: No image name provided.")
            return {'CANCELLED'}

        image_datablock = bpy.data.images.get(self.image_name)
        if not image_datablock:
            self.report({'ERROR'}, f"Image '{self.image_name}' not found.")
            return {'CANCELLED'}

        material = active_obj.active_material
        if not material or not material.use_nodes:
            self.report({'ERROR'}, "Active object has no material or it does not use nodes.")
            return {'CANCELLED'}

        # Find the Principled BSDF node to connect to
        bsdf_node = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf_node:
            self.report({'ERROR'}, "No Principled BSDF node found in the material.")
            return {'CANCELLED'}

        # Create a new image texture node and link it
        tex_node = material.node_tree.nodes.new('ShaderNodeTexImage')
        tex_node.image = image_datablock
        tex_node.location = (bsdf_node.location.x - 400, bsdf_node.location.y)
        material.node_tree.links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])

        self.report({'INFO'}, f"Applied '{self.image_name}' to material '{material.name}'.")
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
    remote workflow, and then downloads the results. It uses a modal timer to
    keep the UI responsive and a separate thread for all network operations.
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
    _status_message: str = ""
    _import_plan: list = []  # A list of dicts describing downloaded files
    _outputs_result: dict | None = None

    # --- API Helper Methods (run in background thread) ---

    def _api_upload_file(self, base_url: str, version: str, api_id: str, file_path: str) -> str:
        """Uploads a single file and returns its file_id."""
        url = f"{base_url}/{version}/upload/{api_id}"
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            resp = requests.post(url, files=files, timeout=300)
        resp.raise_for_status()
        return resp.json()["file_id"]

    def _api_download_file(self, base_url: str, version: str, api_id: str, file_id: str, output_path: str) -> None:
        """Downloads a single file and saves it to the output_path."""
        url = f"{base_url}/{version}/download_binary_result/{api_id}/{file_id}"
        resp = requests.get(url, timeout=300)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)

    # --- Orchestrator (runs in background thread) ---

    def _job_thread(self, state_data: dict, payload: dict, upload_plan: list, output_file_types: dict):
        """
        Orchestrates the entire API flow in the background.
        This method handles uploading, execution, and downloading.
        """
        try:
            base_url = state_data['base_url']
            version = state_data['version']
            api_id = state_data['api_id']

            # STAGE 1: UPLOAD FILES
            if upload_plan:
                for i, item in enumerate(upload_plan):
                    self._status_message = f"Uploading {os.path.basename(item['path'])} ({i + 1}/{len(upload_plan)})..."
                    file_id = self._api_upload_file(base_url, version, api_id, item['path'])
                    payload[item['param_id']] = file_id  # Replace local path with remote file_id

            # STAGE 2: EXECUTE WORKFLOW
            self._status_message = "Executing remote workflow..."
            execute_url = f"{base_url}/{version}/api_execute/{api_id}"
            resp = requests.post(execute_url, json=payload, timeout=600)
            resp.raise_for_status()
            outputs = resp.json().get("outputs", {})
            self._outputs_result = outputs

            # STAGE 3: DOWNLOAD RESULTING FILES
            self._import_plan = []
            output_ids_to_download = {k: v for k, v in outputs.items() if k in output_file_types}

            if output_ids_to_download:
                count = len(output_ids_to_download)
                for i, (param_id, file_id) in enumerate(output_ids_to_download.items()):
                    self._status_message = f"Downloading result ({i + 1}/{count})..."
                    file_type = output_file_types[param_id]
                    ext = ".png" if file_type == 'IMAGE' else ".glb"
                    temp_path = os.path.join(self._temp_dir, f"{param_id}{ext}")

                    self._api_download_file(base_url, version, api_id, file_id, temp_path)
                    self._import_plan.append({'param_id': param_id, 'type': file_type, 'path': temp_path})

            self._status_message = "Workflow finished successfully."

        except Exception as e:
            # If anything goes wrong, record the error for the main thread.
            self._error = str(e)
            self._status_message = f"Error: {e}"
        finally:
            # Signal to the main thread that the job is done.
            self._done = True

    # --- Modal Operator Methods (run in main thread) ---

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Prepares data, starts the background thread, and enters modal mode."""
        if requests is None:
            self.report({'ERROR'}, "Python 'requests' module not installed. Please check addon preferences.")
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
        output_file_types = {p.param_id: p.param_type.upper() for p in state.outputs if
                             p.param_type in ('image', 'mesh')}

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

        # --- 3. Start the background job and modal timer ---
        state.job_running = True
        self._done = False
        self._error = None
        self._import_plan = []
        self._status_message = "Initializing..."
        self._start_time = time.time()

        base = state.base_url.strip().rstrip("/")
        state_data = {
            'base_url': f"https://{base}" if not base.startswith('http') else base,
            'version': state.version,
            'api_id': state.active_api_id,
        }

        # Start the background thread
        self._thread = threading.Thread(target=self._job_thread,
                                        args=(state_data, payload, upload_plan, output_file_types))
        self._thread.start()

        # Start the modal timer to check for thread completion
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
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
            state.job_running = False

            if self._error:
                # Handle errors from the background thread
                state.job_status = self._status_message
                self.report({'ERROR'}, state.job_status)
                return {'CANCELLED'}

            # --- SUCCESS: Update state and import results ---
            self._update_primitive_outputs(state)
            self._process_import_plan(state)

            state.job_status = "Workflow complete"
            state.job_progress = 1.0
            self.report({'INFO'}, "Workflow executed successfully.")
            redraw_view3d_ui()
            return {'FINISHED'}

        else:
            # --- JOB STILL RUNNING ---
            elapsed = time.time() - self._start_time
            state.job_elapsed_time = f"{elapsed:.1f}s"
            state.job_status = self._status_message

            # Create a pulsing progress bar effect
            spinner_period = 1.5
            state.job_progress = (elapsed % spinner_period) / spinner_period

            redraw_view3d_ui()
            return {'RUNNING_MODAL'}

    def cancel(self, context: bpy.types.Context):
        """Called when the operator is cancelled (e.g., by pressing ESC)."""
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        # Note: The background thread is not forcefully stopped, but it will
        # complete without affecting the Blender state further.

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
                    log.warning(f"[AtlasWorkflow] Could not set output '{out_param.param_id}': {e}")

    def _process_import_plan(self, state):
        """Processes the downloaded files, importing them into Blender."""
        for item in self._import_plan:
            out_param = next((p for p in state.outputs if p.param_id == item['param_id']), None)
            if not out_param:
                continue

            if item['type'] == 'IMAGE':
                try:
                    img = bpy.data.images.load(item['path'])
                    img.pack()  # Pack into the .blend file
                    out_param.image_name = img.name
                except Exception as e:
                    log.warning(f"Error importing image for {item['param_id']}: {e}")

            elif item['type'] == 'MESH':
                # For meshes, just store the path. The user can import it via a button.
                out_param.temp_file_path = item['path']
                out_param.mesh_name = f"Result: {out_param.label}"


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
    ATLAS_OT_PickInputFile
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