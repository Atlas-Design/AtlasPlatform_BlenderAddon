"""Native UI draw/screenshot smoke test in an isolated factory-startup GUI process.

blender --factory-startup --python tests/blender_ui_smoke.py -- --output <directory>
No network, user preferences or production history are used. The process exits.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import bpy
bpy.context.preferences.view.show_splash = False

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
parser.add_argument('--dialog', choices=('preview', 'stop', 'delete'), default='preview')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
addon = importlib.import_module(root.name)
ops, ui = addon.operators, addon.ui_panel
jobs = ops.job_manager
(output / 'jobs').mkdir(exist_ok=True)
(output / 'library').mkdir(exist_ok=True)
patches = [patch.object(jobs, 'get_jobs_root_dir', return_value=str(output / 'jobs')),
           patch.object(ops.workflow_manager, 'get_library_dir', return_value=str(output / 'library'))]
for item in patches:
    item.start()
errors = []
original_draw = ui.ATLAS_PT_MainControlPanel.draw
def checked_draw(self, context):
    try:
        original_draw(self, context)
    except Exception as exc:
        errors.append(repr(exc))
        raise
ui.ATLAS_PT_MainControlPanel.draw = checked_draw
# Blender 4.0 cannot select sidebar categories through RNA. In this disposable
# process, draw the same native panel in the already-selected Item category.
category_override = 'active_panel_category' not in bpy.types.Region.bl_rna.properties
if category_override:
    ui.ATLAS_PT_MainControlPanel.bl_category = 'Item'
    ui.ATLAS_PT_MainControlPanel.bl_order = -1
addon.register()
state = bpy.context.window_manager.atlas_workflow_state
definition = ops.WorkflowDefinition.from_dict(dict(version='0.2', api_id='ui-smoke',
    base_url='https://example.invalid', name='Material Generator', inputs=[
        dict(id='prompt', label='Prompt', type='string', default_value='Warm sandstone'),
        dict(id='references', label='Reference Images', type='image', isArray=True),
    ], outputs=[dict(id='textures', type='image', isArray=True)]))
addon.atlas_workflow_state.populate_state_from_definition(bpy.context, state, definition)
for fid in ('reference-a', 'reference-b'):
    entry = state.inputs[1].asset_items.add()
    entry.source_type, entry.asset_id = 'ASSET', fid
img = bpy.data.images.new('Smoke result', width=64, height=64)
img.pixels[:] = [value for y in range(64) for x in range(64)
                for value in (x / 64, y / 64, 0.3, 1)]
image_path = str(output / 'result.png')
ops._save_image_as_png(img, image_path)
job = jobs.create_job('ui-smoke', 'Material Generator', '0.2', [],
                      workflow_snapshot=definition.to_dict(),
                      input_draft=addon.atlas_workflow_state.capture_input_values(state))
job.UserLabel = 'Sandstone variation'
jobs.complete_job(job, [dict(ParamId='textures', Label='Textures', ParamType='image', IsArray=True,
                            Items=[dict(Index=0, FilePath=image_path)])])
pending = jobs.create_job('other', 'Mesh Generator', '0.2', [])
running = state.running_jobs.add()
running.job_id, running.workflow_name = pending.JobId, pending.WorkflowName
running.current_phase, running.status, running.elapsed_time = 'running', 'Workflow running', '18.2s'
running.run_number = pending.RunNumber
state.last_started_job_id = pending.JobId
bpy.ops.atlas.refresh_job_history()
view = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
view.spaces.active.show_region_ui = True
stages = iter(('run', 'jobs', 'running_detail', 'detail', args.dialog, 'done'))
stage = None
def tick():
    global stage
    try:
        region = next(region for region in view.regions if region.type == 'UI')
        if not category_override:
            region.active_panel_category = 'Atlas'
        if stage:
            bpy.ops.screen.screenshot(filepath=str(output / f'{stage}.png'))
        stage = next(stages)
        if stage == 'run':
            state.view_mode = 'RUN'
        elif stage == 'jobs':
            state.view_mode = 'JOBS'
            state.job_history_detail_mode = False
            state.job_history_index = next(i for i, j in enumerate(state.job_history) if j.job_id == job.JobId)
        elif stage == 'running_detail':
            bpy.ops.atlas.select_job(job_id=pending.JobId)
        elif stage == 'detail':
            bpy.ops.atlas.select_job(job_id=job.JobId)
        elif stage == 'preview':
            with bpy.context.temp_override(area=view, region=region):
                bpy.ops.atlas.view_job_output_image('INVOKE_DEFAULT', file_path=image_path)
        elif stage == 'stop':
            with bpy.context.temp_override(area=view, region=region):
                bpy.ops.atlas.stop_tracking('INVOKE_DEFAULT', job_id=pending.JobId)
        elif stage == 'delete':
            with bpy.context.temp_override(area=view, region=region):
                bpy.ops.atlas.delete_job('INVOKE_DEFAULT', job_id=job.JobId)
        else:
            (output / 'report.json').write_text(json.dumps(dict(draw_errors=errors,
                category_override=category_override)), encoding='utf-8')
            bpy.ops.wm.quit_blender()
            return None
        view.tag_redraw()
        return 1.0
    except Exception as exc:
        errors.append(repr(exc))
        (output / 'report.json').write_text(json.dumps(dict(draw_errors=errors)), encoding='utf-8')
        bpy.ops.wm.quit_blender()
        return None
bpy.app.timers.register(tick, first_interval=1.5)
