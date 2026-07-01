# In preferences.py
"""
Atlas Addon Preferences

This module defines the addon preferences accessible through Blender's
Edit > Preferences > Add-ons > Atlas Workflow Integration.

Settings include:
- API configuration (timeout, poll interval)
- Output settings (save paths)
- Storage management (limits, cleanup)
- Notification settings
- Logging verbosity
"""

import bpy
from bpy.types import AddonPreferences, Operator
from bpy.props import (
    BoolProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
    EnumProperty,
)
import os
import logging

try:
    from . import job_manager
except ImportError:
    import job_manager

log = logging.getLogger("atlas_workflow")
ADDON_PACKAGE = __package__.split(".")[0] if __package__ else __name__


def set_addon_package(package_name: str) -> None:
    """Set the Blender addon module id used for preferences lookup."""
    global ADDON_PACKAGE
    if package_name:
        ADDON_PACKAGE = package_name
        AtlasAddonPreferences.bl_idname = package_name


# ---------------------------------------------------------------------------
# Addon Preferences Class
# ---------------------------------------------------------------------------

class AtlasAddonPreferences(AddonPreferences):
    """
    Atlas Workflow Integration addon preferences.
    
    Access via: bpy.context.preferences.addons['Platform_BlenderAddon'].preferences
    Or use get_preferences() helper function.
    """
    bl_idname = ADDON_PACKAGE  # Must match the addon folder name

    # --- API Settings ---
    workspace_api_key: StringProperty(
        name="Workspace API Key",
        description="Atlas workspace API key for platform API v0.2+. Falls back to API_KEY environment variable when empty",
        default="",
        subtype='PASSWORD',
    )

    request_timeout: IntProperty(
        name="Request Timeout",
        description="Maximum time to wait for API requests (seconds). Set to 0 for no timeout",
        default=300,
        min=0,
        max=3600,
        soft_max=600,
        subtype='TIME_ABSOLUTE',
    )
    
    no_timeout_limit: BoolProperty(
        name="Disable Timeout",
        description="WARNING: Disable timeout entirely. Requests may hang indefinitely",
        default=False,
    )
    
    poll_interval: FloatProperty(
        name="Poll Interval",
        description="How often to check job status (seconds)",
        default=2.0,
        min=0.5,
        max=30.0,
        soft_max=10.0,
        precision=1,
        subtype='TIME_ABSOLUTE',
    )

    # --- Output Settings ---
    default_output_path: StringProperty(
        name="Default Output Path",
        description="Default directory for saving output files. Leave empty to use job folders",
        default="",
        subtype='DIR_PATH',
    )
    
    auto_import_meshes: BoolProperty(
        name="Auto-Import Meshes",
        description="Automatically import mesh outputs into the scene",
        default=False,
    )
    
    auto_apply_images: BoolProperty(
        name="Auto-Apply Images",
        description="Automatically apply image outputs to the active object's material",
        default=False,
    )

    # --- Storage Settings ---
    max_storage_mb: IntProperty(
        name="Max Storage (MB)",
        description="Maximum storage for job history. Set to 0 for unlimited",
        default=500,
        min=0,
        max=10000,
        soft_max=2000,
    )
    
    warn_on_storage_limit: BoolProperty(
        name="Warn on Limit",
        description="Show a warning when storage limit is exceeded",
        default=True,
    )
    
    auto_cleanup_days: IntProperty(
        name="Auto-Cleanup (Days)",
        description="Automatically delete jobs older than this. Set to 0 to disable",
        default=0,
        min=0,
        max=365,
        soft_max=90,
    )

    # --- Notification Settings ---
    notify_on_complete: BoolProperty(
        name="Notify on Complete",
        description="Show a Blender notification when a job completes",
        default=True,
    )
    
    notify_on_error: BoolProperty(
        name="Notify on Error",
        description="Show a Blender notification when a job fails",
        default=True,
    )

    # --- Debug Settings ---
    verbose_logging: BoolProperty(
        name="Verbose Logging",
        description="Enable detailed logging to Blender's console for debugging",
        default=False,
    )

    def draw(self, context):
        """Draw the preferences UI"""
        layout = self.layout
        
        # --- API Settings ---
        box = layout.box()
        box.label(text="API Settings", icon='URL')
        
        col = box.column(align=True)
        col.prop(self, "workspace_api_key")
        if not get_workspace_api_key(context):
            col.label(text="API v0.2+ requires a workspace API key or API_KEY env var.", icon='INFO')

        row = col.row()
        row.prop(self, "request_timeout")
        row.prop(self, "no_timeout_limit", text="No Limit", toggle=True)
        
        if self.no_timeout_limit:
            col.label(text="⚠ Warning: Requests may hang indefinitely!", icon='ERROR')
        
        col.prop(self, "poll_interval")
        
        # --- Output Settings ---
        box = layout.box()
        box.label(text="Output Settings", icon='EXPORT')
        
        col = box.column(align=True)
        col.prop(self, "default_output_path")
        col.prop(self, "auto_import_meshes")
        col.prop(self, "auto_apply_images")
        
        # --- Storage Settings ---
        box = layout.box()
        box.label(text="Storage Management", icon='DISK_DRIVE')
        
        col = box.column(align=True)
        row = col.row()
        row.prop(self, "max_storage_mb")
        row.prop(self, "warn_on_storage_limit", text="Warn", toggle=True)
        
        col.prop(self, "auto_cleanup_days")
        
        # Storage info
        file_count, total_bytes = job_manager.get_jobs_storage_size()
        total_mb = total_bytes / (1024 * 1024)
        storage_text = f"Current Usage: {total_mb:.1f} MB ({file_count} files)"
        
        row = col.row()
        row.label(text=storage_text)
        
        if self.max_storage_mb > 0 and total_mb > self.max_storage_mb:
            row.label(text="⚠ Over limit!", icon='ERROR')
        
        # Storage actions
        row = col.row(align=True)
        row.operator("atlas.cleanup_old_jobs", text="Clean Old Jobs", icon='TRASH')
        row.operator("atlas.clear_all_jobs", text="Clear All", icon='X')
        
        # Temp cache cleanup
        col.separator()
        col.operator("atlas.clear_cache", text="Clear Temp Cache", icon='FILE_REFRESH')
        
        # --- Notification Settings ---
        box = layout.box()
        box.label(text="Notifications", icon='INFO')
        
        row = box.row()
        row.prop(self, "notify_on_complete")
        row.prop(self, "notify_on_error")
        
        # --- Debug Settings ---
        box = layout.box()
        box.label(text="Developer Options", icon='CONSOLE')
        
        col = box.column(align=True)
        col.prop(self, "verbose_logging")
        
        if self.verbose_logging:
            col.label(text="Verbose logs written to Blender console", icon='INFO')


# ---------------------------------------------------------------------------
# Storage Management Operators
# ---------------------------------------------------------------------------

class ATLAS_OT_CleanupOldJobs(Operator):
    """Clean up old job folders based on age"""
    bl_idname = "atlas.cleanup_old_jobs"
    bl_label = "Cleanup Old Jobs"
    bl_options = {'REGISTER'}
    
    days: IntProperty(
        name="Max Age (Days)",
        description="Delete jobs older than this many days",
        default=30,
        min=1,
        max=365,
    )
    
    def invoke(self, context, event):
        prefs = get_preferences(context)
        if prefs and prefs.auto_cleanup_days > 0:
            self.days = prefs.auto_cleanup_days
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "days")
        
        # Show preview of what will be deleted
        from datetime import datetime, timezone
        cutoff = datetime.now(timezone.utc).timestamp() - (self.days * 24 * 60 * 60)
        jobs = job_manager.get_all_jobs()
        old_jobs = []
        
        for job in jobs:
            try:
                created = datetime.fromisoformat(job.CreatedAtUtc.replace('Z', '+00:00'))
                if created.timestamp() < cutoff:
                    old_jobs.append(job)
            except:
                pass
        
        if old_jobs:
            layout.label(text=f"Will delete {len(old_jobs)} job(s)", icon='ERROR')
        else:
            layout.label(text="No jobs to delete", icon='INFO')
    
    def execute(self, context):
        deleted_count = job_manager.cleanup_old_jobs(self.days)
        
        if deleted_count > 0:
            self.report({'INFO'}, f"Deleted {deleted_count} old job(s)")
            # Refresh job history if it exists
            try:
                bpy.ops.atlas.refresh_job_history()
            except:
                pass
        else:
            self.report({'INFO'}, "No old jobs to clean up")
        
        return {'FINISHED'}


class ATLAS_OT_ClearAllJobs(Operator):
    """Delete ALL job history - this cannot be undone!"""
    bl_idname = "atlas.clear_all_jobs"
    bl_label = "Clear All Job History"
    bl_options = {'REGISTER'}
    
    confirm: BoolProperty(
        name="I understand this cannot be undone",
        default=False,
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        
        # Warning
        layout.label(text="⚠ WARNING: This will delete ALL job history!", icon='ERROR')
        layout.label(text="All job records and output files will be permanently removed.")
        layout.separator()
        
        # Show what will be deleted
        jobs = job_manager.get_all_jobs()
        file_count, total_bytes = job_manager.get_jobs_storage_size()
        total_mb = total_bytes / (1024 * 1024)
        
        layout.label(text=f"Jobs to delete: {len(jobs)}")
        layout.label(text=f"Space to free: {total_mb:.1f} MB ({file_count} files)")
        layout.separator()
        
        layout.prop(self, "confirm")
    
    def execute(self, context):
        if not self.confirm:
            self.report({'WARNING'}, "Please confirm to proceed")
            return {'CANCELLED'}
        
        # Delete all jobs
        jobs = job_manager.get_all_jobs()
        deleted_count = 0
        
        for job in jobs:
            if job_manager.delete_job(job):
                deleted_count += 1
        
        self.report({'INFO'}, f"Deleted {deleted_count} job(s)")
        
        # Refresh job history
        try:
            bpy.ops.atlas.refresh_job_history()
        except:
            pass
        
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def get_preferences(context=None) -> AtlasAddonPreferences:
    """
    Get the addon preferences instance.
    
    Args:
        context: Optional Blender context (uses bpy.context if not provided)
        
    Returns:
        AtlasAddonPreferences instance or None if not found
    """
    if context is None:
        context = bpy.context
    
    try:
        return context.preferences.addons[ADDON_PACKAGE].preferences
    except (KeyError, AttributeError):
        return None


def get_effective_timeout(context=None) -> float:
    """
    Get the effective request timeout from preferences.
    
    Returns:
        Timeout in seconds, or None if no timeout
    """
    prefs = get_preferences(context)
    
    if prefs is None:
        return 300.0  # Default
    
    if prefs.no_timeout_limit:
        return None  # No timeout
    
    if prefs.request_timeout == 0:
        return None  # No timeout
    
    return float(prefs.request_timeout)


def get_poll_interval(context=None) -> float:
    """
    Get the poll interval from preferences.
    
    Returns:
        Poll interval in seconds
    """
    prefs = get_preferences(context)
    
    if prefs is None:
        return 2.0  # Default
    
    return prefs.poll_interval


def get_workspace_api_key(context=None) -> str:
    """Get the workspace API key from preferences or the API_KEY environment variable."""
    prefs = get_preferences(context)
    if prefs and prefs.workspace_api_key.strip():
        return prefs.workspace_api_key.strip()

    return os.environ.get("API_KEY", "").strip()


def check_storage_limit(context=None) -> bool:
    """
    Check if storage limit is exceeded.
    
    Returns:
        True if over limit (or should warn), False otherwise
    """
    prefs = get_preferences(context)
    
    if prefs is None or prefs.max_storage_mb == 0:
        return False  # No limit
    
    file_count, total_bytes = job_manager.get_jobs_storage_size()
    total_mb = total_bytes / (1024 * 1024)
    
    return total_mb > prefs.max_storage_mb


def should_auto_import_meshes(context=None) -> bool:
    """Check if meshes should be auto-imported"""
    prefs = get_preferences(context)
    return prefs.auto_import_meshes if prefs else False


def should_auto_apply_images(context=None) -> bool:
    """Check if images should be auto-applied"""
    prefs = get_preferences(context)
    return prefs.auto_apply_images if prefs else False


def should_notify(context=None, on_error=False) -> bool:
    """Check if notifications should be shown"""
    prefs = get_preferences(context)
    if prefs is None:
        return True
    
    if on_error:
        return prefs.notify_on_error
    return prefs.notify_on_complete


def is_verbose_logging(context=None) -> bool:
    """Check if verbose logging is enabled"""
    prefs = get_preferences(context)
    return prefs.verbose_logging if prefs else False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    AtlasAddonPreferences,
    ATLAS_OT_CleanupOldJobs,
    ATLAS_OT_ClearAllJobs,
)


def register():
    """Register preference classes"""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    log.info("[Atlas Preferences] Registered addon preferences")


def unregister():
    """Unregister preference classes"""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
