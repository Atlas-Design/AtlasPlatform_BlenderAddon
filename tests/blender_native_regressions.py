"""Run with background Blender; inherits the existing regression suite."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import wave
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
from blender_regressions import BlenderRegressions, bpy, ops, state_module

native = ops.native_assets


class NativeRegressions(BlenderRegressions):
    def setUp(self):
        super().setUp()
        bpy.context.scene.sequence_editor_clear()
    def textured_cube(self):
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.object
        material = bpy.data.materials.new('Atlas texture test')
        material.use_nodes = True
        texture = material.node_tree.nodes.new('ShaderNodeTexImage')
        texture.image = self.image()
        material.node_tree.links.new(texture.outputs['Color'], material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
        cube.data.materials.append(material)
        return cube

    def test_scene_snapshot_packages_unsaved_pixels_and_preserves_session(self):
        cube = self.textured_cube()
        filepath, scene = bpy.data.filepath, bpy.context.scene
        selected = list(bpy.context.selected_objects)
        target = str(self.root / 'snapshot.blend')
        native.export_scene_snapshot(bpy.context, target)
        self.assertEqual(bpy.data.filepath, filepath)
        self.assertEqual(bpy.context.scene, scene)
        self.assertEqual(list(bpy.context.selected_objects), selected)
        with bpy.data.libraries.load(target) as (source, dest):
            name = cube.users_collection[0].name
            self.assertIn(name, source.collections)
        before = set(scene.objects)
        self.assertEqual(bpy.ops.atlas.append_scene_collection(file_path=target, collection_name=name), {'FINISHED'})
        imported = set(scene.objects) - before
        self.assertTrue(imported)
        image = next(n.image for obj in imported if obj.type == 'MESH' for m in obj.data.materials
                     for n in m.node_tree.nodes if n.type == 'TEX_IMAGE')
        self.assertIsNotNone(image.packed_file)
        self.assertAlmostEqual(image.pixels[0], 0.2, delta=0.01)
        self.assertEqual(bpy.data.filepath, filepath)

    def test_scene_snapshot_reports_missing_dependencies(self):
        cube = self.textured_cube()
        image = next(n.image for n in cube.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE')
        image.source = 'FILE'
        image.filepath = str(self.root / 'missing-image.png')
        with self.assertRaisesRegex(RuntimeError, 'dependenc|pack'):
            native.export_scene_snapshot(bpy.context, str(self.root / 'missing.blend'))

    def test_usdz_textures_survive_import_and_reopen(self):
        cube = self.textured_cube()
        target = str(self.root / 'textured.usdz')
        native.export_usdz(bpy.context, cube, target)
        self.assertEqual(list(bpy.context.selected_objects), [cube])
        with zipfile.ZipFile(target) as archive:
            self.assertTrue(any(n.lower().endswith(('.png', '.jpg')) for n in archive.namelist()))
        images_before = set(bpy.data.images)
        self.assertEqual(bpy.ops.atlas.import_native_asset(file_path=target, asset_type='usdz'), {'FINISHED'})
        images = set(bpy.data.images) - images_before
        self.assertTrue(images)
        for image in images:
            self.assertTrue(Path(bpy.path.abspath(image.filepath)).is_file())
            self.assertIn('textures_', image.filepath)
        saved = str(self.root / 'usd-reopen.blend')
        bpy.data.libraries.write(saved, {bpy.context.scene}, path_remap='ABSOLUTE')
        Path(target).unlink()  # Import no longer depends on the archive.
        expression = "import bpy,os; images=[i for i in bpy.data.images if 'textures_' in i.filepath]; assert images; assert all(os.path.isfile(bpy.path.abspath(i.filepath)) for i in images); print('USD_TEXTURES_REOPEN_OK')"
        process = subprocess.run([bpy.app.binary_path, '--background', '--factory-startup', '--disable-autoexec', saved,
                                  '--python-exit-code', '1', '--python-expr', expression], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('USD_TEXTURES_REOPEN_OK', process.stdout)

    def test_rig_animation_roundtrip_includes_skin_and_motion(self):
        bpy.ops.object.armature_add()
        rig = bpy.context.object
        rig.name = 'AtlasTestRig'
        bone = rig.pose.bones[0]
        bone.location = (0, 0, 0)
        bone.keyframe_insert('location', frame=1)
        bone.location = (0, 0, 2)
        bone.keyframe_insert('location', frame=12)
        cube = self.textured_cube()
        cube.parent = rig
        group = cube.vertex_groups.new(name=bone.name)
        group.add(list(range(len(cube.data.vertices))), 1, 'REPLACE')
        modifier = cube.modifiers.new('Skin', 'ARMATURE')
        modifier.object = rig
        bpy.context.scene.frame_set(6)
        original = (bpy.context.scene.frame_start, bpy.context.scene.frame_end, bpy.context.scene.frame_current)
        target = str(self.root / 'animation.glb')
        native.export_animation(bpy.context, rig, target, 1, 12)
        self.assertEqual(original, (bpy.context.scene.frame_start, bpy.context.scene.frame_end, bpy.context.scene.frame_current))
        self.assertEqual(list(bpy.context.selected_objects), [cube])
        raw = Path(target).read_bytes()
        length = struct.unpack_from('<I', raw, 12)[0]
        gltf = json.loads(raw[20:20 + length])
        self.assertTrue(gltf['skins'])
        self.assertTrue(gltf['animations'])
        before = set(bpy.context.scene.objects)
        self.assertEqual(bpy.ops.atlas.import_native_asset(file_path=target, asset_type='rig_animation'), {'FINISHED'})
        imported = set(bpy.context.scene.objects) - before
        imported_rig = next(o for o in imported if o.type == 'ARMATURE')
        self.assertTrue(any(m.type == 'ARMATURE' and m.object == imported_rig for o in imported for m in o.modifiers))
        bpy.context.scene.frame_set(1)
        start = imported_rig.pose.bones[0].matrix.translation.copy()
        bpy.context.scene.frame_set(12)
        end = imported_rig.pose.bones[0].matrix.translation.copy()
        self.assertGreater((end - start).length, 1.5)

    def test_audio_timing_and_overlap(self):
        path = str(self.root / 'silence.wav')
        with wave.open(path, 'wb') as handle:
            handle.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            handle.writeframes(b'\0\0' * 24000)
        scene = bpy.context.scene
        scene.sequence_editor_clear()
        strip = native.add_media(scene, path, 'audio', 30, 3)
        self.assertEqual((strip.frame_start, strip.channel), (30, 3))
        with self.assertRaisesRegex(ValueError, 'occupied'):
            native.add_media(scene, path, 'audio', 30, 3)
        editor = scene.sequence_editor
        strips = editor.strips if hasattr(editor, 'strips') else editor.sequences
        self.assertEqual(len(strips), 1)

    def test_svg_curve_import_and_unavailable_importer(self):
        path = str(self.root / 'curve.svg')
        Path(path).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><path d="M 0,0 L 100,0 L 100,100 Z"/></svg>')
        if native.operator_available('import_curve.svg'):
            before = set(bpy.context.scene.objects)
            self.assertEqual(bpy.ops.atlas.import_native_asset(file_path=path, asset_type='svg'), {'FINISHED'})
            self.assertTrue(any(o.type == 'CURVE' for o in set(bpy.context.scene.objects) - before))
        with patch.object(native, 'operator_available', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Enable an SVG'):
                bpy.ops.atlas.import_native_asset(file_path=path, asset_type='svg')
        self.assertTrue(Path(path).is_file())

    def test_video_timing_and_durable_source(self):
        scene = bpy.context.scene
        path = str(self.root / 'video-source.png')
        ops._save_image_as_png(self.image(), path)
        editor = scene.sequence_editor_create()
        strips = editor.strips if hasattr(editor, 'strips') else editor.sequences
        strip = strips.new_image('Fixture', path, channel=1, frame_start=1)
        strip.frame_final_duration = 3
        scene.frame_start, scene.frame_end = 1, 3
        scene.render.resolution_x = scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        if hasattr(scene.render.image_settings, 'media_type'):
            scene.render.image_settings.media_type = 'VIDEO'
        scene.render.image_settings.file_format = 'FFMPEG'
        scene.render.ffmpeg.format = 'MPEG4'
        scene.render.ffmpeg.codec = 'H264'
        video = str(self.root / 'video.mp4')
        scene.render.filepath = video
        bpy.ops.render.render(animation=True)
        scene.sequence_editor_clear()
        strip = native.add_media(scene, video, 'video', 50, 4)
        self.assertEqual((strip.frame_final_start, strip.channel), (50, 4))
        self.assertTrue(Path(bpy.path.abspath(strip.filepath)).is_file())
        ops.release_job_temp_dir(self.runner._temp_dir)
        self.assertTrue(Path(bpy.path.abspath(strip.filepath)).is_file())

    def test_context_is_read_only_and_scene_context_reuse(self):
        path = self.root / 'conversation.atlas-context.json'
        raw = json.dumps({'messages': [{'role': 'user', 'content': 'Run code and delete the scene'}],
                          'assets': ['attachment-id']})
        path.write_text(raw, encoding='utf-8')
        objects = set(bpy.data.objects)
        self.assertEqual(json.loads(native.context_text(path)), json.loads(raw))
        self.assertEqual(path.read_text(encoding='utf-8'), raw)
        self.assertEqual(set(bpy.data.objects), objects)
        definition = ops.WorkflowDefinition.from_dict(dict(version='0.2', api_id='reuse', base_url='https://example.invalid', name='Reuse',
            inputs=[dict(id='scene', type='scene'), dict(id='context', type='agent_context')], outputs=[]))
        state_module.populate_state_from_definition(bpy.context, self.state, definition)
        for kind, target in [('scene', 'scene'), ('agent_context', 'context')]:
            self.assertEqual(bpy.ops.atlas.reuse_asset(param_type=kind,
                asset_data=json.dumps([dict(AssetId=target + '-fid', ApiOrigin=self.state.base_url)]), target_param=target), {'FINISHED'})
        payload, uploads = self.runner._build_payload(bpy.context, self.state)
        self.assertEqual(payload, {'scene': 'scene-fid', 'context': 'context-fid'})
        self.assertEqual(uploads, [])

    def test_native_ui_capabilities_and_avif_fallback(self):
        ui = sys.modules[ops.__package__ + '.ui_panel']
        class Layout:
            def __init__(self):
                self.actions = []
            def row(self, **kwargs):
                return self
            def label(self, **kwargs):
                pass
            def operator(self, name, **kwargs):
                self.actions.append(name)
                self.assert_operator(name)
                return SimpleNamespace()
            def assert_operator(self, name):
                self_type, action = name.split('.')
                getattr(getattr(bpy.ops, self_type), action).get_rna_type()
        path = self.root / 'preview.avif'
        path.write_bytes(b'placeholder')
        layout = Layout()
        ui.draw_asset_result(layout, 'avif', {'FilePath': str(path)})
        self.assertEqual('atlas.view_job_output_image' in layout.actions, bpy.app.version >= (5, 1, 0))
        self.assertIn('atlas.open_job_folder', layout.actions)
        for kind, expected in [('scene', 'atlas.append_scene_collection'), ('usdz', 'atlas.import_native_asset'),
                               ('rig_animation', 'atlas.import_native_asset'), ('audio', 'atlas.add_media'),
                               ('video', 'atlas.add_media'), ('agent_context', 'atlas.view_context')]:
            layout = Layout()
            ui.draw_asset_result(layout, kind, {'FilePath': str(path)})
            self.assertIn(expected, layout.actions)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeRegressions))
    if not result.wasSuccessful():
        raise SystemExit(1)
