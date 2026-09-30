"""Run with blender --background --factory-startup --python this_file.py.

Uses real Blender data and exporters, with a fake Atlas transport. All files and
job history live in an isolated temporary directory; no API requests are made.
"""
import importlib
import io
import logging
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
REAL_API_KEY = ops.preferences.get_workspace_api_key
REAL_POLL_INTERVAL = ops.preferences.get_poll_interval
REAL_STORAGE_CHECK = ops.preferences.check_storage_limit
REAL_AUTO_IMPORT = ops.preferences.should_auto_import_meshes
REAL_AUTO_APPLY = ops.preferences.should_auto_apply_images

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
        self.upload_path = path
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
        self.state.job_notices.clear()
        self.state.job_history_detail_mode = False
        self.state.job_history_index = -1
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
            with patch.object(ops, 'AtlasAPIClient', side_effect=clients), \
                 patch.object(ops.preferences, 'prepare_output_copy_root',
                              side_effect=[str(self.root / 'copies-A'), str(self.root / 'copies-B')]):
                for index, name in enumerate(('A', 'B')):
                    self.workflow(name)
                    self.assertEqual(runners[index].execute(context), {'RUNNING_MODAL'})
                    self.assertTrue(clients[index].upload_started.wait(5))
                    self.assertEqual(runners[index]._current_status, 'uploading')
            ops.cleanup_old_temp_dirs()
            for client in clients:
                self.assertTrue(Path(client.upload_path).is_file())
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
                self.assertEqual(Path(saved.OutputCopyFolder).parent.parent, self.root / f'copies-{saved.WorkflowName}')
                self.assertEqual((Path(saved.OutputCopyFolder) / Path(outputs['image']['FilePath']).name).read_bytes(),
                                 png.read_bytes())
                self.assertFalse(Path(runners[index]._temp_dir).exists())
                self.assertEqual(self.state.outputs[0].string_value, 'B result')
                if index == 1:
                    bpy.ops.atlas.select_job(job_id=runners[1]._job.JobId)
            self.assertEqual(self.state.job_history[self.state.job_history_index].job_id,
                             runners[1]._job.JobId)
            self.assertEqual([n.job_id for n in self.state.job_notices],
                             [runners[1]._job.JobId, runners[0]._job.JobId])
            self.assertEqual(self.state.active_api_id, 'B')
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

    def test_history_navigation_uses_job_id_and_preserves_workflow(self):
        self.workflow('editing')
        input_name = self.state.inputs[0].image_name
        first = jobs.create_job('first', 'First run', '0.2', [])
        second = jobs.create_job('second', 'Second run', '0.2', [])
        self.state.filter_status = 'FAILED'
        self.state.filter_date = 'TODAY'
        # Force different list orders around navigation and refresh.
        with patch.object(jobs, 'get_all_jobs', return_value=[second, first]):
            self.assertEqual(bpy.ops.atlas.select_job(job_id=first.JobId), {'FINISHED'})
        self.assertEqual(self.state.job_history_index, 1)
        self.assertTrue(self.state.job_history_detail_mode)
        self.assertTrue(self.state.job_detail_outputs_expanded)
        self.assertEqual(self.state.filter_status, 'ALL')
        self.assertEqual(self.state.filter_date, 'ALL')
        self.assertEqual(self.state.filter_workflow, 'ALL')
        with patch.object(jobs, 'get_all_jobs', return_value=[first, second]):
            bpy.ops.atlas.refresh_job_history()
        self.assertEqual(self.state.job_history_index, 0)
        self.assertEqual(self.state.active_api_id, 'editing')
        self.assertEqual(self.state.inputs[0].image_name, input_name)
        with patch.object(jobs, 'get_all_jobs', return_value=[second]):
            self.assertEqual(bpy.ops.atlas.select_job(job_id=first.JobId), {'CANCELLED'})
        self.assertFalse(self.state.job_history_detail_mode)
        self.assertEqual(self.state.job_history_index, -1)

    def test_completion_notice_does_not_navigate_and_dismiss_keeps_results(self):
        self.runner._workflow_name = 'Notice run'
        self.runner._job = jobs.create_job('notice', 'Notice run', '0.2', [])
        self.runner._notify_completion(self.state, failed=True)
        self.assertFalse(self.state.job_history_detail_mode)
        self.assertTrue(self.state.job_notices[0].failed)
        bpy.ops.atlas.dismiss_job_notice(job_id=self.runner._job.JobId)
        self.assertEqual(len(self.state.job_notices), 0)
        self.assertIsNotNone(jobs.get_job(self.runner._job.JobFolderPath))

    def test_running_status_never_fabricates_percentage(self):
        self.runner._done = False
        self.runner._start_time = 100
        self.runner._running_job_id = 'status-test'
        job = self.state.running_jobs.add()
        job.job_id = 'status-test'
        try:
            for phase, elapsed in [('pending', 1), ('running', 13), ('downloading', 35)]:
                self.runner._current_status = phase
                self.runner._status_message = phase
                with patch.object(ops.time, 'time', return_value=100 + elapsed):
                    self.assertEqual(self.runner.modal(self.context(), SimpleNamespace(type='TIMER')),
                                     {'RUNNING_MODAL'})
                self.assertEqual(job.current_phase, phase)
                self.assertEqual(job.elapsed_time, f'{elapsed:.1f}s')
                self.assertEqual(job.progress, 0.0)
                self.assertEqual(self.state.job_progress, 0.0)
        finally:
            self.runner._remove_running_job(self.state)

    def test_worker_reports_submission_queue_and_download_phases(self):
        self.runner._output_params = [ops.WorkflowOutputResult('image', 'Image', 'image')]
        self.runner._api_origin = 'https://example.invalid'
        self.runner._poll_interval = 0
        phases = []
        client = Mock()
        def submit(*args):
            phases.append(self.runner._current_status)
            return 'execution'
        def poll(*args):
            phases.append(self.runner._current_status)
            return ops.api_client.StatusResult(ops.ExecutionStatus.COMPLETED, outputs={'image': 'asset'})
        def download(api_id, value, path):
            phases.append(self.runner._current_status)
            Path(path).write_bytes(b'fixture')
            return path
        client.execute_async.side_effect = submit
        client.poll_status.side_effect = poll
        client.download_file.side_effect = download
        self.runner._job_thread(client, 'api', {}, [], {})
        self.assertIsNone(self.runner._error)
        self.assertEqual(phases, ['submitting', 'pending', 'downloading'])

    def test_output_copy_path_resolution_and_validation(self):
        prefs = SimpleNamespace(default_output_path='')
        with patch.object(ops.preferences, 'get_preferences', return_value=prefs):
            self.assertEqual(ops.preferences.get_output_copy_root(), '')
            prefs.default_output_path = '//output-copies'
            with patch.object(ops.preferences, 'bpy', SimpleNamespace(data=SimpleNamespace(filepath=''))):
                with self.assertRaisesRegex(ValueError, 'Save the .blend'):
                    ops.preferences.get_output_copy_root()
            self.assertEqual(Path(ops.preferences.prepare_output_copy_root()), self.root / 'output-copies')
            prefs.default_output_path = str(self.root / 'jobs' / 'nested')
            with self.assertRaisesRegex(ValueError, 'outside Job History'):
                ops.preferences.get_output_copy_root()
            prefs.default_output_path = 'ambiguous-relative-path'
            with self.assertRaisesRegex(ValueError, 'absolute folder'):
                ops.preferences.get_output_copy_root()
            prefs.default_output_path = str(self.root / 'not-a-folder')
            Path(prefs.default_output_path).write_text('existing file')
            with self.assertRaises(OSError):
                ops.preferences.prepare_output_copy_root()

    def test_output_copy_failure_preserves_history_and_other_items(self):
        job = jobs.create_job('export', '..', '0.2', [], str(self.root / 'exported'))
        files = []
        for name in ('one.png', 'two.atlas-context.json'):
            path = Path(job.JobFolderPath) / 'outputs' / name
            path.write_bytes(b'original')
            files.append({'FilePath': str(path)})
        jobs.complete_job(job, [{'Items': files + [{'FilePath': '', 'Error': 'download failed'}]}])
        collision = Path(job.OutputCopyFolder) / 'one.png'
        collision.write_bytes(b'user file')
        with self.assertRaisesRegex(OSError, 'originals are safe'):
            jobs.export_output_copies(job)
        self.assertEqual(collision.read_bytes(), b'user file')
        self.assertEqual((Path(job.OutputCopyFolder) / 'two.atlas-context.json').read_bytes(), b'original')
        self.assertTrue(all(Path(item['FilePath']).is_file() for item in files))
        self.assertTrue(jobs.delete_job(job))
        self.assertTrue(collision.is_file())  # History cleanup never deletes exported copies.

    def test_interrupted_output_copy_removes_partial_copy(self):
        job = jobs.create_job('interrupted', 'Interrupted', '0.2', [], str(self.root / 'interrupted-export'))
        source = Path(job.JobFolderPath) / 'outputs' / 'image.png'
        source.write_bytes(b'original')
        jobs.complete_job(job, [{'FilePath': str(source)}])
        def interrupted(src, dst):
            dst.write(b'partial')
            raise OSError('disk full')
        with patch.object(jobs.shutil, 'copyfileobj', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'disk full'):
                jobs.export_output_copies(job)
        self.assertFalse((Path(job.OutputCopyFolder) / source.name).exists())
        self.assertEqual(source.read_bytes(), b'original')

    def test_notification_toggles_are_independent(self):
        prefs = SimpleNamespace(notify_on_complete=False, notify_on_error=True)
        self.runner._job = jobs.create_job('notice-toggle', 'Notice', '0.2', [])
        self.runner._workflow_name = 'Notice'
        with patch.object(ops.preferences, 'get_preferences', return_value=prefs):
            self.runner._notify_completion(self.state)
            self.assertEqual(len(self.state.job_notices), 0)
            self.runner._notify_completion(self.state, failed=True)
            self.assertEqual(len(self.state.job_notices), 1)
            self.state.job_notices.clear()
            prefs.notify_on_complete, prefs.notify_on_error = True, False
            self.runner._notify_completion(self.state, failed=True)
            self.assertEqual(len(self.state.job_notices), 0)
            self.runner._notify_completion(self.state)
            self.assertEqual(len(self.state.job_notices), 1)

    def test_verbose_logging_controls_only_atlas_and_does_not_duplicate_handlers(self):
        prefs = SimpleNamespace(verbose_logging=False)
        logger = logging.getLogger('atlas_workflow')
        root_level = logging.getLogger().level
        with patch.object(ops.preferences, 'get_preferences', return_value=prefs):
            ops.preferences.configure_logging()
            handler = ops.preferences._console_handler
            stream = io.StringIO()
            previous_stream = handler.stream
            handler.setStream(stream)
            try:
                logger.debug('hidden-debug')
                prefs.verbose_logging = True
                ops.preferences.configure_logging()
                ops.preferences.configure_logging()
                logger.debug('visible-debug')
                self.assertNotIn('hidden-debug', stream.getvalue())
                self.assertEqual(stream.getvalue().count('visible-debug'), 1)
                self.assertEqual(logger.handlers.count(handler), 1)
                self.assertEqual(logging.getLogger().level, root_level)
            finally:
                handler.setStream(previous_stream)
                prefs.verbose_logging = False
                ops.preferences.configure_logging()

    def test_cleanup_preserves_unfinished_jobs_and_rejects_outside_paths(self):
        pending = jobs.create_job('keep', 'Cleanup', '0.2', [])
        finished = jobs.create_job('remove', 'Cleanup', '0.2', [])
        for job in (pending, finished):
            job.CreatedAtUtc = '2000-01-01T00:00:00+00:00'
            job.save()
        jobs.complete_job(finished, [])
        with patch.object(jobs, 'get_all_jobs', return_value=[pending, finished]):
            self.assertEqual(jobs.cleanup_old_jobs(30), 1)
        self.assertTrue(Path(pending.JobFolderPath).is_dir())
        self.assertFalse(Path(finished.JobFolderPath).exists())
        outsider = self.root / 'outside-history'
        outsider.mkdir()
        (outsider / 'job.json').write_text('{}')
        pending.Status = jobs.JobStatus.COMPLETED
        pending.JobFolderPath = str(outsider)
        self.assertFalse(jobs.delete_job(pending))
        self.assertTrue(outsider.exists())

    def test_api_settings_and_storage_warning_helpers(self):
        prefs = SimpleNamespace(request_timeout=42, no_timeout_limit=False,
                                max_storage_mb=1, workspace_api_key=' key ', poll_interval=3,
                                auto_import_meshes=True, auto_apply_images=False)
        with patch.object(ops.preferences, 'get_preferences', return_value=prefs), \
             patch.object(jobs, 'get_jobs_storage_size', return_value=(1, 2 * 1024 * 1024)), \
             patch.dict(os.environ, {'API_KEY': 'environment-key'}):
            self.assertEqual(ops.preferences.get_effective_timeout(), 42)
            prefs.no_timeout_limit = True
            self.assertIsNone(ops.preferences.get_effective_timeout())
            prefs.no_timeout_limit, prefs.request_timeout = False, 0
            self.assertIsNone(ops.preferences.get_effective_timeout())
            self.assertEqual(REAL_API_KEY(), 'key')
            prefs.workspace_api_key = ''
            self.assertEqual(REAL_API_KEY(), 'environment-key')
            self.assertEqual(REAL_POLL_INTERVAL(), 3)
            self.assertTrue(REAL_STORAGE_CHECK())
            prefs.max_storage_mb = 0
            self.assertFalse(REAL_STORAGE_CHECK())
            self.assertTrue(REAL_AUTO_IMPORT())
            self.assertFalse(REAL_AUTO_APPLY())

    def test_copy_failure_is_saved_and_muted_error_does_not_notify(self):
        self.workflow('copy failure')
        png = self.root / 'copy-fixture.png'
        ops._save_image_as_png(self.image(), str(png))
        client = FakeClient('preserved result', png.read_bytes())
        client.allow_upload.set()
        self.runner.report = Mock()
        context = self.context()
        with patch.object(ops, 'AtlasAPIClient', return_value=client), \
             patch.object(ops.preferences, 'should_notify', return_value=False), \
             patch.object(jobs, 'export_output_copies', side_effect=OSError('copy destination unavailable')):
            self.assertEqual(self.runner.execute(context), {'RUNNING_MODAL'})
            self.runner._thread.join(5)
            self.assertFalse(self.runner._thread.is_alive())
            self.runner.report.reset_mock()
            self.assertEqual(self.runner.modal(context, SimpleNamespace(type='TIMER')), {'CANCELLED'})
            self.runner.report.assert_not_called()
        saved = jobs.get_job(self.runner._job.JobFolderPath)
        self.assertEqual(saved.Status, jobs.JobStatus.FAILED)
        self.assertIn('copy destination unavailable', saved.ErrorMessage)
        self.assertEqual(saved.OutputsSnapshot[0]['StringValue'], 'preserved result')
        self.assertEqual(Path(saved.OutputsSnapshot[1]['FilePath']).read_bytes(), png.read_bytes())
        self.assertEqual(len(self.state.job_notices), 0)

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
            self.assertTrue(Path(client.upload_path).exists())
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
                               label='Image', param_id='image', image_name='', mesh_name='')
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

    def test_all_types_state_keeps_array_format_and_unknown_requiredness(self):
        definition = ops.WorkflowDefinition.from_json_file(str(ROOT / 'examples/all-types-v02.example.json'))
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        self.assertEqual((len(self.state.inputs), len(self.state.outputs)), (15, 21))
        self.assertEqual(sum(p.is_array for p in self.state.inputs), 2)
        self.assertTrue(all(p.required == 'UNKNOWN' for p in self.state.inputs))
        context_output = next(p for p in self.state.outputs if p.param_type == 'agent_context')
        self.assertEqual(context_output.file_format, 'atlas-context.json')

    def test_array_payload_preserves_order_duplicates_and_primitive_values(self):
        definition = ops.WorkflowDefinition.from_dict(dict(version='0.2', api_id='array', base_url='https://example.invalid', name='Array',
            inputs=[dict(id='images', type='image', isArray=True, default_value=[]),
                    dict(id='flag', type='boolean', default_value=False),
                    dict(id='number', type='number', default_value=0),
                    dict(id='text', type='string', default_value=''),
                    dict(id='context', type='agent_context', required=False)], outputs=[]))
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        param = self.state.inputs[0]
        file_path = self.root / 'reference.png'
        file_path.write_bytes(b'file fixture')
        image = self.image()
        fid = '11111111-1111-4111-8111-111111111111'
        for source in ('ASSET', 'FILE', 'ASSET', 'SCENE'):
            entry = param.asset_items.add()
            entry.source_type, entry.asset_id = source, fid
            entry.file_path, entry.image_name = str(file_path), image.name
        self.state.inputs[4].provided = False
        payload, uploads = self.runner._build_payload(bpy.context, self.state)
        self.assertEqual(payload, dict(images=[fid, None, fid, None], flag=False, number=0, text=''))
        self.assertEqual([p['index'] for p in uploads], [1, 3])
        self.assertTrue(all(Path(p['path']).is_file() for p in uploads))
        param.asset_items.clear()
        param.required = 'REQUIRED'
        payload, uploads = self.runner._build_payload(bpy.context, self.state)
        self.assertEqual(payload['images'], [])  # Required means present, not nonempty.
        self.state.inputs[4].required = 'REQUIRED'
        with self.assertRaisesRegex(ValueError, 'required'):
            self.runner._build_payload(bpy.context, self.state)

    def test_list_edit_and_asset_reuse_operators(self):
        definition = ops.WorkflowDefinition.from_dict(dict(version='0.2', api_id='array', base_url='https://example.invalid', name='Array',
            inputs=[dict(id='images', type='image', isArray=True)], outputs=[]))
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        records = [dict(AssetId=f'asset-{i}', ApiOrigin=self.state.base_url) for i in range(2)]
        result = bpy.ops.atlas.reuse_asset(param_type='jpeg', asset_data=json.dumps(records), target_param='images')
        self.assertEqual(result, {'FINISHED'})
        items = self.state.inputs[0].asset_items
        self.assertEqual([i.asset_id for i in items], ['asset-0', 'asset-1'])
        bpy.ops.atlas.edit_asset_list(param_id='images', item_index=1, action='UP')
        self.assertEqual([i.asset_id for i in items], ['asset-1', 'asset-0'])
        bpy.ops.atlas.edit_asset_list(param_id='images', item_index=1, action='REMOVE')
        self.assertEqual(len(items), 1)

    def test_partial_array_download_keeps_files_ids_and_context(self):
        definition = ops.WorkflowDefinition.from_dict(dict(version='0.2', api_id='array', base_url='https://example.invalid', name='Array', inputs=[],
            outputs=[dict(id='images', type='image', isArray=True, format='png'),
                     dict(id='meshes', type='mesh', isArray=True, format='glb'),
                     dict(id='context', type='agent_context', format='atlas-context.json')]))
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        png = self.root / 'array.png'
        ops._save_image_as_png(self.image(), str(png))
        outputs = dict(images=['first', dict(fid='failed'), dict(fid='first', metadata=dict(mime='image/png'))],
                       meshes=[], context=dict(fid='context-asset'))
        client = Mock()
        client.execute_async.return_value = 'execution'
        client.poll_status.return_value = ops.api_client.StatusResult(ops.ExecutionStatus.COMPLETED, outputs=outputs)
        def download(api_id, value, path):
            asset = ops.normalize_asset(value)
            if asset.fid == 'failed':
                raise IOError('fixture download failure')
            Path(path).write_bytes(b'{"format":"atlas.agent-context","version":1,"messages":[]}'
                                   if asset.fid == 'context-asset' else png.read_bytes())
            return path
        client.download_file.side_effect = download
        runner, context = Runner(), self.context()
        with patch.object(ops, 'AtlasAPIClient', return_value=client):
            self.assertEqual(runner.execute(context), {'RUNNING_MODAL'})
        runner._thread.join(5)
        self.assertFalse(runner._thread.is_alive())
        self.assertEqual(runner.modal(context, SimpleNamespace(type='TIMER')), {'CANCELLED'})
        job = jobs.get_job(runner._job.JobFolderPath)
        self.assertEqual(job.Status, jobs.JobStatus.FAILED)
        results = {p['ParamId']: p for p in job.OutputsSnapshot}
        items = results['images']['Items']
        self.assertEqual([i['AssetId'] for i in items], ['first', 'failed', 'first'])
        self.assertTrue(Path(items[0]['FilePath']).exists())
        self.assertTrue(Path(items[2]['FilePath']).exists())
        self.assertNotEqual(items[0]['FilePath'], items[2]['FilePath'])
        self.assertIn('failure', items[1]['Error'])
        self.assertEqual(results['meshes']['Items'], [])
        self.assertTrue(results['context']['FilePath'].endswith('.atlas-context.json'))
        self.assertEqual(results['context']['AssetId'], 'context-asset')

    def test_scene_exr_preserves_hdr_values(self):
        image = bpy.data.images.new('HDR', width=2, height=2, alpha=True, float_buffer=True)
        image.pixels[:] = [4.0, 2.0, 0.5, 0.75] * 4
        item = SimpleNamespace(source_type='SCENE', param_type='exr', image_name=image.name,
                               label='HDR', param_id='hdr')
        settings = bpy.context.scene.render.image_settings
        settings.file_format = 'JPEG'
        scenes_before = set(bpy.data.scenes)
        path = self.runner._prepare_datablock_for_upload(bpy.context, item)
        self.assertEqual(settings.file_format, 'JPEG')
        self.assertEqual(set(bpy.data.scenes), scenes_before)
        self.assertEqual(Path(path).suffix, '.exr')
        loaded = bpy.data.images.load(path)
        self.assertTrue(loaded.is_float)
        for actual, expected in zip(loaded.pixels, image.pixels):
            self.assertAlmostEqual(actual, expected, delta=0.002)

    def test_mesh_array_exports_independent_objects(self):
        cube, sphere, _ = self.mesh_objects()
        definition = ops.WorkflowDefinition.from_dict(dict(version='0.2', api_id='array', base_url='https://example.invalid', name='Meshes',
            inputs=[dict(id='meshes', type='mesh', isArray=True)], outputs=[]))
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        for obj in (sphere, cube):
            entry = self.state.inputs[0].asset_items.add()
            entry.source_type, entry.mesh_name = 'SCENE', obj.name
        payload, uploads = self.runner._build_payload(bpy.context, self.state)
        self.assertEqual(payload['meshes'], [None, None])
        for upload, obj in zip(uploads, (sphere, cube)):
            raw = Path(upload['path']).read_bytes()
            length = struct.unpack_from('<I', raw, 12)[0]
            gltf = json.loads(raw[20:20 + length])
            self.assertEqual([n['name'] for n in gltf['nodes']], [obj.name])
        self.assertEqual(list(bpy.context.selected_objects), [cube])

        previous = set(bpy.context.scene.objects)
        paths = [u['path'] for u in uploads]
        self.assertEqual(bpy.ops.atlas.import_mesh_list(paths_json=json.dumps(paths)), {'FINISHED'})
        created = set(bpy.context.scene.objects) - previous
        self.assertEqual(len(created), 2)
        self.assertEqual(len({obj.users_collection[0] for obj in created}), 2)
        self.assertTrue(all(len(obj.users_collection) == 1 for obj in created))

    def test_raster_formats_load_through_result_pipeline(self):
        formats = [('jpeg', 'JPEG', 'jpg'), ('webp', 'WEBP', 'webp'),
                   ('tga', 'TARGA', 'tga'), ('tiff', 'TIFF', 'tiff')]
        if bpy.app.version >= (5, 1, 0):
            formats.append(('avif', 'AVIF', 'avif'))
        image = self.image()
        for wire_type, encoding, extension in formats:
            with self.subTest(wire_type=wire_type):
                path = str(self.root / f'encoded.{extension}')
                ops._save_image_as_png(image, path, encoding)
                output = ops.WorkflowOutputResult(param_id='result', label='Raster', param_type=wire_type)
                self.runner._output_params = [output]
                self.runner._import_plan = [dict(param_id='result', type=wire_type.upper(), path=path)]
                self.runner._process_import_plan(bpy.context)
                self.assertTrue(output.image_name)
                loaded = bpy.data.images[output.image_name]
                self.assertEqual(tuple(loaded.size), (2, 2))
                self.assertIsNotNone(loaded.packed_file)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlenderRegressions)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
