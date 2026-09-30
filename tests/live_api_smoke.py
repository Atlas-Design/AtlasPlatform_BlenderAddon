"""Opt-in integration check. Uploads fixtures and executes a real workflow.

Supply API_KEY (or ATLAS_TEST_KEY) through the process environment, never a file.
python tests/live_api_smoke.py --workflow PATH --fixtures DIR --output DIR
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'atlas'))
from api_client import AtlasAPIClient
from asset_types import FILE_FORMATS, normalize_asset, output_extension, safe_file_key, file_extension
from workflow_definition import WorkflowDefinition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow', required=True)
    parser.add_argument('--fixtures', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--chain', action='store_true')
    args = parser.parse_args()
    key = os.environ.get('ATLAS_TEST_KEY') or os.environ.get('API_KEY')
    if not key:
        parser.error('Set API_KEY in the process environment')
    logging.disable(logging.CRITICAL)
    workflow = WorkflowDefinition.from_json_file(args.workflow)
    client = AtlasAPIClient(workflow.base_url, workflow.version, api_key=key, timeout=60)
    fixtures = Path(args.fixtures)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = dict(image='image.png', mesh='mesh.glb', scene='scene.blend', usdz='scene.usdz',
                 rig_animation='animation.glb', exr='image.exr', audio='audio.wav',
                 video='video.mp4', pdf='reference.pdf', agent_context='conversation.atlas-context.json')
    payload, uploaded = {}, {}
    for param in workflow.inputs:
        kind = str(getattr(param.type, 'value', param.type))
        if kind in files:
            if kind not in uploaded:
                uploaded[kind] = client.upload_file(workflow.api_id, str(fixtures / files[kind]))
                print('Uploaded:', kind, flush=True)
            payload[param.id] = [uploaded[kind], uploaded[kind]] if param.is_array else uploaded[kind]
        elif kind in ('boolean', 'number', 'string'):
            payload[param.id] = param.default_value
        else:
            raise ValueError('No synthetic fixture for input type: ' + kind)
    for run in range(2 if args.chain else 1):
        execution = client.execute_async(workflow.api_id, payload)
        print('Submitted live run', run + 1, flush=True)
        deadline = time.monotonic() + 300
        while True:
            status = client.poll_status(execution)
            if status.is_failed:
                raise RuntimeError(status.error.format_message() if status.error else 'Workflow failed')
            if status.is_complete:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Live workflow still running after five minutes')
            time.sleep(2)
        records = []
        by_type = {}
        for param in workflow.outputs:
            kind = str(getattr(param.type, 'value', param.type))
            value = status.outputs[param.id]
            if kind not in FILE_FORMATS:
                records.append(dict(parameter=param.id, type=kind, shape=type(value).__name__))
                continue
            values = value if param.is_array else [value]
            for index, item in enumerate(values):
                asset = normalize_asset(item)
                extension = output_extension(kind, param.format or '', asset.mime, asset.filename)
                path = output_dir / f'run{run + 1}_{safe_file_key(param.id)}_{index}.{extension}'
                downloaded = client.download_file(workflow.api_id, item, str(path))
                if kind in ('mesh', 'rig_animation', 'scene', 'usdz', 'pdf', 'exr', 'agent_context'):
                    if file_extension(downloaded) != FILE_FORMATS[kind]:
                        raise ValueError(f'{param.id}: downloaded file has an unexpected format')
                by_type.setdefault(kind, []).append(asset.fid)
                # Only structural evidence goes into the report; no credentials,
                # signed URLs, UUIDs or conversation contents are recorded.
                records.append(dict(parameter=param.id, type=kind, shape=type(item).__name__,
                    keys=sorted(item) if isinstance(item, dict) else [],
                    bytes=Path(downloaded).stat().st_size, suffix=Path(downloaded).suffix))
            print('Downloaded:', param.id, len(values), flush=True)
        (output_dir / f'report-run{run + 1}.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        print('Verified output parameters:', len(workflow.outputs), flush=True)
        if run == 0 and args.chain:
            for param in workflow.inputs:
                kind = str(getattr(param.type, 'value', param.type))
                if kind in by_type:
                    payload[param.id] = by_type[kind] if param.is_array else by_type[kind][0]
            print('Next run reuses returned UUIDs; no new uploads.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc)
        for name in ('API_KEY', 'ATLAS_TEST_KEY'):
            if os.environ.get(name):
                message = message.replace(os.environ[name], '[redacted]')
        print('LIVE VALIDATION FAILED:', type(exc).__name__, message)
        response = getattr(exc, 'response', None)
        if response is not None:
            print('HTTP status:', response.status_code)
            detail = response.text[:1500]
            for name in ('API_KEY', 'ATLAS_TEST_KEY'):
                if os.environ.get(name):
                    detail = detail.replace(os.environ[name], '[redacted]')
            print('Server detail:', detail)
        raise SystemExit(1)
