# In workflow_manager.py
"""
Manages the persistent library of saved workflow JSON files.

This module provides functions to:
- Get the path to the addon's persistent data directory.
- Save a workflow file into that directory.
- List all saved workflows for use in a UI dropdown.
"""

import bpy
import os
import shutil
import logging
log = logging.getLogger("atlas_workflow")

# --- Directory Management ---

def get_library_dir() -> str:
    """
    Finds or creates the persistent directory for storing workflow JSONs.

    This will be a folder like:
    .../4.0/scripts/addons/atlas_workflow_addon/atlas_workflows/

    Returns:
        The absolute path to the library directory.
    """
    # Get the directory of the currently running addon
    addon_dir = os.path.dirname(__file__)
    library_dir = os.path.join(addon_dir, "atlas_workflows")

    # Create the directory if it doesn't exist
    if not os.path.exists(library_dir):
        os.makedirs(library_dir)

    return library_dir

# --- Workflow Management ---

def is_workflow_in_library(filepath: str) -> bool:
    """Checks if a workflow file already exists in the library."""
    if not filepath:
        return False
    library_dir = get_library_dir()
    filename = os.path.basename(filepath)
    return os.path.exists(os.path.join(library_dir, filename))


def save_workflow_to_library(source_filepath: str) -> str | None:
    """
    Copies a workflow JSON file from a source path into the library.

    Args:
        source_filepath: The path to the .json file to copy.

    Returns:
        The path to the newly saved file in the library, or None on failure.
    """
    if not source_filepath or not os.path.exists(source_filepath):
        return None

    library_dir = get_library_dir()
    destination_path = os.path.join(library_dir, os.path.basename(source_filepath))

    try:
        shutil.copy(source_filepath, destination_path)
        log.warning(f"[AtlasWorkflow] Saved '{os.path.basename(source_filepath)}' to library.")
        return destination_path
    except Exception as e:
        log.warning(f"[AtlasWorkflow] Error saving workflow to library: {e}")
        return None


def delete_workflow_from_library(filename: str) -> bool:
    """
    Deletes a specified workflow JSON file from the library.

    Returns:
        True on success, False on failure.
    """
    if not filename or filename == '__PLACEHOLDER__':
        return False

    library_dir = get_library_dir()
    filepath = os.path.join(library_dir, filename)

    if not os.path.exists(filepath):
        log.warning(f"[AtlasWorkflow] Cannot delete: file not found at {filepath}")
        return False

    try:
        os.remove(filepath)
        log.warning(f"[AtlasWorkflow] Deleted '{filename}' from library.")
        return True
    except OSError as e:
        log.warning(f"[AtlasWorkflow] Error deleting workflow: {e}")
        return False


def rename_workflow_in_library(old_filename: str, new_name: str) -> str | None:
    """
    Renames a workflow file in the library.

    Args:
        old_filename: The current filename (e.g., "workflow.json").
        new_name: The desired new name, WITHOUT the extension (e.g., "new_workflow").

    Returns:
        The new filename on success, None on failure.
    """
    if not old_filename or not new_name or old_filename == '__PLACEHOLDER__':
        return None

    library_dir = get_library_dir()
    new_filename = f"{new_name}.json"

    old_path = os.path.join(library_dir, old_filename)
    new_path = os.path.join(library_dir, new_filename)

    if not os.path.exists(old_path):
        log.warning(f"[AtlasWorkflow] Cannot rename: source file not found at {old_path}")

        return None
    if os.path.exists(new_path):
        log.warning(f"[AtlasWorkflow] Cannot rename: destination file already exists at {new_path}")

        return None

    try:
        os.rename(old_path, new_path)
        log.warning(f"[AtlasWorkflow] Renamed '{old_filename}' to '{new_filename}'.")

        return new_filename
    except OSError as e:
        log.warning(f"[AtlasWorkflow] Error renaming workflow: {e}")

        return None

# --- UI Callback Function ---

_saved_workflows = []

def get_saved_workflows_for_enum(self, context: bpy.types.Context) -> list:
    """
    Scans the library directory and returns a list of .json files.
    This function is designed to be used as the `items` callback for an EnumProperty.
    """
    global _saved_workflows
    library_dir = get_library_dir()

    try:
        # Find all .json files in the library
        json_files = [f for f in os.listdir(library_dir) if f.endswith(".json")]

        # Format for EnumProperty: (identifier, name, description)
        _saved_workflows = [(f, os.path.splitext(f)[0], f) for f in sorted(json_files)]
    except Exception as e:
        log.warning(f"[AtlasWorkflow] Error scanning workflow library: {e}")
        _saved_workflows = []

    # Add a placeholder at the beginning
    return [('__PLACEHOLDER__', "Load from Library", "Select a saved workflow")] + _saved_workflows