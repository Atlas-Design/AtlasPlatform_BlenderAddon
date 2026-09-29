"""Run with blender --background --factory-startup --python this_file.py.

Uses real Blender data and exporters, with a fake Atlas transport. All files and
job history live in an isolated temporary directory; no API requests are made.
"""
import importlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import bpy

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
ops = addon.operators
state_module = addon.atlas_workflow_state
jobs = ops.job_manager

# Exercise the real operator methods without requiring an interactive window.
Runner = type('Runner', (), {
    name: value for name, value in ops.ATLAS_OT_RunWorkflow.__dict__.items()
    if not name.startswith('__') and not name.startswith('bl_')
})
Runner.report = lambda self, level, message: None


class FakeClient:
    def __init__(self, text, png):
        self.text = text
        self.png = png
        self.upload_started = threading.Event()
        self.allow_upload = threading.Event()
        self.uploaded_bytes = None

    def upload_file(self, api_id, path):
        self.upload_started.set()
        if not self.allow_upload.wait(10):
            raise RuntimeError('Test upload was not released')
        self.uploaded_bytes = Path(path).read_bytes()
        return 'input-file'

    def execute_async(self, api_id, payload):
        return 'execution-' + api_id

    def poll_status(self, execution_id):
        return ops.api_client.StatusResult(
            ops.ExecutionStatus.COMPLETED,
            outputs={'text': self.text, 'image': 'result-file'},
        )

    def download_file(self, api_id, file_id, path):
        Path(path).write_bytes(self.png)
        return path


class BlenderRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='atlas_regression_')
        cls.root = Path(cls.directory.name).resolve()
        (cls.root / 'library').mkdir()
        (cls.root / 'jobs').mkdir()
        cls.patches = [
            patch.object(ops.tempfile, 'gettempdir', return_value=str(cls.root)),
            patch.object(ops.workflow_manager, 'get_library_dir', return_value=str(cls.root / 'library')),
            patch.object(jobs, 'get_jobs_root_dir', return_value=str(cls.root / 'jobs')),
            patch.object(ops.preferences, 'get_poll_interval', return_value=0.001),
            patch.object(ops.preferences, 'get_workspace_api_key', return_value='test-only'),
            patch.object(ops.preferences, 'check_storage_limit', return_value=False),
            patch.object(ops.preferences, 'should_auto_import_meshes', return_value=False),
            patch.object(ops.preferences, 'should_auto_apply_images', return_value=False),
        ]
        for p in cls.patches:
            p.start()
        addon.register()
        # Establish a blend-relative base without touching the user's session.
        bpy.context.preferences.filepaths.save_version = 0
        bpy.context.preferences.filepaths.file_preview_type = 'NONE'
        bpy.ops.wm.save_as_mainfile(filepath=str(cls.root / 'test.blend'))

    @classmethod
    def tearDownClass(cls):
        addon.unregister()
        for p in reversed(cls.patches):
            p.stop()
        assert cls.root.parent == Path(tempfile.gettempdir()).resolve()
        assert cls.root.name.startswith('atlas_regression_')
        cls.directory.cleanup()

    def setUp(self):
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        self.state = bpy.context.window_manager.atlas_workflow_state
        state_module.clear_workflow_state(self.state)
        self.runner = Runner()
        self.runner._temp_dir = ops.create_job_temp_dir()
        self.addCleanup(ops.release_job_temp_dir, self.runner._temp_dir)

    def image(self):
        image = bpy.data.images.new('RegressionImage', width=2, height=2, alpha=True)
        image.pixels[:] = [0.2, 0.4, 0.6, 0.75] * 4
        return image

    def context(self):
        return SimpleNamespace(
            window_manager=SimpleNamespace(
                atlas_workflow_state=self.state,
                event_timer_add=Mock(return_value=object()),
                event_timer_remove=Mock(), modal_handler_add=Mock(),
            ),
            window=bpy.context.window, scene=bpy.context.scene,
            view_layer=bpy.context.view_layer, active_object=bpy.context.active_object,
            screen=bpy.context.screen,
        )

    def workflow(self, api_id):
        definition = ops.WorkflowDefinition.from_dict({
            'version': '0.2', 'api_id': api_id, 'base_url': 'example.invalid',
            'name': api_id, 'inputs': [{'id': 'input', 'type': 'image'}],
            'outputs': [{'id': 'text', 'type': 'string'}, {'id': 'image', 'type': 'image'}],
        })
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        self.state.inputs[0].image_name = self.image().name

    def test_concurrent_completion_survives_workflow_switch_and_cache_clear(self):
        png = self.root / 'fixture.png'
        ops._save_image_as_png(self.image(), str(png))
        clients = [FakeClient('A result', png.read_bytes()), FakeClient('B result', png.read_bytes())]
        runners = [Runner(), Runner()]
        context = self.context()
        try:
            with patch.object(ops, 'AtlasAPIClient', side_effect=clients):
                for index, name in enumerate(('A', 'B')):
                    self.workflow(name)
                    self.assertEqual(runners[index].execute(context), {'RUNNING_MODAL'})
                    self.assertTrue(clients[index].upload_started.wait(5))
            ops.cleanup_old_temp_dirs()
            for runner in runners:
                self.assertTrue((Path(runner._temp_dir) / 'input.png').is_file())
            # Complete B first, then A while B is still selected (same output IDs).
            for index in (1, 0):
                clients[index].allow_upload.set()
                runners[index]._thread.join(5)
                self.assertFalse(runners[index]._thread.is_alive())
                self.assertIsNone(runners[index]._error)
                self.assertEqual(runners[index].modal(context, SimpleNamespace(type='TIMER')), {'FINISHED'})
                saved = jobs.get_job(runners[index]._job.JobFolderPath)
                outputs = {p['ParamId']: p for p in saved.OutputsSnapshot}
                self.assertEqual(outputs['text']['StringValue'], clients[index].text)
                self.assertEqual(Path(outputs['image']['FilePath']).read_bytes(), png.read_bytes())
                self.assertFalse(Path(runners[index]._temp_dir).exists())
                self.assertEqual(self.state.outputs[0].string_value, 'B result')
            self.assertFalse(self.state.job_running)
            self.assertTrue(Path(self.state.outputs[1].temp_file_path).is_file())
        finally:
            for client in clients:
                client.allow_upload.set()
            for runner in runners:
                if runner._thread:
                    runner._thread.join(12)
                if runner._temp_dir:
                    ops.release_job_temp_dir(runner._temp_dir)

    def test_outputs_persist_after_selection_is_cleared(self):
        self.workflow('A')
        self.runner._workflow_key = self.runner._get_workflow_key(self.state)
        self.runner._output_params = [ops.WorkflowOutputResult('text', 'Text', 'string')]
        self.runner._outputs_result = {'text': 'A result'}
        state_module.clear_workflow_state(self.state)
        self.runner._update_primitive_outputs()
        snapshot = self.runner._create_outputs_snapshot()
        self.runner._publish_outputs(self.state)
        self.assertEqual(snapshot[0].StringValue, 'A result')
        self.assertEqual(len(self.state.outputs), 0)

    def test_cache_cleanup_preserves_other_process_and_active_job(self):
        foreign = self.root / 'atlas_workflow_other_process'
        foreign.mkdir(exist_ok=True)
        marker = foreign / 'input.png'
        marker.write_bytes(b'active elsewhere')
        ops.cleanup_old_temp_dirs()
        self.assertTrue(marker.exists())
        self.assertTrue(Path(self.runner._temp_dir).exists())

    def mesh_objects(self):
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.object
        cube.name = 'SelectedCube'
        bpy.ops.mesh.primitive_uv_sphere_add()
        sphere = bpy.context.object
        sphere.name = 'RequestedSphere'
        sphere.select_set(False)
        cube.select_set(True)
        bpy.context.view_layer.objects.active = cube
        item = SimpleNamespace(source_type='SCENE', param_type='mesh', mesh_name=sphere.name,
                               label='Mesh', param_id='mesh')
        return cube, sphere, item

    def test_mesh_export_uses_input_object_and_restores_selection(self):
        cube, sphere, item = self.mesh_objects()
        path = self.runner._prepare_datablock_for_upload(bpy.context, item)
        raw = Path(path).read_bytes()
        length = struct.unpack_from('<I', raw, 12)[0]
        gltf = json.loads(raw[20:20 + length])
        self.assertEqual([n['name'] for n in gltf['nodes']], [sphere.name])
        self.assertEqual(list(bpy.context.selected_objects), [cube])
        self.assertEqual(bpy.context.view_layer.objects.active, cube)

    def test_mesh_export_restores_mode_and_selection_on_failure(self):
        cube, sphere, item = self.mesh_objects()
        sphere.hide_set(True)
        sphere.hide_select = True
        bpy.ops.object.mode_set(mode='EDIT')
        failing_export = SimpleNamespace(ops=SimpleNamespace(
            object=bpy.ops.object,
            export_scene=SimpleNamespace(gltf=Mock(side_effect=RuntimeError('export failed'))),
        ))
        with patch.object(ops, 'bpy', failing_export):
            with self.assertRaisesRegex(RuntimeError, 'export failed'):
                self.runner._prepare_datablock_for_upload(bpy.context, item)
        self.assertEqual(bpy.context.view_layer.objects.active, cube)
        self.assertEqual(cube.mode, 'EDIT')
        self.assertTrue(cube.select_get())
        self.assertFalse(sphere.select_get())
        self.assertTrue(sphere.hide_get())
        self.assertTrue(sphere.hide_select)

    def test_cancelled_job_keeps_upload_until_worker_finishes(self):
        self.workflow('cancelled')
        client = FakeClient('unused result', b'fake-download')
        runner = Runner()
        context = self.context()
        try:
            with patch.object(ops, 'AtlasAPIClient', return_value=client):
                self.assertEqual(runner.execute(context), {'RUNNING_MODAL'})
            self.assertTrue(client.upload_started.wait(5))
            runner.cancel(context)
            ops.cleanup_old_temp_dirs()
            self.assertTrue((Path(runner._temp_dir) / 'input.png').exists())
        finally:
            client.allow_upload.set()
            if runner._thread:
                runner._thread.join(12)
        self.assertFalse(runner._thread.is_alive())
        self.assertIsNone(runner._error)
        self.assertFalse(Path(runner._temp_dir).exists())

    def test_failed_job_releases_only_its_own_files(self):
        self.workflow('failed')
        runner = Runner()
        client = Mock()
        client.upload_file.side_effect = RuntimeError('upload failed')
        context = self.context()
        with patch.object(ops, 'AtlasAPIClient', return_value=client):
            self.assertEqual(runner.execute(context), {'RUNNING_MODAL'})
        runner._thread.join(5)
        self.assertEqual(runner.modal(context, SimpleNamespace(type='TIMER')), {'CANCELLED'})
        self.assertFalse(Path(runner._temp_dir).exists())
        self.assertTrue(Path(self.runner._temp_dir).exists())
        self.assertEqual(jobs.get_job(runner._job.JobFolderPath).Status, jobs.JobStatus.FAILED)

    def test_scene_image_is_png_and_preserves_pixels_and_settings(self):
        image = self.image()
        settings = bpy.context.scene.render.image_settings
        settings.file_format = 'JPEG'
        bpy.context.scene.view_settings.view_transform = 'AgX'
        original = (image.filepath_raw, image.file_format, list(image.pixels))
        image_count = len(bpy.data.images)
        item = SimpleNamespace(source_type='SCENE', param_type='image', image_name=image.name,
                               label='Image', param_id='image')
        path = self.runner._prepare_datablock_for_upload(bpy.context, item)
        self.assertEqual(Path(path).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(len(bpy.data.images), image_count)
        self.assertEqual((image.filepath_raw, image.file_format, list(image.pixels)), original)
        self.assertEqual(settings.file_format, 'JPEG')
        self.assertEqual(bpy.context.scene.view_settings.view_transform, 'AgX')
        loaded = bpy.data.images.load(path)
        for actual, expected in zip(loaded.pixels, original[2]):
            self.assertAlmostEqual(actual, expected, delta=1 / 255)

    def test_relative_file_input_is_resolved_in_upload_and_snapshot(self):
        (self.root / 'relative.png').write_bytes(b'fixture')
        item = SimpleNamespace(source_type='FILE', param_type='image', file_path='//relative.png',
                               label='Image', param_id='image', image_name='')
        path = self.runner._prepare_datablock_for_upload(bpy.context, item)
        self.assertEqual(Path(path).resolve(), self.root / 'relative.png')
        snapshot = self.runner._create_inputs_snapshot(SimpleNamespace(inputs=[item]))
        self.assertEqual(Path(snapshot[0].FilePath).resolve(), self.root / 'relative.png')

    def test_both_image_apply_operators_replace_material_used_by_faces(self):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        old = bpy.data.materials.new('Original')
        obj.data.materials.append(old)
        image = self.image()
        path = str(self.root / 'apply.png')
        ops._save_image_as_png(image, path)
        for invoke in (
            lambda: bpy.ops.atlas.apply_output_image(image_name=image.name),
            lambda: bpy.ops.atlas.apply_job_output_image(file_path=path),
        ):
            previous = obj.active_material
            self.assertEqual(invoke(), {'FINISHED'})
            self.assertEqual(len(obj.material_slots), 1)
            self.assertNotEqual(obj.active_material, previous)
            self.assertTrue(all(obj.material_slots[p.material_index].material == obj.active_material
                                for p in obj.data.polygons))

    def test_library_selection_registers_one_shot_timer(self):
        path = self.root / 'library' / 'demo.json'
        path.write_text(json.dumps(dict(version='0.2', api_id='demo', base_url='example.invalid',
                                       name='Demo', inputs=[], outputs=[])), encoding='utf-8')
        self.state.saved_workflows_enum = 'demo.json'
        self.assertEqual(self.state.active_name, 'Demo')
        self.assertTrue(bpy.app.timers.is_registered(state_module._reset_library_selection))
        self.assertIsNone(state_module._reset_library_selection())
        self.assertEqual(self.state.saved_workflows_enum, '__NONE__')
        bpy.app.timers.unregister(state_module._reset_library_selection)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlenderRegressions)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
