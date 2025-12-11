# In custom_icons.py
"""
Manages the loading and registration of custom icons from the /icons folder.

This module follows the standard Blender pattern for registering a collection
of custom icons, making them accessible throughout the addon's UI.
"""

import bpy
import bpy.utils.previews
import os
import logging
log = logging.getLogger("atlas_workflow")

# This global dictionary will hold our icon collection.
preview_collections = {}


def get_icon_id(param_type: str) -> int:
    """
    A helper function to easily get the icon ID for a given parameter type.

    Args:
        param_type: The string identifier of the parameter type (e.g., 'number').

    Returns:
        The integer icon_id that can be used by the UI.
    """
    pcoll = preview_collections.get("main")
    if not pcoll:
        return 0  # Return 0 (no icon) if the collection isn't loaded

    # Return the specific icon if it exists, otherwise the 'default' icon
    icon = pcoll.get(param_type) or pcoll.get("default")
    if icon:
        return icon.icon_id

    return 0


# --- Blender Registration Functions ---

def register():
    """
    Registers the custom icons for the addon.
    """
    # Create a new preview collection (an object that can hold icons)
    pcoll = bpy.utils.previews.new()

    # The path to our /icons folder, calculated relative to this file
    icon_dir = os.path.join(os.path.dirname(__file__), "icons")

    # This dictionary maps a unique ID (our param_type) to a filename.
    # To add a new icon, just add a line here and place the file in /icons.
    icons_to_load = {
        "boolean": "Icon_Bool.png",
        "number": "Icon_Number.png",
        "string": "Icon_String.png",
        "image": "Icon_Image.png",
        "mesh": "Icon_Mesh.png",
        "default": "default.png",  # A fallback icon
    }

    # Loop through the dictionary and load each icon file.
    for key, filename in icons_to_load.items():
        filepath = os.path.join(icon_dir, filename)
        if os.path.exists(filepath):
            pcoll.load(key, filepath, 'IMAGE')
        else:
            log.warning(f"Warning: Custom icon file not found at {filepath}")

    # Store the fully loaded collection in our global dictionary
    # so other parts of the addon can access it.
    preview_collections["main"] = pcoll


def unregister():
    """
    Unregisters the custom icons, freeing the memory.
    """
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()