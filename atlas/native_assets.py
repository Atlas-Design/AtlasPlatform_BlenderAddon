"""Explicit Blender adapters for scene, USDZ, animation and media assets."""
import json
import os
from pathlib import Path
import subprocess
import textwrap
import uuid
from contextlib import contextmanager
from array import array

import bpy
from bpy.props import StringProperty, IntProperty, EnumProperty
from bpy.types import Operator


def operator_available(name):
    try:
        group, action = name.split('.')
        getattr(getattr(bpy.ops, group), action).get_rna_type()
        return True
    except (AttributeError, RuntimeError):
        return False


@contextmanager
def export_selection(context, objects):
    """Expose exactly the export set and restore selection, visibility and mode."""
    layer = context.view_layer
    previous = [obj for obj in layer.objects if obj.select_get()]
    active = layer.objects.active
    mode = active.mode if active else 'OBJECT'
    visibility = [(obj, obj.hide_get(), obj.hide_viewport, obj.hide_select) for obj in objects]
    if any(obj.name not in layer.objects for obj in objects):
        raise ValueError('Export objects must belong to the active view layer')
    try:
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in layer.objects:
            obj.select_set(False)
        for obj, *_ in visibility:
            obj.hide_viewport = obj.hide_select = False
            obj.hide_set(False)
            obj.select_set(True)
        layer.objects.active = objects[0]
        yield
    finally:
        for obj in layer.objects:
            obj.select_set(False)
        for obj, hidden, viewport, locked in visibility:
            obj.hide_set(hidden)
            obj.hide_viewport, obj.hide_select = viewport, locked
        for obj in previous:
            obj.select_set(True)
        layer.objects.active = active
        if active and mode != 'OBJECT' and active.mode != mode:
            bpy.ops.object.mode_set(mode=mode)


def export_scene_snapshot(context, path):
    """Pack a scene copy in an isolated process; never save over the active file."""
    source = str(Path(path).with_suffix('.source.blend'))
    script = str(Path(path).with_suffix('.pack.py'))
    manifest = str(Path(path).with_suffix('.pixels.json'))
    bpy.data.libraries.write(source, {context.scene}, path_remap='ABSOLUTE')
    # Library writes do not preserve unsaved image pixels. Transfer those to
    # the isolated copy without packing or changing images in the user's file.
    pixel_files = []
    try:
        reachable = {context.scene}
        users = bpy.data.user_map()
        while True:
            dependencies = {data for data, owners in users.items() if owners & reachable}
            if dependencies <= reachable:
                break
            reachable.update(dependencies)
        for image in bpy.data.images:
            if image not in reachable:
                continue
            if image.source not in ('GENERATED', 'FILE') or not (image.is_dirty or image.source == 'GENERATED'):
                continue
            if not len(image.pixels):
                continue
            pixel_path = str(Path(path).with_suffix(f'.pixels-{len(pixel_files)}'))
            pixel_files.append((image.name, pixel_path))
            pixels = array('f', [0.0]) * len(image.pixels)
            image.pixels.foreach_get(pixels)
            with open(pixel_path, 'wb') as handle:
                pixels.tofile(handle)
        Path(manifest).write_text(json.dumps(pixel_files), encoding='utf-8')
    except Exception:
        for _, pixel_path in pixel_files:
            if os.path.isfile(pixel_path):
                os.remove(pixel_path)
        os.remove(source)
        raise
    # The helper handles only our scene copy, with automatic scripts disabled.
    Path(script).write_text(textwrap.dedent('''
        import bpy, os, sys, json
        from array import array
        target = sys.argv[sys.argv.index('--') + 1]
        scene_name = sys.argv[sys.argv.index('--') + 2]
        bpy.context.window.scene = bpy.data.scenes[scene_name]
        with open(sys.argv[sys.argv.index('--') + 3], encoding='utf-8') as handle:
            pixel_files = json.load(handle)
        for name, path in pixel_files:
            image = bpy.data.images.get(name)
            if image:
                pixels = array('f')
                with open(path, 'rb') as handle:
                    pixels.fromfile(handle, os.path.getsize(path) // pixels.itemsize)
                image.pixels.foreach_set(pixels)
                image.pack()
        if bpy.data.libraries:
            raise RuntimeError('Scene contains linked libraries. Make dependencies local before taking a snapshot.')
        bpy.ops.file.pack_all()
        external = bpy.utils.blend_paths(absolute=True, packed=False)
        if external:
            names = ', '.join(os.path.basename(p) for p in external[:8])
            raise RuntimeError('Scene has unpacked or missing dependencies: ' + names + '. Use a prepared scene file or remove external caches/media.')
        bpy.ops.wm.save_as_mainfile(filepath=target, check_existing=False)
    '''), encoding='utf-8')
    try:
        result = subprocess.run(
            [bpy.app.binary_path, '--background', '--factory-startup', '--disable-autoexec',
             source, '--python-exit-code', '1', '--python', script, '--', path, context.scene.name, manifest],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not os.path.isfile(path):
            raise RuntimeError('Could not package scene snapshot: ' + (result.stderr + result.stdout)[-2400:])
    finally:
        for temporary in (source, script, manifest, *(p for _, p in pixel_files)):
            if os.path.isfile(temporary):
                os.remove(temporary)
    return path


def export_usdz(context, root, path):
    if not operator_available('wm.usd_export'):
        raise ValueError('USD export is unavailable in this Blender build; use a file or asset ID')
    if not root:
        raise ValueError('Select a root object for USDZ export')
    objects = [root, *root.children_recursive]
    with export_selection(context, objects):
        operator = bpy.ops.wm.usd_export
        props = operator.get_rna_type().properties
        kwargs = dict(filepath=path, selected_objects_only=True, export_materials=True)
        if 'export_textures_mode' in props:
            kwargs['export_textures_mode'] = 'NEW'
        elif 'export_textures' in props:
            kwargs['export_textures'] = True
        result = operator(**kwargs)
        if 'FINISHED' not in result or not os.path.isfile(path):
            raise RuntimeError('USDZ export failed')
    return path


def export_animation(context, rig, path, frame_start, frame_end):
    if not rig or rig.type != 'ARMATURE':
        raise ValueError('Choose an armature with an active action for animation export')
    if not rig.animation_data or not rig.animation_data.action:
        raise ValueError('Assign the desired action to the armature before exporting')
    if frame_end < frame_start:
        raise ValueError('Animation end frame must be at or after the start frame')
    if not operator_available('export_scene.gltf'):
        raise ValueError('glTF exporter is unavailable; use an animation file or asset ID')
    objects = [rig] + [obj for obj in context.scene.objects if obj.type == 'MESH' and
                      any(m.type == 'ARMATURE' and m.object == rig for m in obj.modifiers)]
    if len(objects) == 1:
        raise ValueError('The armature needs a mesh with an Armature modifier')
    scene = context.scene
    frames = scene.frame_start, scene.frame_end, scene.frame_current, scene.frame_subframe
    tracks = [(track, track.mute) for track in rig.animation_data.nla_tracks]
    try:
        scene.frame_start, scene.frame_end = frame_start, frame_end
        for track, _ in tracks:
            track.mute = True
        with export_selection(context, objects):
            kwargs = dict(filepath=path, export_format='GLB', use_selection=True,
                          export_animations=True, export_skins=True, export_frame_range=True,
                          export_force_sampling=True, export_nla_strips=False)
            props = bpy.ops.export_scene.gltf.get_rna_type().properties
            if 'export_animation_mode' in props:
                kwargs['export_animation_mode'] = 'ACTIVE_ACTIONS'
            result = bpy.ops.export_scene.gltf(**kwargs)
            if 'FINISHED' not in result:
                raise RuntimeError('Animation export failed')
    finally:
        scene.frame_start, scene.frame_end = frames[:2]
        scene.frame_set(frames[2], subframe=frames[3])
        for track, muted in tracks:
            track.mute = muted
    return path


_collection_choices = []


def collection_choices(self, context):
    global _collection_choices
    try:
        with bpy.data.libraries.load(self.file_path, link=False) as (source, target):
            _collection_choices = [(name, name, '') for name in source.collections]
    except (OSError, RuntimeError):
        _collection_choices = []
    return _collection_choices


class ATLAS_OT_AppendSceneCollection(Operator):
    """Append one collection without opening or replacing the current scene"""
    bl_idname = 'atlas.append_scene_collection'
    bl_label = 'Append Collection'
    bl_options = {'REGISTER', 'UNDO'}
    file_path: StringProperty(subtype='FILE_PATH', options={'HIDDEN'})
    collection_name: EnumProperty(name='Collection', items=collection_choices)

    def invoke(self, context, event):
        if not collection_choices(self, context):
            self.report({'ERROR'}, 'This scene has no appendable collections.')
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            with bpy.data.libraries.load(self.file_path, link=False) as (source, target):
                if self.collection_name not in source.collections:
                    raise ValueError('Choose a collection from this scene file')
                target.collections = [self.collection_name]
            context.scene.collection.children.link(target.collections[0])
            return {'FINISHED'}
        except (OSError, RuntimeError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class ATLAS_OT_OpenSceneSeparately(Operator):
    """Open a result in another Blender window with automatic scripts disabled"""
    bl_idname = 'atlas.open_scene_separately'
    bl_label = 'Open in New Blender'
    file_path: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        if not os.path.isfile(self.file_path):
            self.report({'ERROR'}, 'Scene file is missing')
            return {'CANCELLED'}
        subprocess.Popen([bpy.app.binary_path, '--disable-autoexec', self.file_path])
        return {'FINISHED'}


class ATLAS_OT_ImportNativeAsset(Operator):
    """Import a USDZ, rig animation or SVG result into the current scene"""
    bl_idname = 'atlas.import_native_asset'
    bl_label = 'Import Asset'
    bl_options = {'REGISTER', 'UNDO'}
    file_path: StringProperty(subtype='FILE_PATH')
    asset_type: StringProperty()

    def execute(self, context):
        try:
            if self.asset_type == 'usdz':
                if not operator_available('wm.usd_import'):
                    raise ValueError('USD importer is unavailable; the downloaded file remains in the job folder')
                textures = str(Path(self.file_path).parent / ('textures_' + uuid.uuid4().hex[:12]))
                os.makedirs(textures, exist_ok=True)
                result = bpy.ops.wm.usd_import(filepath=self.file_path, import_textures_mode='IMPORT_COPY',
                                              import_textures_dir=textures, set_frame_range=False)
            elif self.asset_type == 'rig_animation':
                if not operator_available('import_scene.gltf'):
                    raise ValueError('glTF importer is unavailable')
                result = bpy.ops.import_scene.gltf(filepath=self.file_path)
            elif self.asset_type == 'svg':
                if not operator_available('import_curve.svg'):
                    raise ValueError('Enable an SVG curve importer first; the file remains in the job folder')
                result = bpy.ops.import_curve.svg(filepath=self.file_path)
            else:
                raise ValueError('No native importer for this asset type')
            if 'FINISHED' not in result:
                raise RuntimeError('Import did not complete')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


def add_media(scene, path, kind, frame, channel):
    """Insert at the requested channel; reject overlap instead of moving strips."""
    editor = scene.sequence_editor_create()
    strips = getattr(editor, 'strips', None)
    if strips is None:  # Blender 4.x
        strips = editor.sequences
    existing = list(strips)
    creator = strips.new_sound if kind == 'audio' else strips.new_movie
    strip = creator(Path(path).stem, path, channel=channel, frame_start=frame)
    if strip.channel != channel or any(s.channel == channel and
            s.frame_final_start < strip.frame_final_end and strip.frame_final_start < s.frame_final_end
            for s in existing):
        strips.remove(strip)
        raise ValueError('That channel is occupied during this clip; choose another channel or start frame')
    return strip


class ATLAS_OT_AddMedia(Operator):
    """Add a result to the Sequencer at the chosen frame and channel"""
    bl_idname = 'atlas.add_media'
    bl_label = 'Add to Sequencer'
    bl_options = {'REGISTER', 'UNDO'}
    file_path: StringProperty(subtype='FILE_PATH')
    asset_type: StringProperty()
    frame_start: IntProperty(name='Start Frame', default=1)
    channel: IntProperty(name='Channel', min=1, max=128, default=1)

    def invoke(self, context, event):
        self.frame_start = context.scene.frame_current
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, 'frame_start')
        self.layout.prop(self, 'channel')
        if self.asset_type == 'video':
            self.layout.label(text='Adds the video strip; audio is added separately.')

    def execute(self, context):
        try:
            if self.asset_type not in ('audio', 'video'):
                raise ValueError('Expected audio or video')
            add_media(context.scene, self.file_path, self.asset_type, self.frame_start, self.channel)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


def context_text(path):
    """Parse bounded JSON as data only; preserve unknown schemas and attachments."""
    with open(path, 'rb') as handle:
        raw = handle.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Context is larger than 4 MiB; use the file in the job folder')
    return json.dumps(json.loads(raw.decode('utf-8-sig')), indent=2, ensure_ascii=False)


class ATLAS_OT_ViewContext(Operator):
    """Read conversation JSON without executing tools or fetching attachments"""
    bl_idname = 'atlas.view_context'
    bl_label = 'Conversation Context'
    file_path: StringProperty(subtype='FILE_PATH')
    page: IntProperty(name='Page', default=1, min=1)

    def invoke(self, context, event):
        try:
            self._lines = [part for line in context_text(self.file_path).splitlines()
                           for part in (textwrap.wrap(line, 100, replace_whitespace=False) or [''])]
        except (OSError, ValueError, UnicodeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.page = 1
        return context.window_manager.invoke_props_dialog(self, width=800)

    def draw(self, context):
        lines = getattr(self, '_lines', [])
        pages = max(1, (len(lines) + 23) // 24)
        self.layout.label(text=f'Read-only JSON — {pages} pages. Linked assets remain references.')
        self.layout.prop(self, 'page')
        start = (min(self.page, pages) - 1) * 24
        for line in lines[start:start + 24]:
            self.layout.label(text=line)

    def check(self, context):
        return True

    def execute(self, context):
        return {'FINISHED'}


classes = (ATLAS_OT_AppendSceneCollection, ATLAS_OT_OpenSceneSeparately,
           ATLAS_OT_ImportNativeAsset, ATLAS_OT_AddMedia, ATLAS_OT_ViewContext)
