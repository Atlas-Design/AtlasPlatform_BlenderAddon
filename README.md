# Atlas Blender Addon

Run Atlas generative workflows directly inside Blender.

The addon adds an **Atlas** tab to Blender's 3D View sidebar. From there you can load an Atlas workflow JSON, choose Blender scene assets or files as inputs, run the workflow, and bring generated images, meshes, and text back into your scene.

## Status

This plugin is ready for internal testing and demos. Treat public distribution as early access until a clean install and workflow validation pass has been completed.

## Features

- Load Atlas workflow JSON files from disk.
- Configure workflow inputs inside Blender, including booleans, numbers, text, images, and meshes.
- Use image and mesh inputs from the current scene or from local files.
- Run Atlas Platform API v0.2 workflows with workspace API key authentication.
- Track running jobs without freezing Blender.
- Review completed jobs in the history panel.
- Import generated meshes, preview generated images on aspect-ratio planes, apply generated images as materials, and copy generated text.

## Requirements

| Requirement | Notes |
| --- | --- |
| Blender | Blender 4.0 or newer |
| Atlas Platform access | A workflow JSON and workspace API key are required for API v0.2 workflows |
| Python `requests` | Must be available in Blender's Python environment |
| Network access | The addon calls the Atlas Platform API over HTTPS |

## Installation

1. Download or clone this repository.
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Click **Install...** and choose the addon package folder or zip.
4. Enable **Atlas Workflow Integration**.
5. Open the 3D View sidebar with `N`, then select the **Atlas** tab.

If Blender reports that `requests` is missing, install it into Blender's bundled Python. On Windows, the command usually looks like:

```powershell
"C:\Program Files\Blender Foundation\Blender 4.0\4.0\python\bin\python.exe" -m ensurepip
"C:\Program Files\Blender Foundation\Blender 4.0\4.0\python\bin\python.exe" -m pip install requests
```

Adjust the path for your Blender version and install location.

## Quick Start

1. Create a workspace API key in Atlas, then either:
   - paste it into **Edit > Preferences > Add-ons > Atlas Workflow Integration > API Settings**, or
   - set it as the `API_KEY` environment variable before launching Blender.
2. In Blender, open the **Atlas** tab in the 3D View sidebar.
3. Click the import button in **Atlas Workflow Library** and select a workflow JSON.
4. Fill in the workflow inputs.
5. Click **Run <WorkflowName>**.
6. Open **Jobs History** to review outputs.

## Workflow JSON Files

Workflow JSON files describe the Atlas API endpoint, input controls, and expected outputs. The addon does not ship user workflows in its runtime library. Use **Atlas Workflow Library > Import** to load workflow JSON files supplied by your team.

Example workflow files live in `examples/`. They are templates only; replace placeholder `api_id` values with real Atlas workflow API IDs before running them.

Supported input and output types are `boolean`, `number`, `string`, `image`, and `mesh`. API v0.2 workflows require `version`, `api_id`, `base_url`, `name`, `inputs`, and `outputs`.

## Data Stored Locally

The addon creates local folders while you work:

- `atlas_workflows/` stores workflows saved to the local library.
- `atlas_jobs/` stores job history and downloaded outputs.
- System temp folders named `atlas_workflow_*` hold temporary upload/download files.

These folders are intentionally ignored by Git.

## Troubleshooting

| Symptom | Try this |
| --- | --- |
| API v0.2 workflow will not start | Confirm the workspace API key is set in addon preferences or `API_KEY`. |
| `requests` is missing | Install `requests` into Blender's Python environment. |
| Image output is not visible | Use the image **View** action; it creates a textured preview plane and switches supported viewports to Material Preview. |
| Apply image does nothing | Select a mesh object first, then click **Apply**. |
| Workflow JSON will not load | Confirm it includes `version`, `api_id`, `base_url`, `name`, `inputs`, and `outputs`. |

## Repository Layout

- `__init__.py` is the Blender addon entrypoint and intentionally stays at the repository root.
- `atlas/` contains the runtime implementation modules.
- `examples/` contains workflow JSON templates.
- `icons/` contains optional custom icon assets used by `atlas/custom_icons.py`.
- `atlas_workflows/`, `atlas_jobs/`, `docs/`, and `ROADMAP.md` are local-only and ignored by Git.

## License

See `LICENSE`.
