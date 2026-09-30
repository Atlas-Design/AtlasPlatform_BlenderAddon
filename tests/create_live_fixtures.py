"""Generate tiny synthetic assets in background Blender for manual API validation.

Usage: blender --background --factory-startup --python this_file.py -- OUTPUT_DIR
No credentials or network calls are used here.
"""
from pathlib import Path
import importlib
import json
import sys
import wave

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
native = addon.operators.native_assets
output = Path(sys.argv[sys.argv.index('--') + 1])
output.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

bpy.ops.object.armature_add()
rig = bpy.context.object
bone = rig.pose.bones[0]
bone.location = (0, 0, 0)
bone.keyframe_insert('location', frame=1)
bone.location = (0, 0, 1)
bone.keyframe_insert('location', frame=12)
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
cube.parent = rig
group = cube.vertex_groups.new(name=bone.name)
group.add(list(range(len(cube.data.vertices))), 1.0, 'REPLACE')
cube.modifiers.new('Skin', 'ARMATURE').object = rig
native.export_animation(bpy.context, rig, str(output / 'animation.glb'), 1, 12)
with native.export_selection(bpy.context, [cube]):
    bpy.ops.export_scene.gltf(filepath=str(output / 'mesh.glb'), use_selection=True, export_format='GLB', export_animations=False)
native.export_usdz(bpy.context, rig, str(output / 'scene.usdz'))
native.export_scene_snapshot(bpy.context, str(output / 'scene.blend'))
image = bpy.data.images.new('API test image', width=16, height=16, alpha=True, float_buffer=True)
image.pixels[:] = [0.25, 0.5, 0.75, 1.0] * 256
addon.operators._save_image_as_png(image, str(output / 'image.png'))
addon.operators._save_image_as_png(image, str(output / 'image.exr'), 'OPEN_EXR')

with wave.open(str(output / 'audio.wav'), 'wb') as handle:
    handle.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
    handle.writeframes(b'\0\0' * 24000)

(output / 'conversation.atlas-context.json').write_text(json.dumps({
    'format': 'atlas.agent-context', 'version': 1,
    'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Synthetic plugin integration test.'}]}],
}), encoding='utf-8')

# A one-page PDF fixture with a valid cross-reference table.
objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
           b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R >>',
           b'<< /Length 0 >>\nstream\n\nendstream']
pdf = b'%PDF-1.4\n'
offsets = [0]
for i, body in enumerate(objects, 1):
    offsets.append(len(pdf))
    pdf += str(i).encode() + b' 0 obj\n' + body + b'\nendobj\n'
xref = len(pdf)
pdf += b'xref\n0 5\n0000000000 65535 f \n' + b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
pdf += f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
(output / 'reference.pdf').write_bytes(pdf)

# Encode an image strip to a tiny H.264 clip using Blender's bundled FFmpeg.
scene = bpy.context.scene
editor = scene.sequence_editor_create()
strips = editor.strips if hasattr(editor, 'strips') else editor.sequences
strip = strips.new_image('Test frame', str(output / 'image.png'), channel=1, frame_start=1)
strip.frame_final_duration = 12
scene.frame_start, scene.frame_end = 1, 12
scene.render.resolution_x = scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
if hasattr(scene.render.image_settings, 'media_type'):
    scene.render.image_settings.media_type = 'VIDEO'
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.filepath = str(output / 'video.mp4')
bpy.ops.render.render(animation=True)
print('Synthetic live API fixtures ready')
