"""Pure Python contract tests. Run: python -m unittest discover -s tests -p test_*.py"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas'))
import asset_types as assets
from workflow_definition import WorkflowDefinition
from api_client import AtlasAPIClient

FID = '11111111-1111-4111-8111-111111111111'


class AssetContractTests(unittest.TestCase):
    def test_all_types_export_without_openapi(self):
        wf = WorkflowDefinition.from_json_file(str(ROOT / 'examples/all-types-v02.example.json'))
        self.assertEqual((len(wf.inputs), len(wf.outputs)), (15, 21))
        self.assertEqual(sum(p.is_array for p in wf.inputs + wf.outputs), 4)
        self.assertTrue(all(p.required is None for p in wf.inputs))
        self.assertEqual(wf.get_output('conversation_output').format, 'atlas-context.json')

    def test_required_and_default_presence_are_independent(self):
        data = dict(version='0.2', api_id='id', base_url='https://example.invalid', name='test',
                    inputs=[dict(id='a', type='boolean', required=True, default_value=False),
                            dict(id='b', type='number', required=False, default_value=0),
                            dict(id='c', type='string')], outputs=[])
        wf = WorkflowDefinition.from_dict(data)
        self.assertEqual([(p.required, p.has_default) for p in wf.inputs], [(True, True), (False, True), (None, False)])
        data['inputs'][0]['isArray'] = 'false'
        with self.assertRaises(ValueError):
            WorkflowDefinition.from_dict(data)

    def test_unknown_wire_type_survives(self):
        wf = WorkflowDefinition.from_dict(dict(version='0.2', api_id='id', base_url='x', name='test',
                                               inputs=[dict(id='a', type='future_type')], outputs=[]))
        self.assertEqual(wf.inputs[0].type, 'future_type')

    def test_objects_and_legacy_ids_normalize(self):
        asset = assets.normalize_asset(dict(fid=FID, download_url='/download',
                                           metadata=dict(content_type='image/jpeg', filename='result.jpg', size_bytes=4)))
        self.assertEqual((asset.fid, asset.mime, asset.size), (FID, 'image/jpeg', 4))
        self.assertEqual(assets.normalize_asset(FID).fid, FID)
        with self.assertRaises(ValueError):
            assets.normalize_asset({'filename': 'not-an-asset'})

    def test_formats_and_path_keys(self):
        self.assertEqual(assets.output_extension('image', 'png', 'image/jpeg'), 'jpg')
        self.assertEqual(assets.output_extension('agent_context'), 'atlas-context.json')
        self.assertEqual(assets.output_extension('image', filename='../named.tiff'), 'tiff')
        self.assertNotIn('/', assets.safe_file_key('../../escape'))
        with self.assertRaises(ValueError):
            assets.output_extension('image', '../escape')

    def response(self, headers=None, status=200, chunks=(b'one', b'two')):
        response = Mock(status_code=status, headers=headers or {})
        response.iter_content.return_value = iter(chunks)
        return response

    def test_streamed_asset_download_uses_url_auth_and_real_extension(self):
        response = self.response({'Content-Type': 'image/jpeg'})
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        with tempfile.TemporaryDirectory(prefix='atlas_contract_') as directory:
            with patch('api_client.requests.get', return_value=response) as get:
                path = client.download_file('workflow', dict(fid=FID, download_url='/files/result'), str(Path(directory) / 'result.png'))
            self.assertEqual(Path(path).suffix, '.jpg')
            self.assertEqual(Path(path).read_bytes(), b'onetwo')
            self.assertEqual(get.call_args.args[0], 'https://api.example.invalid/files/result')
            self.assertEqual(get.call_args.kwargs['headers'], {'Authorization': 'Bearer test-key'})
            self.assertTrue(get.call_args.kwargs['stream'])
            response.close.assert_called_once()

    def test_untrusted_asset_url_uses_canonical_fid_endpoint(self):
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        with tempfile.TemporaryDirectory(prefix='atlas_contract_') as directory:
            with patch('api_client.requests.get', return_value=self.response()) as get:
                client.download_file('workflow', dict(fid=FID, download_url='https://other.invalid/file'), str(Path(directory) / 'a.png'))
            self.assertEqual(get.call_args.args[0], f'https://api.example.invalid/0.2/download_binary_result/{FID}')

    def test_every_file_type_downloads_without_changing_bytes(self):
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        with tempfile.TemporaryDirectory(prefix='atlas_contract_') as directory:
            for wire_type, extension in assets.FILE_FORMATS.items():
                with self.subTest(wire_type=wire_type):
                    data = b'opaque asset bytes: ' + wire_type.encode()
                    target = Path(directory) / f'{wire_type}.{extension}'
                    with patch('api_client.requests.get', return_value=self.response(chunks=(data,))):
                        path = client.download_file('workflow', dict(fid=FID, filename=target.name), str(target))
                    self.assertEqual(Path(path).name, target.name)
                    self.assertEqual(Path(path).read_bytes(), data)

    def test_upload_includes_canonical_mime(self):
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        with tempfile.TemporaryDirectory(prefix='atlas_contract_') as directory:
            for name, mime in [('a.glb', 'model/gltf-binary'), ('a.exr', 'image/x-exr'),
                               ('a.atlas-context.json', 'application/vnd.atlas.agent-context+json'),
                               ('a.mp4', 'video/mp4'), ('a.usdz', 'model/vnd.usdz+zip')]:
                path = Path(directory) / name
                path.write_bytes(b'fixture')
                response = Mock(status_code=200)
                response.json.return_value = {'fid': FID}
                with patch('api_client.requests.post', return_value=response) as post:
                    self.assertEqual(client.upload_file('workflow', str(path)), FID)
                self.assertEqual(post.call_args.kwargs['files']['file'][2], mime)

    def test_legacy_wrong_png_mime_does_not_rename_mesh_pdf_or_usdz(self):
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        with tempfile.TemporaryDirectory(prefix='atlas_contract_') as directory:
            for extension, data in [('glb', b'glTF\x02\0\0\0'), ('exr', b'v/1\x01'),
                                    ('pdf', b'%PDF-1.4'), ('usdz', b'PK\x03\x04')]:
                with self.subTest(extension=extension):
                    with patch('api_client.requests.get', return_value=self.response({'Content-Type': 'image/png'}, chunks=(data,))):
                        path = client.download_file('workflow', FID, str(Path(directory) / ('asset.' + extension)))
                    self.assertTrue(path.endswith('.' + extension))
                    self.assertEqual(Path(path).read_bytes(), data)

    def test_cross_origin_redirect_never_receives_credentials(self):
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        response = self.response({'Location': 'https://other.invalid/file'}, status=302)
        with patch('api_client.requests.get', return_value=response) as get:
            with self.assertRaisesRegex(ValueError, 'outside'):
                client.download_file('workflow', FID, 'unused.png')
        self.assertEqual(get.call_count, 1)

    def test_failed_stream_does_not_leave_partial_or_overwrite_existing(self):
        client = AtlasAPIClient('https://api.example.invalid', '0.2', api_key='test-key')
        response = self.response()
        def broken():
            yield b'partial'
            raise IOError('connection lost')
        response.iter_content.return_value = broken()
        with tempfile.TemporaryDirectory(prefix='atlas_contract_') as directory:
            path = Path(directory) / 'a.png'
            path.write_bytes(b'previous download')
            with patch('api_client.requests.get', return_value=response):
                with self.assertRaises(IOError):
                    client.download_file('workflow', FID, str(path))
            self.assertEqual(path.read_bytes(), b'previous download')
            self.assertFalse(Path(str(path) + '.part').exists())


if __name__ == '__main__':
    unittest.main()
