<p align="center">
  <img src="images/Banner.png" alt="Atlas Workflow Banner" width="900"/>
</p>

<h1 align="center">Atlas Workflow for Blender</h1>

<p align="center">
  <strong>Run Atlas Platform workflows inside Blender — no coding required</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Blender-4.0+-orange?logo=blender" alt="Blender 4.0+"/>
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License"/>
  <img src="https://img.shields.io/badge/Version-0.1.0-green" alt="Version 0.1.0"/>
  <img src="https://img.shields.io/badge/Status-Early%20Access-orange" alt="Status"/>
</p>

<p align="center">
  <a href="#what-this-is">What this is</a> •
  <a href="#atlas-workflow-panel">Workflow panel</a> •
  <a href="#jobs-history">Job history</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#settings">Settings</a> •
  <a href="#troubleshooting">Troubleshooting</a>
</p>

---

## What this is

**Atlas Workflow for Blender** connects Blender to **Atlas Platform**. You load a workflow JSON your team or Atlas provides, fill in the fields, press run, and get results back inside Blender.

The addon lives in Blender's 3D View sidebar under the **Atlas** tab. It handles file uploads, async execution, result downloads, and local job history so you can focus on creative iteration.

---

## What you can do

- **Run an Atlas workflow** from **3D View Sidebar (`N`) > Atlas**.
- **Use Blender scene data, files, or existing asset IDs** for image and mesh inputs, including ordered lists.
- **Transfer all file types in the all-types export**, including scenes, USDZ, animation, audio, video, PDF, SVG, and agent context.
- **Set primitive inputs** such as text prompts, numbers, and booleans.
- **Watch execution status and elapsed time** while the job runs without freezing Blender.
- **Review outputs later** in **Jobs History**.
- **Bring results into the scene** by importing generated meshes, previewing generated images on planes, applying generated images as materials, and copying generated text.
- **Atlas Platform API v0.2** support with workspace API key auth, async polling, and version-aware upload/download URLs.

> **Note:** You need an internet connection, a workspace API key for API v0.2+ workflows, and access to Atlas Platform. Import workflow JSON exported from Atlas Platform.

---

## Atlas Workflow Panel

**Location:** open the 3D View sidebar with `N`, then select the **Atlas** tab.

This is the main panel for one workflow at a time: pick what to run, fill in inputs, start execution, and open past results.

| Area | What it is for |
| --- | --- |
| **Atlas Workflow Library** | Load a workflow JSON, switch between saved workflows, save the active workflow to the local library, or remove a local workflow. |
| **Selected Workflow** | Shows the current workflow. Inputs are expanded by default; output preview is collapsed until you need it. |
| **Inputs** | Text, number and boolean controls; file or asset-ID inputs; ordered asset lists. Images, EXR and meshes also accept Blender data. |
| **Expected Outputs** | Names and types the workflow can return. View actual results for each run in Job History. |
| **Run button** | Starts the selected workflow with the current inputs. The button label includes the workflow name. |

<p align="center">
  <img src="images/Blender_Atlas_Tab.png" alt="Blender sidebar with the Atlas tab selected" width="900"/>
  <br/>
  <em>Atlas tab in Blender's 3D View sidebar.</em>
</p>

<p align="center">
  <img src="images/Workflow_Loaded.png" alt="Atlas Workflow Library and compact selected workflow panel" width="445"/>
  <br/>
  <em>Workflow loaded and ready to run.</em>
</p>

<p align="center">
  <img src="images/Workflow_Inputs.png" alt="Workflow inputs for image, mesh, number, boolean, and text" width="418"/>
  <br/>
  <em>Type-aware input controls for files, scene data, and primitive values.</em>
</p>

### Typical flow

1. Click the import button in **Atlas Workflow Library**.
2. Choose a workflow JSON exported from Atlas Platform.
3. Select scene objects or files for image and mesh inputs.
4. Fill in text, number, and boolean inputs.
5. Click **Run [Workflow Name]**.
6. Click **View Results** on the completion notice or the job's history row.

Every running job has a **View in Job History** button. It selects that exact run,
even after you switch workflows. Expand Job History's standard Blender header
if the panel is collapsed. Completion notices stay in the library panel
until dismissed (up to five recent notices per session); dismissing a notice keeps
the job and results. Finishing another run does not change the job you are viewing.

<p align="center">
  <img src="images/Workflow_Running.png" alt="Running job progress in the Atlas sidebar" width="453"/>
  <br/>
  <em>Earlier UI shown. Running Jobs now shows execution phase and elapsed time without a percentage bar.</em>
</p>

---

## Jobs History

**Location:** **3D View Sidebar (`N`) > Atlas > Job History**.

Job History is where you review current and past workflow runs. Its default position
is above Selected Workflow, and you can reorder it using Blender's standard panel
header. It has a compact list view and a detail view. Per-run links clear list
filters and select that job's outputs; expand the panel if collapsed. Workflow inputs remain
available; completion never opens or switches history automatically.

| Area | What it is for |
| --- | --- |
| **History list** | Browse previous jobs with status and relative time. |
| **Job detail** | Inspect one job. Outputs are shown first; inputs are collapsed by default to save vertical space. |
| **Output actions** | View or apply image outputs, import mesh outputs, copy number/text outputs, and open full text in a dialog. |
| **Open Folder** | Opens the local job folder containing `job.json`, inputs, and downloaded outputs. |

<p align="center">
  <img src="images/Job_History_List.png" alt="Jobs History list in the Atlas Blender addon" width="633"/>
  <br/>
  <em>History list for completed, failed, and running jobs.</em>
</p>

<p align="center">
  <img src="images/Job_History_Detail.png" alt="Completed job detail with outputs first" width="397"/>
  <br/>
  <em>Job detail prioritizes outputs, with inputs collapsed by default.</em>
</p>

### Working with outputs

- **Image > View** creates a plane with the same aspect ratio as the image, assigns a texture material, and switches supported viewports to Material Preview.
- **Image > Apply** creates a new material from the image and assigns it to the selected object.
- **Mesh > Import** imports the generated GLB into the scene.
- **Text > View** opens the full generated text in a dialog.
- **Copy** actions copy text or primitive values to the clipboard.
- **Use as Input** sends an output's asset ID to a compatible input of the selected workflow, without downloading and uploading it again. For arrays, **Use All as Input** appends the IDs in order.
- **Array outputs** offer actions for each item. **Import All Meshes** imports each asset into its own collection. Arrays stay on disk until explicitly opened; scalar auto-import preferences do not load entire arrays.
- **Other file outputs** remain available in the job folder, with asset IDs and metadata in history. If one download fails, successful files are retained and the failed item is identified.

<p align="center">
  <img src="images/Image_Output_Actions.png" alt="Image output actions and preview plane in Blender" width="409"/>
  <br/>
  <em>Image outputs can be previewed as planes or applied as materials.</em>
</p>

<p align="center">
  <img src="images/Mesh_Output_Imported.png" alt="Generated mesh imported into Blender" width="484"/>
  <br/>
  <em>Generated mesh imported into the Blender scene.</em>
</p>

<p align="center">
  <img src="images/Text_Output_Dialog.png" alt="Full generated text output dialog" width="700"/>
  <br/>
  <em>Full text outputs open in a compact dialog with copy support.</em>
</p>

---

## Requirements

| Requirement | Version / notes |
| --- | --- |
| **Blender** | 4.0 or newer |
| **Atlas Platform** | Access to workflows exported from your workspace |
| **Workspace API key** | Required for API v0.2+ workflows. Create one in Atlas **Workspace settings > API Keys**. |
| **Python HTTP dependencies** | Bundled with the addon |
| **Network access** | The addon calls Atlas Platform over HTTPS |

---

## Installation

1. Download `AtlasPlatform_BlenderAddon.zip` from the [latest GitHub release](https://github.com/Atlas-Design/AtlasPlatform_BlenderAddon/releases/latest/download/AtlasPlatform_BlenderAddon.zip).
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Click **Install...** and select `AtlasPlatform_BlenderAddon.zip`.
4. Enable **Atlas Workflow Integration**.
5. Open the 3D View sidebar with `N`, then select the **Atlas** tab.

The addon bundles its Python HTTP dependencies, so no separate `pip install` step is required for normal use.

### Packaging a release zip for maintainers

From the addon root on Windows, run:

```powershell
scripts\package_release.bat v0.1.0
```

The script creates `dist\AtlasPlatform_BlenderAddon.zip`, a clean Blender-installable package with bundled dependencies and portable zip paths. Keep this filename for Blender installs, upload it as the GitHub release asset, and use the GitHub release tag for the version. Test that exact zip in Blender before publishing the release.

---

## Quick Start

#### Step 1: Configure your API key

Open **Edit > Preferences > Add-ons > Atlas Workflow Integration** and set:

- **Workspace API Key** — your Atlas workspace key (`atk_...`), from **Workspace settings > API Keys** on the platform.
- Or leave the field empty and set `API_KEY` before launching Blender.

API v0.2+ workflow runs fail immediately if no key is configured.

<p align="center">
  <img src="images/Addon_Preferences.png" alt="Atlas Workflow Integration addon preferences in Blender" width="900"/>
  <br/>
  <em>Addon preferences for API key, timeout, polling, output behavior, and storage.</em>
</p>

#### Step 2: Open the Atlas tab

Open a 3D View, press `N`, and choose the **Atlas** tab.

#### Step 3: Import a workflow

1. Click the import button in **Atlas Workflow Library**.
2. Choose a workflow JSON exported from Atlas Platform.
3. The workflow appears in the library and the **Selected Workflow** panel.

<p align="center">
  <img src="images/Workflow_Import_FilePicker.png" alt="Selecting a workflow JSON file for import" width="419"/>
  <br/>
  <em>Import a workflow JSON exported from Atlas Platform.</em>
</p>

#### Step 4: Configure and run

1. Fill in inputs.
2. Click **Run [Workflow Name]**.
3. Wait for the job to complete.
4. Open **Jobs History** and use output actions to bring results into your scene.

---

## Settings

Open **Edit > Preferences > Add-ons > Atlas Workflow Integration**.

| Setting | Default | Description |
| --- | --- | --- |
| **Workspace API Key** | Empty | Bearer token for Atlas Platform (`atk_...`). Required for API v0.2+ workflows. |
| **Request Timeout** | 300 seconds | Per-request HTTP timeout. Set to `0` or enable no limit for long requests. |
| **Poll Interval** | 2 seconds | How often the addon checks async job status. |
| **Output Copy Folder** | Empty | Optional extra file copies in a unique folder per run. Job History always retains originals. The effective destination is shown below the field. |
| **Auto-Import Meshes** | Off | Import single mesh outputs into the current scene; arrays stay manual. |
| **Auto-Apply Images** | Off | Apply single raster outputs to the object active at completion; arrays stay manual. |
| **Storage Warning** | 500 MB | Warning threshold for local job history storage, not a hard cap. `0` disables it. |
| **Warn** | On | Report an exceeded storage threshold when starting a run. |
| **Manual Cleanup Age** | 0 | Starting age for the Clean Old Jobs dialog; `0` uses 30 days. Nothing is deleted automatically. |
| **Notifications** | On | Independently enable completion/error reports and sidebar notices. Validation errors and job history remain available when muted. |
| **Verbose Logging** | Off | Extra console output for troubleshooting. |

The former **Default Output Path** setting is now **Output Copy Folder**. A custom
folder is captured when the run starts, so changing it affects subsequent runs.
Copies use `<folder>/<workflow>/<timestamp>_<job-id>/`; **Open Output Copies** in
the job details opens that location. Blank means no extra copies. `//` paths are
relative to a saved `.blend`. Invalid/unwritable destinations fail before the API
run; later copy failures are recorded while the original results stay in history.
Existing files are never overwritten by the copy step. Primitive values stay in
`job.json`; the optional folder receives file outputs only.

**Clean Old Jobs** and **Clear Finished Jobs** delete finished history records
and their stored files after confirmation. They preserve queued/running jobs and
exported copies. Storage usage counts Job History, not the extra copies.

Keys are sent as `Authorization: Bearer <key>` on upload, execute, status, and download requests.

---

## Workflow JSON Files

Workflow JSON files describe the Atlas API endpoint, input controls, and expected outputs. In normal use, your team or Atlas provides these files.

Example workflow templates live in `examples/`. Replace placeholder `api_id` values with real Atlas workflow API IDs before running them.

Supported types:

| Type | Blender UI | Output behavior |
| --- | --- | --- |
| `boolean` | Checkbox | Shows Yes/No and stores value in job history. |
| `number` | Number field | Shows numeric value and copy action. |
| `string` | Text field | Shows preview, full-text dialog, and copy action. |
| `image` | Scene image or local image file | Downloads image output, supports View and Apply. |
| `mesh` | Scene object or local GLB/GLTF file | Downloads GLB output and supports Import. |
| `jpeg`, `webp`, `tga`, `tiff`, `avif` | File or asset ID | Retains encoding; supports raster View and Apply. AVIF actions require Blender 5.1+. |
| `exr` | Blender image, file or asset ID | Single-layer Blender image export preserves linear float values and alpha; downloaded images support View and Apply. Multilayer EXR is supported as unchanged file transfer. |
| `scene` | Current scene snapshot, file or asset ID | Append a chosen collection or open the result in a separate Blender process. |
| `usdz` | Root object and descendants, file or asset ID | Import with textures extracted beside the result in durable job storage. |
| `rig_animation` | Armature with active action and frame range, file or asset ID | Export bound meshes and skinning; import returned GLB rigs and clips. |
| `audio`, `video` | File or asset ID | Add to the Sequencer with an explicit frame and channel. |
| `svg` | File or asset ID | Import path geometry as curves when the SVG importer is available. |
| `agent_context` | File or asset ID | Read-only, paginated JSON view; linked attachments stay references. |
| `pdf` | File or asset ID | Save, reveal and reuse the asset. |

Every file input accepts an **Existing Asset** UUID. `agent_context` is a stored file asset: provide its UUID or upload its file, never inline conversation JSON. File outputs accept objects containing `fid`, a download URL and metadata; legacy UUID responses also work. The plugin sends only UUIDs when chaining results.

Inputs marked `isArray` expose **Add Item**, **Add Files**, remove and reorder controls. Image and mesh lists can mix Blender data, files and existing asset IDs; each mesh row exports a separate GLB. Empty lists and duplicate IDs retain their meaning.

The **Provide value** checkbox controls omission. Disabling it leaves the field out of the request; Atlas applies optional defaults or returns a required-input error. Explicit per-input `required` flags are respected. When the workflow export omits that metadata, the plugin leaves validation to Atlas. No OpenAPI file is needed.

Downloads preserve the returned format and stream to disk. Workspace credentials are restricted to the configured API origin; foreign download URLs use the canonical asset-ID endpoint, and cross-origin redirects are rejected.

Native behavior is checked in Blender 4.0.2 and 5.1. Unknown future types remain visible; unsupported inputs must be omitted only when the workflow allows it.

The supplied all-types development workflow was also verified live, including all 21 output parameters and a subsequent run using returned UUIDs. That deployment returns legacy UUID strings; asset-object response support is covered by local fixtures. Uploads include explicit MIME types, and recognized file signatures correct stale download MIME labels.

### Scenes, animation and media

- **Scene snapshot:** copies the current scene, including unsaved image edits, and packs its dependencies in an isolated background Blender process. The active file, selection and images stay unchanged. Linked libraries must first be made local. Missing files and dependencies Blender cannot pack, such as external caches or video strips, produce an error; use a prepared scene file for those workflows. Snapshot packaging can take longer for large scenes.
- **Scene results:** **Append Collection** adds the collection you choose to the current scene. **Open in New Blender** opens another process with automatic scripts disabled. Scene compatibility still depends on the Blender version that created the file.
- **USDZ:** choose a root object; its descendants are exported with textures. Imported textures are copied to a unique folder beside the downloaded asset, so they survive temporary-file cleanup. Support is limited to Blender's USD capabilities.
- **Animation:** select an armature, assign the desired action in Blender, and set the start/end frames. The addon includes meshes bound through Armature modifiers and exports the active actions of that selection. NLA tracks on the armature are temporarily muted, then restored. This is an interchange operation; it does not retarget rigs.
- **Audio/video:** **Add to Sequencer** asks for a start frame and channel. An overlapping clip is rejected so existing strips stay in place. Video adds a movie strip; add audio separately. Supported decoding depends on the Blender build. Keep the job's files while the sequence uses them.
- **SVG:** **Import Curves** handles the installed SVG importer's supported path geometry, not full browser rendering. When the importer is unavailable, the downloaded file remains usable.
- **Context:** **View Context** displays JSON up to 4 MiB as read-only pages. It never executes stored instructions or fetches linked attachments. Scene and context results can each be reused as inputs for the next run.

API v0.2 workflows require `version`, `api_id`, `base_url`, `name`, `inputs`, and `outputs`.

---

## Data Stored Locally

The addon creates local folders while you work:

```text
atlas_workflows/      Saved local workflow library
atlas_jobs/           Job history, job.json files, inputs, outputs
atlas_workflow_*      Temporary upload/download folders in the system temp directory
```

These folders are local user data and are intentionally ignored by Git.

---

## Repository Layout

Release validation steps, manual cases and expected results are in
[TESTING_GUIDE.md](TESTING_GUIDE.md). Automated commands are summarized in
[tests/README.md](tests/README.md).

```text
AtlasPlatform_BlenderAddon/
  __init__.py          Blender addon entrypoint
  atlas/               Runtime implementation modules
  examples/            Sanitized workflow JSON templates
  icons/               Custom icon assets
  README.md
  LICENSE
```

Runtime implementation modules are intentionally grouped under `atlas/`; `__init__.py` stays at the repository root because Blender uses it as the addon entrypoint.

---

## Troubleshooting

### Authentication

#### API key required / run blocked before it starts

**Possible causes:**

- No API key in addon preferences.
- API v0.2+ workflow but empty key field and no `API_KEY` environment variable.

**Solutions:**

1. Set **Workspace API Key** in addon preferences, or set `API_KEY` before launching Blender.
2. Create a new key in Atlas **Workspace settings > API Keys**.
3. Confirm the workflow JSON belongs to the same workspace as the key.

#### HTTP 401 or 403

**Possible causes:**

- Invalid or revoked API key.
- Workflow JSON from a workspace your key cannot access.

**Solutions:**

1. Re-copy the key from Atlas.
2. Re-import a workflow JSON exported from your workspace.
3. Ask your team to confirm workspace access.

### Common issues

| Problem | What to try |
| --- | --- |
| HTTP client import fails | Reinstall the addon from a complete release zip so the bundled `vendor/` folder is included. |
| Workflow JSON will not load | Confirm it includes the required fields and supported parameter types. |
| Input file is missing | Re-select the image or mesh file in the input row. |
| Image output is not visible | Use **View**; it creates a textured plane and switches supported viewports to Material Preview. |
| Apply image does nothing | Select an object with material slots, then click **Apply** again. |
| Mesh did not import | Confirm the output file exists in the job folder and is GLB/GLTF. |
| Job history looks stale | Click refresh in **Jobs History** or rerun the workflow. |

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE).

---

<p align="center">
  <strong>Built by the Atlas team</strong>
</p>
