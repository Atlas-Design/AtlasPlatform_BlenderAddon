"""Shared API type capabilities and asset-reference parsing (no Blender imports)."""
from dataclasses import dataclass
import re
import mimetypes

PRIMITIVE_TYPES = {'boolean', 'number', 'string'}
FILE_FORMATS = {
    'image': 'png', 'mesh': 'glb', 'jpeg': 'jpg', 'webp': 'webp',
    'tga': 'tga', 'tiff': 'tiff', 'avif': 'avif', 'exr': 'exr',
    'usdz': 'usdz', 'scene': 'blend', 'rig_animation': 'glb',
    'audio': 'mp3', 'video': 'mp4', 'pdf': 'pdf', 'svg': 'svg',
    'agent_context': 'atlas-context.json',
}
RASTER_TYPES = {'image', 'jpeg', 'webp', 'tga', 'tiff', 'avif', 'exr'}
SCENE_INPUT_TYPES = {'image', 'mesh', 'exr', 'scene', 'usdz', 'rig_animation'}
MIME_EXTENSIONS = {
    'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
    'image/avif': 'avif', 'image/tiff': 'tiff', 'image/x-tga': 'tga',
    'image/x-exr': 'exr', 'image/exr': 'exr', 'application/x-exr': 'exr',
    'image/svg+xml': 'svg', 'model/gltf-binary': 'glb',
    'model/gltf+json': 'gltf', 'model/vnd.usdz+zip': 'usdz',
    'application/x-blender': 'blend', 'application/pdf': 'pdf',
    'application/vnd.atlas.agent-context+json': 'atlas-context.json',
    'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'audio/x-wav': 'wav',
    'audio/ogg': 'ogg', 'audio/flac': 'flac', 'audio/mp4': 'm4a',
    'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov',
}


def safe_file_key(value):
    """API labels are data, never paths. Include an index at call sites."""
    return re.sub(r'[^A-Za-z0-9_-]', '_', str(value))[:80] or 'asset'


def file_extension(filename):
    filename = str(filename or '').lower()
    if filename.endswith('.atlas-context.json'):
        return 'atlas-context.json'
    return filename.rsplit('.', 1)[-1] if '.' in filename else ''


def upload_mime(filename):
    extension = file_extension(filename)
    preferred = {'exr': 'image/x-exr', 'wav': 'audio/wav', 'jpeg': 'image/jpeg',
                 'tif': 'image/tiff', 'bmp': 'image/bmp', 'gif': 'image/gif',
                 'avi': 'video/x-msvideo'}
    return (preferred.get(extension) or next((mime for mime, ext in MIME_EXTENSIONS.items() if ext == extension), None)
            or mimetypes.guess_type(str(filename))[0] or 'application/octet-stream')


def detected_extension(prefix, fallback):
    """Concrete signatures override stale MIME labels on legacy assets."""
    signatures = ((b'glTF', 'glb'), (b'v/1\x01', 'exr'), (b'%PDF-', 'pdf'),
                  (b'\x89PNG\r\n\x1a\n', 'png'), (b'\xff\xd8\xff', 'jpg'),
                  (b'II*\x00', 'tiff'), (b'MM\x00*', 'tiff'), (b'BLENDER', 'blend'),
                  (b'GIF8', 'gif'), (b'BM', 'bmp'), (b'fLaC', 'flac'), (b'ID3', 'mp3'))
    for signature, extension in signatures:
        if prefix.startswith(signature):
            return extension
    if prefix.startswith(b'RIFF'):
        return {b'WAVE': 'wav', b'WEBP': 'webp', b'AVI ': 'avi'}.get(prefix[8:12], fallback)
    if prefix[4:8] == b'ftyp':
        if prefix[8:12] in (b'avif', b'avis'):
            return 'avif'
        if prefix[8:12] in (b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V '):
            return 'mp4'
    if prefix.startswith(b'PK\x03\x04') and fallback == 'usdz':
        return 'usdz'
    return fallback


def output_extension(param_type, declared='', mime='', filename=''):
    """Prefer concrete download metadata; use the workflow format as fallback."""
    extension = MIME_EXTENSIONS.get(str(mime).split(';')[0].strip().lower())
    if not extension:
        extension = file_extension(filename) or declared or FILE_FORMATS.get(param_type, 'bin')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9]+)*', extension):
        raise ValueError(f'Invalid output format: {extension!r}')
    return extension.lower()


def compatible_asset(source_type, target_type):
    return source_type == target_type or (target_type == 'image' and source_type in RASTER_TYPES)


@dataclass
class AssetReference:
    fid: str
    download_url: str = ''
    mime: str = ''
    filename: str = ''
    size: int | None = None


def normalize_asset(value):
    """Accept asset objects and legacy UUID strings at a single boundary.

    fid is the chaining contract. URL/metadata can be omitted by older APIs;
    the canonical download endpoint remains available in that case.
    """
    if isinstance(value, AssetReference):
        return value
    if isinstance(value, str) and value.strip():
        return AssetReference(value.strip())
    if not isinstance(value, dict) or not isinstance(value.get('fid'), str) or not value['fid'].strip():
        raise ValueError('Expected an asset object containing fid, or a file ID string')
    metadata = value.get('metadata') or {}
    if not isinstance(metadata, dict):
        raise ValueError('Asset metadata must be an object')
    def get(*keys, default=''):
        for source in (value, metadata):
            for key in keys:
                if source.get(key) is not None:
                    return source[key]
        return default
    url = get('download_url', 'url')
    mime = get('mime', 'content_type')
    filename = get('filename')
    size = get('size_bytes', 'size', default=None)
    if not all(isinstance(v, str) for v in (url, mime, filename)):
        raise ValueError('Asset URL, MIME and filename must be strings')
    if size is not None and (type(size) is not int or size < 0):
        raise ValueError('Asset byte size must be a nonnegative integer')
    return AssetReference(value['fid'].strip(), url, mime, filename, size)
