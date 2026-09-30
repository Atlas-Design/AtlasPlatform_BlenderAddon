# Atlas Blender addon — release testing guide

Prepared 2026-09-29 for the expanded API types and native Blender adapters.

## 1. What is left

The five planned implementation phases are complete. This is **not yet a release sign-off**. The remaining work is to test the installable package through Blender's actual UI, exercise realistic assets and failures, fix any defects found, then commit and package the approved version.

| Area | Evidence already obtained | Remaining release work |
| --- | --- | --- |
| Parser and HTTP transport | 12 automated checks passed | Rerun against the final source revision after fixes. |
| Blender behavior | 27 checks passed independently in Blender 4.0.2 and 5.1 | Interactive dialogs, file pickers, appearance, undo, realistic projects, and the installed ZIP. |
| Live API | Three executions of the supplied dev workflow returned all 21 output parameters; one run reused returned UUIDs without uploading again | A run through the installed addon's UI; explicit optional/default cases; denied/missing asset cases. |
| File formats | Live testing found and fixed missing upload MIME and incorrect download extensions | Inspect actual output content and native actions in the final candidate. |
| Asset-object responses | Local fixtures cover objects with `fid`, URLs and metadata | Verify against a deployment or controlled test endpoint that actually returns this shape. The tested dev endpoint returned legacy UUID strings. |
| Credentials and redirects | Mock tests cover credential scope and cross-origin redirect rejection | Confirm messages and logs remain usable without exposing credentials in the installed build. |
| Package and upgrade | Source layout registered in automated Blender tests | Build/install the exact ZIP; restart; disable/re-enable; upgrade with existing history and library. |
| Delivery | Changes currently exist locally | Review fixes, choose/update release version, commit locally, build final ZIP and approve release. |

The API update validation covered **39 distinct automated checks**: 27 Blender
checks on two versions, plus 12 parser/transport checks. The results UX update
added four base regressions; all **22 base checks** passed on Blender 4.0.2 and
5.1. The settings audit adds eight further base checks for a total of 30. The
native suite now inherits these 30 and contains 39 checks in total. All 30 base
checks passed on both Blender versions on 2026-09-30, and all 12 parser/transport
checks passed again after the settings changes.
Running both Blender scripts repeats the base checks. Rerun the full suites on
the final release candidate.

All manual cases below are **unexecuted acceptance criteria** unless a result is recorded for a particular candidate. Automated coverage does not mark the corresponding manual case passed.

## 2. Test order and recording rules

Run in this order:

1. Prepare fixtures and record the candidate revision.
2. Run automated checks.
3. Build and install the candidate ZIP in isolated Blender profiles.
4. Complete the all-types UI smoke run and output inspection.
5. Exercise each native adapter and asset reuse.
6. Test history, concurrent jobs, failures, permissions and realistic load.
7. Retest fixes, rebuild if necessary, and sign off the **exact ZIP** that was tested.

Use `PASS`, `FAIL`, `BLOCKED`, or `N/A` for every case. A missing second workspace or unavailable object-response deployment is `BLOCKED`, not `PASS`. Use `N/A` only with a reason and a stated support limitation.

For every result record: case ID, date, tester, Blender version/build, candidate ZIP SHA-256, workflow/environment, fixture, steps that differed from this guide, result, and evidence. Keep workflow/job IDs in the internal test record; remove credentials and signed URLs from shared evidence.

Severity for triage:

| Severity | Examples | Release decision |
| --- | --- | --- |
| Blocker | Credentials disclosed; original project overwritten; another job's files deleted; Blender crashes on a normal path | Stop release and fix. |
| Major | A supported type cannot upload/download/import; incorrect file contents; broken chaining; lost results after restart | Fix before release or explicitly remove/narrow that support claim. |
| Minor | Misleading label, clipped dialog text, awkward layout, nonessential notification issue | Record and prioritize; accept only with an explicit decision. |

Do not silently turn a failed case into a limitation. Record the failure first, then make a release decision.

## 3. Prepare the environment

Use a disposable test project and a dedicated Blender configuration for each version. Keep working production projects closed during upgrade/removal tests. The addon stores `atlas_jobs` and `atlas_workflows` under its installed addon directory; copy those directories before replacing an existing installation used for comparison.

Required materials:

- Blender 4.0.2 and Blender 5.1. Test additional Blender/OS versions separately before claiming them verified.
- The candidate ZIP built from this source tree.
- A workspace API key authorized for the supplied dev workflow.
- A second workflow with clearly different input/output labels for concurrent-run tests.
- A small server-side test workflow with explicitly required and optional inputs, including optional defaults. Editing the local JSON alone does not change server requiredness.
- For authorization tests, an authorized test owner who can provide an asset from a different workspace that the first key cannot access.
- For object-response tests, a compatible deployment or a controlled local test server. No OpenAPI file is needed by the addon.

PowerShell setup:

```powershell
$repo = 'M:\P4-PLUGINS\BlenderPlugin\Platform_BlenderAddon'
$blender51 = 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe'
$blender40 = Join-Path $env:TEMP 'atlas-blender-validation\blender-4.0.2-windows-x64\blender.exe'
$python = 'C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\bin\python.exe'
$workflow = 'M:\P4-PLUGINS\EXPORTED-APIS\Atllas-Test-FrontendAPI-AllTypes_v001.json'
$qaRoot = 'M:\P4-PLUGINS\Blender-QA\all-types-candidate'
New-Item -ItemType Directory -Force -Path $qaRoot | Out-Null
Set-Location -LiteralPath $repo
git status --short
git rev-parse HEAD
Test-Path -LiteralPath $blender40
```

The portable 4.0.2 path is temporary validation storage from the previous checks. If it has been removed, set `$blender40` to your own 4.0.2 installation. A Git commit hash alone does not identify this uncommitted candidate; retain its diff and ZIP hash too.

### Generate fixtures for each version

```powershell
$fixtures40 = Join-Path $qaRoot 'fixtures-4.0'
$fixtures51 = Join-Path $qaRoot 'fixtures-5.1'
& $blender40 --background --factory-startup --disable-autoexec --python-exit-code 1 --python "$repo\tests\create_live_fixtures.py" -- $fixtures40
if ($LASTEXITCODE -ne 0) { throw 'Blender 4.0 fixture generation failed' }
& $blender51 --background --factory-startup --disable-autoexec --python-exit-code 1 --python "$repo\tests\create_live_fixtures.py" -- $fixtures51
if ($LASTEXITCODE -ne 0) { throw 'Blender 5.1 fixture generation failed' }
```

Each directory should contain `mesh.glb`, `animation.glb`, `scene.usdz`, `scene.blend`, `image.png`, `image.exr`, `audio.wav`, `video.mp4`, `reference.pdf`, and `conversation.atlas-context.json`. Helper scratch files should be gone.

Generate version-specific `.blend` fixtures. Do not treat Blender 4.0 failing to read a Blender 5.1-created file as proof that the addon's Blender 4.0 adapter is broken.

The generated audio is silence, the PDF is blank, the image is a solid color, and the video is a short still-image clip. They validate format plumbing. Also prepare:

- Two visibly distinct images, including one nonsquare image with alpha and one HDR image with values above 1.
- A cube and sphere with different names, materials and transforms; an unrelated selected object.
- A textured parent/child hierarchy and a realistic USDZ with texture dependencies.
- A skinned rig with a known active action, NLA track, and a nondefault frame range.
- Audible audio and a moving video for playback checks.
- An SVG with paths and a separate SVG containing unsupported constructs such as text/filters.
- A small scene with nested collections, packed images and unsaved edits; a separate scene with a missing image, linked library or external cache.
- A long Unicode context file with attachment references, an invalid JSON file, and a context file larger than 4 MiB.

## 4. Automated baseline

Run from `$repo`:

```powershell
& $python -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Parser/transport tests failed' }
& $blender40 --background --factory-startup --python-exit-code 1 --python "$repo\tests\blender_native_regressions.py"
if ($LASTEXITCODE -ne 0) { throw 'Blender 4.0 tests failed' }
& $blender51 --background --factory-startup --python-exit-code 1 --python "$repo\tests\blender_native_regressions.py"
if ($LASTEXITCODE -ne 0) { throw 'Blender 5.1 tests failed' }
git diff --check
```

Expected: 12 parser/transport tests and 27 Blender tests in each version, all `OK`, with successful exit codes. Some negative tests deliberately produce error-level Blender reports. Judge the test result and exit code rather than failing a log simply because it contains the word `Error`.

These tests use isolated temporary files and simulated transport. They do not install the release ZIP or verify an interactive popup. The explicit live script in section 17 makes real API calls.

## 5. Package, install and upgrade

Build a local QA candidate; this command does not publish anything:

```powershell
& "$repo\scripts\package_release.bat" qa-all-types
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
$candidate = Join-Path $repo 'dist\AtlasPlatform_BlenderAddon.zip'
Get-FileHash -LiteralPath $candidate -Algorithm SHA256
```

The packaging script needs `python` on PATH. If necessary, put the directory containing `$python` on PATH for this shell. It replaces the previous ZIP at `$candidate`; retain a separate copy when comparing candidates. The argument identifies staging; it does **not** update the addon's `bl_info` version. Choose and update the actual version before final release.

For a dedicated interactive profile, set version-specific directories in a separate PowerShell window before launching Blender:

```powershell
$env:BLENDER_USER_CONFIG = Join-Path $qaRoot 'profile-5.1\config'
$env:BLENDER_USER_SCRIPTS = Join-Path $qaRoot 'profile-5.1\scripts'
New-Item -ItemType Directory -Force -Path $env:BLENDER_USER_CONFIG, $env:BLENDER_USER_SCRIPTS | Out-Null
& $blender51
```

Use `profile-4.0` and `$blender40` for the other version. Close this dedicated shell afterward so subsequent launches do not accidentally reuse the test profile.

Install the ZIP through **Edit > Preferences > Add-ons**, using **Install…** or **Install from Disk…**, depending on the Blender version. Enable **Atlas Workflow Integration**. Open **3D View > N sidebar > Atlas**.

| ID | Procedure | Expected result |
| --- | --- | --- |
| PKG-01 | Inspect the ZIP before installing. | One installable addon root; `__init__.py`, runtime modules including `asset_types.py` and `native_assets.py`, bundled HTTP dependencies, and required icon assets present. No credentials or user job/library data. |
| PKG-02 | Install in a clean 4.0 profile, then a clean 5.1 profile. | Enable succeeds without traceback or a separate pip installation; Atlas panels appear once. |
| PKG-03 | Verify the installed module location, rather than relying only on the displayed version. In Blender's Python Console, list `[(m.__name__, m.__file__) for m in __import__('addon_utils').modules() if m.bl_info.get('name') == 'Atlas Workflow Integration']`. | Exactly the intended candidate installation is enabled. Source-directory imports or a second old copy do not invalidate the test unnoticed. |
| PKG-04 | Disable/re-enable twice; close and restart Blender. | No duplicate panels/classes, stale timers or registration errors. Preferences load as expected. |
| PKG-05 | Configure preferences, run one job, save one workflow, restart. | Key masking works; jobs and saved workflow remain accessible. Unsaved input edits need not survive restart. |
| PKG-06 | In a disposable profile containing old job/library copies, install the candidate over the older addon using the normal upgrade procedure. | Old scalar history remains readable, files remain available and the library is preserved. Record any required migration/backup procedure. |
| PKG-07 | Repeat a smoke run with a standard Windows account and a path containing spaces/non-ASCII characters. | No admin requirement for normal addon use; paths and file pickers work. |
| PKG-08 | Reduce sidebar width and increase UI scale. Open every new dialog. | Controls remain reachable, labels explain the action, scrolling works and no traceback appears while drawing panels. |

## 6. Workflow loading and primitive inputs

Import the supplied workflow JSON. Expect **15 inputs and 21 output parameters**, with image/mesh arrays in both directions. An array is one parameter even when it contains multiple assets.

| ID | Procedure | Expected result |
| --- | --- | --- |
| WF-01 | Import the all-types export without an OpenAPI file. Expand Inputs and Expected Outputs. | Loads successfully; all fields are present; the four array parameters are identified. |
| WF-02 | Save to Library, switch to another workflow and back, rename a disposable saved copy, restart and reload it. | The selected workflow identity and schema remain correct. Renaming/deleting a library copy does not alter the original exported file. |
| WF-03 | Import an original five-type example with a valid API ID. | Existing boolean/number/string/image/mesh behavior remains usable. |
| WF-04 | Try malformed JSON, a missing required top-level field, duplicate input IDs, and `"isArray": "false"` in separate disposable export copies. | Load fails clearly; no partially misleading input form is left ready to execute. Record whether the prior workflow is retained or cleared. |
| WF-05 | Add a made-up input type to a local copy. Load it, first with Provide value enabled, then disabled. Do not submit this altered copy to production. | Type stays visible; providing it produces an unsupported-type error. Omission is allowed locally but is still subject to server validation. |
| WF-06 | Enter `false`, `0`, `-12.5`, and empty text in suitable inputs. | Actual values are supplied; none silently becomes omission. Verify using an echo workflow or request capture, not just the widgets. |
| WF-07 | Enter Unicode and multiline text; try the largest number your intended workflow needs. | Supported values survive request and history accurately. Report truncation/precision limits rather than assuming unlimited numeric precision. |
| WF-08 | On a server workflow with optional input/default, disable Provide value and run. | Request omits the key; the server's configured default is used. |
| WF-09 | On a server-required input, omit the value. Test both explicit local `required: true` and an export missing that metadata. | Explicit local requiredness blocks locally; missing metadata leaves validation to the server, whose error is visible. A displayed default does not make a required input optional. |
| WF-10 | Compare an empty array, `false`, `0`, empty text and omitted input on a controlled workflow. | These remain distinct. Required means the key must be supplied; any minimum array length is separately server-defined. |

## 7. First complete run through the installed UI

Use the fixture directory for the Blender version being tested. Initially select **File** for every file input; leave **Provide value** enabled. Keep automatic mesh import and image application off for this baseline.

| Export input | Value/source |
| --- | --- |
| `number_input` | `42` |
| `boolean_input` | Enabled/true |
| `text_input` | `Atlas Blender manual QA` |
| `mesh_input` | File: `mesh.glb` |
| `audio_input` | File: `audio.wav` |
| `scene_input` | File: `scene.blend` |
| `video_input` | File: `video.mp4` |
| `meshes_input` | Add Files: two entries; duplicates are permitted. Later replace these with visibly distinct meshes. |
| `images_input` | Add Files: two entries; later use distinct colors to verify order. |
| `pdf_input` | File: `reference.pdf` |
| `usdz_input` | File: `scene.usdz` |
| `conversation_input` | File: `conversation.atlas-context.json` |
| `image_input` | File: `image.png` |
| `exr_input` | File: `image.exr` |
| `animation_input` | File: `animation.glb` |

1. Save the test `.blend` and note its filename, active object and selected objects.
2. Click **Run [workflow name]** once.
3. Observe upload, waiting/running, download and completion states. File preparation/export can pause the UI; network waiting should allow normal interaction.
4. Open the completed job in **Jobs History**, expand inputs, inspect outputs and use **Open Folder**.
5. Confirm `job.json` and durable output files exist. Do not use a transient `atlas_workflow_*` directory as the final result location.
6. Compare the result to the workflow's actual graph behavior. The all-types graph can return configured/default assets for some outputs; it is not guaranteed to echo every input byte-for-byte.

| ID | Acceptance criterion |
| --- | --- |
| RUN-01 | One click creates one run with the correct workflow identity and input snapshot. |
| RUN-02 | The run completes without traceback; history includes all 21 expected output parameters. |
| RUN-03 | Primitive types and values match graph behavior; output arrays preserve returned order and duplicates. |
| RUN-04 | File extensions agree with the actual encoding; GLB/PDF/USDZ/video/EXR bytes are not mislabeled PNG. |
| RUN-05 | Every successful file remains accessible after refresh, switching workflows and clearing unused addon temporary files. |
| RUN-06 | No scene, rig, USDZ, media clip or SVG is automatically imported simply because it was returned. Their native actions are explicit. |

### Inspect every output

For all file outputs, check the folder action, file existence/size, asset-ID copy and compatible reuse. Inspect content, not just the extension. These formats are those declared by this sample; concrete returned metadata/bytes may legitimately select another compatible encoding.

| Output parameter | Expected format/type | Additional action to verify |
| --- | --- | --- |
| `number_output` | Number | Display/copy value; compare to graph. |
| `boolean_output` | Boolean | Correct Yes/No display. |
| `text_output` | String | Full-text View and Copy, including Unicode. |
| `image_output` | PNG/image | View plane and Apply material. |
| `jpeg_output` | JPEG | Decodes, correct dimensions and colors. |
| `webp_output` | WebP | Decodes; alpha where present. |
| `tga_output` | TGA | Decodes; image is not flipped unexpectedly. |
| `tiff_output` | TIFF | Decodes; dimensions/channels preserved. |
| `avif_output` | AVIF | View/Apply in 5.1; file/reuse fallback in 4.0. |
| `exr_output` | EXR | Float/HDR image, not an 8-bit PNG conversion. |
| `mesh_output` | GLB | Import correct geometry/materials. |
| `meshes_output` | List of GLBs | Per-item Import and Import All Meshes. |
| `images_output` | List of images | Per-item View/Apply; no automatic loading of the entire array. |
| `audio_output` | Audio, MP3 in sample | Decode/play via Sequencer. |
| `video_output` | Video, MP4 in sample | Add video strip and play frames. |
| `scene_output` | `.blend` | Choose a collection to append; separately test Open in New Blender. |
| `usdz_output` | USDZ | Native import with durable textures. |
| `animation_output` | GLB rig/animation | Skinning, action and motion after import. |
| `pdf_output` | PDF | Open externally from folder and inspect a page; no embedded PDF editor is expected. |
| `svg_output` | SVG | Import supported paths as curves when importer is available. |
| `conversation_output` | `.atlas-context.json` | Read-only paged view and UUID reuse. |

## 8. File, scene-data and array controls

| ID | Procedure | Expected result |
| --- | --- | --- |
| IN-01 | For each file type, select a file through the picker, then replace it. Cancel the picker once. | Selected path is correct; replacement affects only that input; cancel does not append or overwrite a value. |
| IN-02 | Use paths with spaces/Unicode and a `//` path relative to a saved test `.blend`. | The intended existing file is uploaded. An unsaved project must not silently resolve to an unrelated file. |
| IN-03 | Choose a missing file or delete a fixture after selection. | Run fails clearly for the affected input; no apparently successful result is created. |
| IN-04 | Select an image datablock with unsaved pixel edits, then run image input from Scene. | Export reflects current edits; original image filepath, packing and render settings are unchanged. |
| IN-05 | Select object B as mesh input while object A is selected/active. Repeat from Edit Mode and with B hidden/selection-locked. | Only B is exported; prior selection, active object, mode and visibility are restored, including on failure. An excluded object gives an actionable error. |
| IN-06 | Change source File → Existing Asset → Scene → File. | Only the selected source is used; stale values in inactive controls do not override it. |
| ARR-01 | Add three distinct image rows. Move the last to first, remove the middle, add another. | Displayed order and submitted order match; the intended row is changed. |
| ARR-02 | Add multiple files in one picker operation; cancel a subsequent picker. | Exactly the accepted selections are added once. No blank/duplicate rows are added by cancellation. |
| ARR-03 | Replace the file in the middle row. | That row changes; no unintended append and no neighbor changes. |
| ARR-04 | Mix Scene, File and Existing Asset in one list. Include the same asset ID twice. | Only new scene/file data uploads; UUID entries are reused; order and duplicates survive. |
| ARR-05 | Repeat ARR-01 through ARR-04 with mesh rows. | Each scene object becomes a separate GLB. The list is not merged into one scene file. |
| ARR-06 | Submit an empty list to a workflow that accepts it, then omit the input entirely. | Empty list and omission remain different requests. |
| ARR-07 | View a large result list with auto-import preferences enabled. | The whole list is not eagerly imported/packed. Per-item actions affect the chosen item. |
| ARR-08 | Click Import All Meshes on three distinct outputs. | Three imports go into separate collections. Errors identify failed items while successful imports remain visible. |
| ARR-09 | Inspect array items at narrow and wide sidebar widths; switch each source. | Index, source selector and up/down/remove controls share the first row. File entries use one further row for the path and a single filtered browse button. First-up and last-down are disabled. |
| ARR-10 | Browse and manually edit paths for scalar and array file inputs, including a // path. | Exactly one browse button per path, with the correct file-type filter. Values remain editable and only the intended input changes. |

## 9. Asset reuse and response compatibility

| ID | Procedure | Expected result |
| --- | --- | --- |
| ASSET-01 | From a completed job, Use as Input on one file result; choose a compatible input and run. | Input changes to Existing Asset; submitted value is the UUID alone, not the whole output object or a local path. No upload occurs for that input. |
| ASSET-02 | Use All as Input for an array, with existing rows already present. | IDs append in returned order. Existing rows stay intact; duplicates are retained. |
| ASSET-03 | Try multiple results into a scalar input. | Clear rejection; no partial input mutation. Choose a list input or one result. |
| ASSET-04 | Reuse JPEG/WebP/EXR into generic image input; try an incompatible type. | Compatible raster-to-image choices appear; incompatible targets are not offered. |
| ASSET-05 | Switch workflow and reuse an old job's asset into a compatible input on the same API environment. | Works if the key is authorized. Workflow identity does not force unnecessary re-upload. |
| ASSET-06 | Reuse both scene and context outputs as the next run's respective inputs. | Both values are UUIDs; context JSON is not embedded in the execute payload. Attachment references remain intact. |
| ASSET-07 | Attempt reuse from an obviously different API base URL. | Clear environment mismatch; no upload/execute triggered by the reuse action. |
| ASSET-08 | Paste a random/nonexistent UUID, then an expired/deleted asset ID in a controlled workspace. | Server rejection is shown clearly; job is failed, not completed; unrelated saved outputs remain intact. |
| ASSET-09 | With workspace A's key, submit an asset owned by test workspace B without access. | Server denies it; the UI explains the failed request. Record the actual response. Do not treat same-origin URLs as proof of workspace authorization. |
| ASSET-10 | Empty Existing Asset field; then paste inline JSON into it. | Empty ID is rejected locally. Inline JSON must never become inline agent state; any invalid-ID request is rejected clearly. UUID format validation may remain server-owned. |
| RESP-01 | Verify scalar UUID and ordered UUID-array responses on the supplied dev endpoint. | Files download, IDs persist and reuse works. Already observed live; repeat through the candidate UI. |
| RESP-02 | On an object-response deployment, return `{fid, download_url, metadata}` for a scalar and ordered objects for an array. | Download succeeds; identity/metadata/order persist; chaining sends only IDs. Confirm actual deployed field names rather than silently adapting the fixture to the code. |
| RESP-03 | Controlled fixtures: missing `fid`, wrong metadata type, malformed byte size, non-array response for an array field, empty array. | Malformed assets get actionable failures; empty arrays remain valid where allowed; other successful files persist. |
| RESP-04 | Return an unknown future output type. | Raw result remains inspectable; no guessed binary download/import. |
| RESP-05 | Return a file with stale PNG MIME but a real GLB, EXR, PDF or MP4 signature; also test correct headers. | Recognized bytes determine the correct saved extension; the file contents are unchanged. |
| RESP-06 | Return filenames/parameter IDs containing separators or `..`. | Files remain inside the intended job directories and have safe local names. |

RESP-02 is still a deployment-level gap if your endpoint only returns UUIDs. The automated tests are useful evidence but do not certify an unobserved production wrapper.

## 10. Raster images, meshes and EXR

| ID | Procedure | Expected result |
| --- | --- | --- |
| IMG-01 | View a nonsquare result with alpha. | Plane aspect ratio matches; texture/alpha are correct; supported viewports switch to Material Preview. |
| IMG-02 | Apply to a selected object whose faces use its active material slot. Repeat with no material slots. | The visible material changes appropriately; a new slot is created where needed. |
| IMG-03 | Apply with no active object or an unsuitable active object. | Clear error; no unrelated object is altered. |
| IMG-04 | View/apply every raster row in the output matrix. | Correct decoding/colors/dimensions. Corrupt files fail clearly and remain available for inspection. |
| IMG-05 | Compare AVIF behavior between 4.0 and 5.1. | 4.0 explains the preview limitation but offers file/reuse actions; 5.1 offers working image actions. |
| EXR-01 | Upload from a float image containing values `4.0`, `2.0`, `0.5`, alpha `0.75`; inspect numerical values after round trip. | Values above 1 and alpha survive within reasonable export precision; visual appearance alone is not sufficient evidence. |
| EXR-02 | Change scene view transform, exposure and output format before EXR export. | Scene settings stay unchanged; EXR export does not bake the display transform. |
| EXR-03 | Transfer a multilayer EXR as File. | Downloaded file remains usable as a file; no claim of layer-aware native export/editing. |
| MESH-01 | Import GLB with UVs, texture/material assignments and known transforms. | Geometry, transforms and intended supported materials are intact. |
| MESH-02 | Import per-item and batch outputs; use Undo where offered. | Undo removes the intended import without harming existing objects; successful batch imports remain identifiable. |
| MESH-03 | Try malformed GLB and a `.gltf` requiring external sidecar files. | Errors are explicit. Single-file upload does not promise to bundle arbitrary external `.bin`/texture dependencies; use a self-contained GLB for the supported path. |

## 11. Scene snapshot and scene results

Prepare a disposable project with a recognizable object, two collections, a material image with unsaved edits, a nondefault frame, and a saved filename. Record the current selection, render settings and image filepath/packing state.

| ID | Procedure | Expected result |
| --- | --- | --- |
| SCENE-01 | Use Scene source for a `scene` input and run. | Snapshot includes current scene edits and referenced data; the user's active project is not saved over or renamed. |
| SCENE-02 | After snapshot preparation, compare original selection, frame, render settings, image pixels/filepath/packing and project filename. | Original state remains intact. Background packaging may take time, but must not silently modify the source project. |
| SCENE-03 | Open the result separately and inspect the material image that had unsaved edits. | Latest pixels are present; supported dependencies are packed; helper `.source.blend`, pixel files and scripts are not part of the final upload. |
| SCENE-04 | Repeat with a missing texture, linked library, then external simulation cache/video strip. | A clear packaging/dependency error, or a genuinely self-contained result for a packable case. An apparently successful scene with silently broken dependencies is a failure. |
| SCENE-05 | Choose Append Collection, select one of two named collections, confirm. | Only the chosen collection hierarchy and its dependencies are appended; current scene/file is preserved. |
| SCENE-06 | Cancel the collection chooser. Repeat append with duplicate collection names already in the scene. | Cancel changes nothing; name collisions are handled without overwriting existing data. |
| SCENE-07 | Use Open in New Blender. | A separate Blender process opens the result; original session stays open; automatic scripts are disabled for the new process. |
| SCENE-08 | Try a scene with no appendable collections, a corrupt `.blend`, and a file made by a newer unsupported Blender version. | Useful failure instead of replacing the project or reporting false success. Version incompatibility is recorded explicitly. |
| SCENE-09 | Save the receiving project, restart and inspect appended objects/materials. | Appended data and supported dependencies remain usable. |

Opening a complete scene and appending a collection are different actions. Neither test is satisfied merely by downloading a `.blend` file.

## 12. USDZ and rig animation

| ID | Procedure | Expected result |
| --- | --- | --- |
| USD-01 | Select a root with two descendants and an unrelated selected object; use Scene source for USDZ. | Export contains the root hierarchy, not the unrelated object. Selection/visibility/mode restore afterward. |
| USD-02 | Use textured geometry with supported materials. Import returned USDZ. | Geometry and textures are visible; textures are copied to a unique `textures_*` directory beside the durable result. |
| USD-03 | Import two USDZ files with identically named textures but different colors. | Each result retains its own textures; existing textures are not silently overwritten. |
| USD-04 | Clear addon temporary files; save/reopen receiving `.blend`; remove only a disposable copy of the source USDZ. | Imported textures still resolve from durable job storage. |
| USD-05 | Try missing root, excluded root, unavailable USD importer/exporter, corrupt USDZ and unsupported USD constructs. | Missing capabilities and failures are clear; downloaded files remain usable. Do not promise complete USD feature parity. |
| ANIM-01 | Assign a known action to a skinned armature, choose it as input, set frames 1–12 and export. | GLB includes armature, bound meshes, skin weights and animation; it is not just a static mesh. |
| ANIM-02 | Import the result and inspect first, middle and last frame. | Expected pose/motion and skin deformation; inspect numerical timing as well as playback. |
| ANIM-03 | Repeat with nondefault frame range/current frame and an NLA track. | Chosen export range is respected; original frame range/current frame and armature NLA mute states restore. |
| ANIM-04 | Test no armature, no active action, no bound mesh and reversed frame range separately. | Clear preflight errors; current scene state remains intact. |
| ANIM-05 | Use multiple bound meshes, an unrelated rig and nontrivial object transforms. | Intended rig/meshes are included; unrelated assets are excluded; supported transforms remain correct. |
| ANIM-06 | Try a representative production rig with constraints/actions, then compare motion to Blender. | Record any exporter limitations. This feature does not retarget rigs or guarantee every rig convention. |
| ANIM-07 | Import, save/reopen and Undo a separate import. | Animation remains playable after reopening; Undo affects the intended import. |

## 13. Audio, video, SVG, PDF and context

| ID | Procedure | Expected result |
| --- | --- | --- |
| MEDIA-01 | Add audible audio at frame 30, channel 3; inspect and play it. | Strip begins on the chosen frame/channel and decodes correctly. Silence fixture alone cannot verify audible playback. |
| MEDIA-02 | Add moving video at frame 50, channel 4. | Correct timing and visible frames. Video adds a movie strip; it does not automatically add a sound strip. |
| MEDIA-03 | Cancel the frame/channel dialog. | No strip or other scene modification. |
| MEDIA-04 | Add an overlapping clip on an occupied channel; then use an empty channel. | Overlap is rejected without moving/replacing existing strips; the empty-channel insertion succeeds. |
| MEDIA-05 | Save/reopen and clear temporary files. | Clips still reference durable job files and play. Deleting the job's source files is not expected to preserve playback. |
| MEDIA-06 | Try corrupt media, unavailable codec, a long clip and a nondefault scene frame rate. | Clear decoder error when unsupported; duration/synchronization are checked against expected scene timing. |
| MEDIA-07 | Undo an insertion and repeat in a scene already containing strips/metastrips. | Only the inserted clip is removed; existing sequence layout is not damaged. |
| SVG-01 | Import a simple path SVG using Import Curves. | Curves appear with expected shape and useful scale; no raster plane masquerades as a curve import. |
| SVG-02 | Disable/remove the compatible SVG importer in a disposable profile. | Import action is unavailable/explained; folder and asset reuse remain available. |
| SVG-03 | Import SVG containing text, filters or other unsupported features. | Compare with the source and record limitations. Full browser-equivalent rendering is not a support claim. |
| PDF-01 | Upload/download a PDF with visible content; open it from the job folder externally. | Readable PDF bytes and reusable asset ID. No native PDF editor is expected. |
| CTX-01 | View a valid context file with Unicode, multiple messages and long lines. Change pages, including an out-of-range page. | Read-only content is legible, navigation is stable, and the source file is unchanged. |
| CTX-02 | View a context containing attachment references and text that looks like instructions/tool calls. | References remain data; no instructions run, assets are not fetched automatically and the scene is unchanged. |
| CTX-03 | Try invalid JSON, missing file and a file larger than 4 MiB. | Clear error/file fallback; no hang or partial scene mutation. |
| CTX-04 | Close/cancel viewer and reopen another context. | No stale text from the previous file and no writes to either file. |
| CTX-05 | Reuse context into a subsequent API run with scene input. | Only its canonical UUID is submitted; linked asset references are preserved by the server contract. |

## 14. History, concurrency and settings

| ID | Procedure | Expected result |
| --- | --- | --- |
| HIST-01 | Inspect scalar, array, omitted-input, scene and animation job details. | Correct parameter identity, source, array order, scene name/frame range where recorded; omitted inputs are identified. |
| HIST-02 | Restart Blender and open a completed job. | Files and asset IDs remain accessible; native actions and reuse still work. |
| HIST-03 | Load copied history produced before this update. | Legacy scalar FilePath records remain readable; no invented reusable ID when old history lacks one. |
| HIST-04 | Delete one downloaded file from a disposable job. | Missing-file actions do not pretend to work; the rest of the job remains readable. Asset reuse can remain available when an ID exists. |
| HIST-05 | Refresh, enter/leave details, switch selected job and expand/collapse sections repeatedly. | Correct content stays associated with the selected job; no duplicated rows or drawing errors. |
| CON-01 | Start two runs with distinct text/objects, then change workflow before either finishes. | Results and IDs stay with their originating jobs; another workflow's output widgets are not overwritten. |
| CON-02 | While both runs are active, clear unused addon cache and manipulate the local library. | Active upload/download files survive; jobs finish independently. |
| CON-03 | Let one run fail while the other completes. | Failure cleanup does not delete successful/active files belonging to the other run. |
| CON-04 | Clear/unload the selected workflow while a run finishes. | Job-owned output definitions still allow correct durable history. |
| CON-05 | Close/reopen Blender while a controlled test run is active. | No project corruption. Record unfinished-job behavior; automatic remote cancellation, recovery or resumed polling is not implemented as a promised feature. |
| CON-06 | Exercise local operator cancellation through the automated cancellation test or an available developer test harness. | Files needed by the worker remain until it finishes; do not claim the remote execution was cancelled. There is no assumed dedicated Cancel button in this guide. |
| PREF-01 | Auto-import meshes off/on, using a scalar mesh and a mesh array. | Scalar behavior follows the preference; arrays still need explicit per-item/batch import. |
| PREF-02 | Auto-apply images off/on with an active object, then no active object. | Scalar preference works when applicable; no crash or unintended bulk application. |
| PREF-03 | Change request timeout and polling interval for a controlled slow endpoint. | Settings affect request timing as documented; no unbounded wait when a finite timeout should apply. |
| PREF-04 | Lower storage warning threshold, then exceed it with test jobs. | Warning is useful; a warning threshold is not treated as a guarantee that all storage is automatically cleaned. |
| PREF-05 | Exercise visible notification, output-path and cleanup settings used by your release. | Compare actual behavior with the UI/README. Record dormant or misleading options as defects; their presence alone is not evidence of support. |

## 15. Failures, authorization and transport

Use a controlled endpoint/mock or disposable workspace for fault injection. Do not manufacture destructive failures on a production workstation. The existing automated suite provides a repeatable starting point for stream/redirect failures.

| ID | Procedure | Expected result |
| --- | --- | --- |
| ERR-01 | Remove the configured key and ensure API_KEY is absent; attempt a v0.2 run. | Clear missing-key error before submission. Restore test configuration afterward. |
| ERR-02 | Use invalid/revoked key, then a valid key without required permission. | Authentication/authorization failure is visible; no success state or leaked credential. |
| ERR-03 | Use wrong API ID or wrong environment. | Clear server failure; previously saved history remains intact. |
| ERR-04 | Break connectivity during upload, polling and download in separate controlled runs. | Errors identify failure; active/other jobs remain intact; no complete-looking corrupt output is exposed. |
| ERR-05 | Have one file in an output array fail to download. | Successful siblings are saved; failed item is identified; ID remains available if known; job does not claim complete success. |
| ERR-06 | Interrupt a stream while a previous completed file already exists at its destination. | Previous file is not overwritten by partial data; `.part` is removed on handled failure. |
| ERR-07 | Make the test output directory unwritable or simulate disk-full in an isolated volume. | Save failure is clear; no silent successful job and no deletion of unrelated files. Preserve diagnostic evidence. |
| ERR-08 | Return HTTP 429/5xx and a workflow/node-level failure. | Useful failure/status and recovery by an explicit later run. Do not assume automatic retry, resume or deduplication. |
| ERR-09 | Return same-origin URL/redirect, foreign-origin URL, foreign-origin redirect, and redirect loop in controlled tests. | Same-origin authorized download succeeds; foreign URL uses the canonical ID endpoint; foreign redirects/loops fail without forwarding the workspace key. |
| ERR-10 | Inspect logs, copied errors, job JSON, test reports and package contents. | No raw API key or Authorization header is exposed. Treat job metadata/URLs as potentially sensitive when sharing evidence. |
| ERR-11 | Correct the cause of a failed run and execute again. | New run succeeds; prior failed run remains accurately identified; no duplicate automatic submission. |

When testing errors, separately record whether the failure originated in the plugin, Blender importer/codec, workflow graph, server authorization, or network. A server-declared unsupported input format is not fixed by renaming the file.

## 16. Realistic scale and compatibility

Start with small fixtures. Then use sizes representative of your team's real work rather than imposing an invented universal limit.

| ID | Procedure | Expected result |
| --- | --- | --- |
| SCALE-01 | Run lists with 1, 10, 50 and the largest practical number of assets your API accepts. | Order remains correct; UI is usable; memory does not grow simply from eagerly opening every output. Record actual time/memory. |
| SCALE-02 | Download a large image, scene and media file; observe Task Manager. | Streaming behavior; no avoidable full-response buffering; finite timeout/error behavior remains understandable. |
| SCALE-03 | Snapshot a realistic textured scene with dirty images. | Record packaging delay and peak memory. Original project remains intact. The snapshot helper's 180-second timeout is an explicit limit to evaluate for your workload. |
| SCALE-04 | Run repeated imports/reuse and two concurrent jobs over a longer session. | No escalating stale timers, orphaned active-job rows, runaway temporary storage or cross-job corruption. |
| SCALE-05 | Repeat essential cases on other claimed Blender versions and operating systems. | Record each environment separately. Testing 4.0.2 and 5.1 on Windows does not certify every intermediate release or macOS/Linux. |
| SCALE-06 | Upgrade/restart with a substantial old job library. | Acceptable history refresh time and backward-compatible records; opening one job does not mutate another. |

Record CPU/RAM, Blender version, asset sizes, list lengths, upload/download duration, export/import duration and subjective responsiveness. Establish release-specific thresholds from your expected workload; do not record a qualitative `fast enough` as a reproducible benchmark.

## 17. Optional scripted live rerun

This supplements the installed-UI test; it cannot replace it. It uploads synthetic files and executes the supplied live workflow. `--chain` runs it twice and can consume workflow credits.

Run in PowerShell after section 3 setup. Use a prompt so the key is not pasted into source or a command-history literal:

```powershell
$secureKey = Read-Host 'Atlas test workspace API key' -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:ATLAS_TEST_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    & $python "$repo\tests\live_api_smoke.py" --workflow $workflow --fixtures $fixtures51 --output "$qaRoot\live-script-results" --chain
    if ($LASTEXITCODE -ne 0) { throw 'Live API validation failed' }
} finally {
    Remove-Item Env:\ATLAS_TEST_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    Remove-Variable secureKey, keyPointer -ErrorAction SilentlyContinue
}
```

Expected:

- First run uploads ten synthetic file types and supplies the primitive values.
- All 21 output parameters are processed; array elements produce additional files/report rows.
- Second run reuses returned UUIDs without new uploads. The helper groups returned IDs by type, so second-run array lengths may differ from the first run; exact UI row preservation is tested separately in section 8.
- `report-run1.json` and `report-run2.json` contain structural evidence, not credentials, signed URLs, UUIDs or conversation text. Downloaded assets themselves can contain context and should be handled as test data.
- `.atlas-context.json` remains the full filename suffix even though a report's simple `Path.suffix` field is `.json`.

Limits of this helper: it does not click UI controls, test the installed ZIP, assert the meaning of every primitive value, verify all native imports, or test unauthorized workspaces. It uses a 60-second request timeout and five-minute polling deadline; a local polling timeout does not prove the server job stopped.

## 17a. Results discovery and execution status

These are interactive acceptance cases for the results UX update. Execute in both
Blender versions with a narrow and a widened sidebar. They remain unexecuted.

| ID | Steps | Expected |
| --- | --- | --- |
| UX-01 | Load a workflow; collapse and expand Expected Outputs before running it. | Preview describes names/types using labels; the note points to Job History even when collapsed. It has no result actions. |
| UX-02 | Start workflow A, switch to B and edit its inputs, then click A's View in Job History. Expand Job History if collapsed. | History selects A. B's input values and selection remain intact. |
| UX-03 | Close history and apply filters that exclude A; click A's running-job link, then expand the native panel header. | History shows A with Outputs expanded, Inputs collapsed and filters cleared. Native collapse state remains under user control. |
| UX-04 | Complete B while inspecting A's history detail. | A stays selected. A separate B completion notice offers View Results; no automatic navigation occurs. |
| UX-05 | Complete two runs of the same workflow out of order; click each notice and history action. | Each link opens its exact run and matching outputs, independent of list order or matching names. |
| UX-06 | Click View Results and use the relevant View, Import, Open or Save actions. | Actions are visible under the selected job's expanded Outputs and affect that job's files. |
| UX-07 | Dismiss a completion notice, refresh history, restart Blender. | Only the session notice disappears. The job and saved results remain accessible in history. |
| UX-08 | Observe a long upload, queued job, running job and download. | Activity icon, truthful phase and increasing elapsed time; no simulated percentage or repeating fill bar. Job details also show the current status. |
| UX-09 | Trigger a failed run and a partial download failure. | A Needs attention notice opens the failed job, error details and any saved partial results. |
| UX-10 | While editing B, let A finish with history collapsed. | B's controls stay available, history stays collapsed, and A's notice appears without stealing focus. |
| UX-11 | Finish more than five runs, then dismiss a notice. | At most five recent session notices; all jobs remain in history. Dismissing one does not dismiss the others. |
| UX-12 | Remove a test job folder externally, then click its old notice. | A clear unavailable-job warning; no unrelated job is opened. |
| UX-13 | Collapse, expand and drag Job History among the other Atlas panels. | Standard Blender header and panel appearance; normal drag reordering. No custom outer disclosure replaces the native header. |

## 17b. Settings audit

The 13 preferences were traced to their runtime consumers. Run these additional
interactive acceptance cases on the installed candidate; they are not marked passed
by the automated checks.

| ID | Steps | Expected |
| --- | --- | --- |
| SET-01 | Leave Output Copy Folder empty; run a workflow with file outputs. | Preferences shows the history destination. Results stay in history; no extra copies are produced. |
| SET-02 | Choose a writable custom folder; run scalar and array file outputs. | Copies match saved originals in a unique per-run folder. Open Output Copies opens that folder; history actions use originals. Primitive results remain in job.json. |
| SET-03 | Start A with folder X; change to Y and start B. Finish out of order. | A copies to X, B to Y, with distinct run folders. Changing the preference does not migrate existing files. |
| SET-04 | Try an unwritable folder, a path to a file, an ordinary relative path, and a // path in an unsaved blend. | Clear preflight error before remote execution. A // path works relative to a saved blend. Copy destinations inside history storage are rejected. |
| SET-05 | Make the copy destination unavailable after submission. | Saved originals and history remain usable. The job records the copy error; an error notice appears only when enabled. |
| SET-06 | Disable success notifications, then error notifications, and trigger the corresponding outcomes. | Each toggle independently controls completion reports and sidebar notices. History still shows outcomes; input validation errors are not hidden. |
| SET-07 | Toggle Verbose Logging on/off and restart with each setting saved. | Atlas debug messages appear only when enabled, with no duplicate handlers/messages. Other addons' logging is unaffected. Request payload contents are not logged. |
| SET-08 | Set a low Storage Warning threshold; toggle Warn; try zero. | A warning on submission only when enabled and exceeded. Runs are never blocked by this threshold; zero disables it. Export copies are outside usage totals. |
| SET-09 | Set Manual Cleanup Age without pressing Clean Old Jobs. Then open its dialog and cancel. | No automatic deletion. The dialog starts at the configured age, or 30 days for zero. Cancellation keeps all files. |
| SET-10 | Clean old test jobs, then Clear Finished Jobs, while another test run is active. | Only eligible finished history is deleted. Queued/running jobs and exported copies survive; history refreshes. |
| SET-11 | Toggle Auto-Import Meshes and Auto-Apply Images using a disposable scene. | Single mesh/raster outputs follow the switches; arrays remain manual. Image application targets the object active at completion. |
| SET-12 | Toggle No Limit and edit Request Timeout/Poll Interval. | Timeout field disables while No Limit is enabled; effective transport timeout and polling interval follow the settings. |

## 18. Failure report and final sign-off

Copy this for each defect:

```text
Case ID:
Severity:
Candidate ZIP SHA-256:
Git revision + dirty diff/reference:
Blender version/build / OS:
Workflow/environment:
Fixture(s), size and source type:
Exact steps:
Expected:
Actual:
Reproducibility:
Job status / internal job reference:
Console error (credentials and signed URLs removed):
Screenshot/video or sample output:
Workaround, if any:
Fix reference and retest result:
```

Release checklist:

- [ ] Candidate revision/diff and ZIP hash recorded.
- [ ] Automated suites pass after the last runtime change.
- [ ] Exact ZIP installs, restarts and upgrades successfully in the supported test profiles.
- [ ] Installed-UI all-types run passes; every output row inspected.
- [ ] File, Scene and Existing Asset sources plus mixed arrays exercised.
- [ ] Required/optional/default behavior verified against appropriate server graphs.
- [ ] Native scene, USDZ, animation, media, SVG and context cases pass or have explicit supported-scope decisions.
- [ ] History, restart, concurrency, partial failure and realistic-project checks pass.
- [ ] Missing/denied asset tests completed; otherwise marked blocked with an explicit release decision.
- [ ] Live asset-object contract verified where deployed; otherwise its fixture-only evidence and deployment gap are documented explicitly.
- [ ] No unresolved blockers/majors hidden as “testing later.”
- [ ] Version metadata and documentation match the final candidate.
- [ ] Local commit created when approved; final ZIP built from that revision and rechecked.
- [ ] Release publication approved separately; only the verified ZIP is distributed.

The immediate priority is **sections 5–7, then native dialogs/actions in 9–13**. Those cover the largest remaining difference between the checks already run and what a Blender user will actually experience.
