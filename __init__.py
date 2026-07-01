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

import logging
import importlib
import os
import sys

# --- Submodule Imports ---
# Instead of importing every class, we import the registration functions
# from each module. This keeps the __init__.py file clean.

_MODULE_NAMES = (
    "preferences",
    "atlas_workflow_state",
    "custom_icons",
    "operators",
    "ui_panel",
)


def _import_modules_from(prefix):
    """Import addon modules from a package prefix or from the top level."""
    modules = []
    for module_name in _MODULE_NAMES:
        qualified_name = f"{prefix}.{module_name}" if prefix else module_name
        modules.append(importlib.import_module(qualified_name))
    return modules


def _is_missing_candidate_module(exc, prefix):
    """Return true when an import attempt failed because this layout is absent."""
    if not isinstance(exc, ModuleNotFoundError):
        return False
    candidate_names = {f"{prefix}.{name}" if prefix else name for name in _MODULE_NAMES}
    if prefix:
        candidate_names.add(prefix)
    return exc.name in candidate_names


def _import_addon_modules():
    """Import addon modules from flat release layout or source atlas layout."""
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)

    prefixes = []
    if __package__:
        prefixes.extend((__package__, f"{__package__}.atlas"))
    prefixes.extend(("", "atlas"))

    last_error = None
    for prefix in prefixes:
        try:
            return _import_modules_from(prefix)
        except ModuleNotFoundError as exc:
            if not _is_missing_candidate_module(exc, prefix):
                raise
            last_error = exc
            continue
        except ImportError as exc:
            if "attempted relative import with no known parent package" not in str(exc):
                raise
            last_error = exc
            continue

    raise last_error or ImportError("Could not import Atlas addon modules.")


preferences, atlas_workflow_state, custom_icons, operators, ui_panel = _import_addon_modules()

log = logging.getLogger("atlas_workflow")
preferences.set_addon_package(__name__)


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