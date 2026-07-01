# In __init__.py
"""
The main entry point for the Atlas Workflow Integration addon.

This file defines the addon's metadata (bl_info) and contains the top-level
register() and unregister() functions that Blender calls when the addon is
enabled or disabled.

It follows a modular structure by importing and calling the registration
functions from its submodules, rather than handling all class registrations
directly. This makes the addon easier to maintain and extend.
"""

bl_info = {
    "name": "Atlas Workflow Integration",
    "author": "Atlas",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "3D View > Sidebar (N-Panel) > Atlas",
    "category": "3D View",
    "description": "Integrates the Atlas platform's generative workflows directly into Blender's UI.",
    "doc_url": "",  # Optional: Add a link to your documentation
}

# --- Submodule Imports ---
# Instead of importing every class, we import the registration functions
# from each module. This keeps the __init__.py file clean.

from .atlas import preferences
from .atlas import atlas_workflow_state
from .atlas import custom_icons
from .atlas import operators
from .atlas import ui_panel

import logging
log = logging.getLogger("atlas_workflow")


def register():
    """
    Registers all parts of the addon with Blender.

    This function is called when the addon is enabled. It calls the register()
    function from each of the addon's modules in the correct order.

    The registration order is important:
    1. Preferences (must be first for bl_idname to match package)
    2. State (Property Groups)
    3. Operators (Actions that may depend on the state)
    4. UI (Panels that display the state and use the operators)
    """
    preferences.register()
    atlas_workflow_state.register()
    custom_icons.register()
    operators.register()
    ui_panel.register()


def unregister():
    """
    Unregisters all parts of the addon from Blender.

    This function is called when the addon is disabled. It unregisters all
    modules in the reverse order of registration to ensure a clean shutdown.
    """
    ui_panel.unregister()
    operators.unregister()
    custom_icons.unregister()
    atlas_workflow_state.unregister()
    preferences.unregister()


# This allows the script to be run directly from Blender's text editor
# to test the registration process.
if __name__ == "__main__":
    register()