# Expanded API type support — analysis and roadmap

## Goal

Allow Blender users to run workflows containing every type in the supplied
all-types export, while reserving native Blender actions for types where they
add useful functionality. Recognizing a type, transferring its files, and
importing/editing it in Blender are separate capabilities.

All five phases are implemented locally. The native regression suite passes in
Blender 4.0.2 and 5.1. Live validation against the supplied development workflow
confirmed all 21 outputs and a second run using returned asset UUIDs. A final
run verified corrected upload MIME and downloaded file extensions. The gap
analysis below describes the `a6f67ee` baseline, before these changes.

## Evidence and current gaps

Analysis date: 2026-09-29. Plugin baseline: `a6f67ee`.

Implementation validation on 2026-09-29:

- 27 Blender regression checks pass independently on 4.0.2 and 5.1.
- 12 parser/transport checks pass, including asset objects, credential handling,
  explicit multipart MIME and byte-signature correction of stale MIME headers.
- Three live executions of the supplied development workflow completed: initial
  transfer, UUID reuse without another upload, and confirmation of the MIME fix.
  Each execution returned all 21 output parameters, including file arrays.
- This development deployment returns raw UUIDs rather than asset objects.
  Object responses remain covered by local fixtures. Cross-workspace negative
  authorization cases have not been exercised with another workspace's assets.
- No credentials were written to source, fixtures, reports or addon preferences.
- Native scene packaging, USDZ texture persistence across reopening, rig motion,
  media timing/overlap, SVG importer availability, and AVIF fallback are tested.

- Sample: `M:/P4-PLUGINS/EXPORTED-APIS/Atllas-Test-FrontendAPI-AllTypes_v001.json`.
  It contains 15 inputs and 21 outputs. Four fields are arrays: images and
  meshes in both directions. It contains no `required` fields and no FBX output.
- Running the current `WorkflowDefinition.from_dict` on that sample fails at
  `inputs[4]`: unsupported type `audio`. The parser only knows `boolean`,
  `number`, `string`, `image`, and `mesh`.
- `isArray` is ignored, so an image/mesh list would incorrectly become a scalar
  even if the other unsupported types were removed.
- `OutputParamDef.format` is parsed but not carried through Blender state or
  `WorkflowOutputResult`. Downloads assume `.png` for images and `.glb` for
  meshes. Job history stores one file path per parameter and no remote asset ID.
- Binary defaults are ignored. There is no distinction between providing a
  value and omitting a field to use the server's default.
- The local backend checkout was inspected as supporting evidence, not as
  proof of the deployed API. Its HEAD is `632e3c4e8`, dated 2026-09-15.
  `backend/src/v2/api_creation/api_execution.py:gather_api_outputs` returns
  primitive values, scalar file IDs, or lists of file IDs. The user's subsequent
  contract clarification supersedes this checkout as the implementation target:
  file outputs are asset objects containing canonical `fid`, an authenticated
  download URL, and metadata including MIME, filename and byte size. Treat the
  checkout's raw-ID shape as a compatibility case, not the current contract.
- That checkout's `_create_api_summary_dict` does not emit `required`, matching
  the sample. The user clarified that node inputs default to required; optional
  omitted inputs use the node's default, and the actual OpenAPI/schema export
  includes a required list. Apply schema optionality rules to that schema, but
  do not assume this custom summary is the same representation. It currently
  carries neither that list nor per-input required flags.
- `agent_context` is an asset reference, not inline JSON. Requests send its
  UUID, including when chaining a previous result. The stored file contains
  serialized context and can reference additional conversation assets. The
  clarification describes both asset-object file outputs and UUID context
  outputs; a response fixture should resolve whether context is an exception
  to the general output wrapper. Its asset-reference semantics are settled.
- The checkout's file-type map and API node list contain no FBX output type.
  Its map also contains `zipfile`, which is not in the sample; this does not
  establish an exported ZIP node contract. Confirm either with a real export
  before adding a dedicated adapter.
- For mesh input, the local runtime's MIME validation expects the canonical
  GLB media type. The summary's broad OBJ/PLY claim is insufficient to enable
  direct uploads of those formats. Normalize through Blender or confirm the
  deployed contract first.

## Recommended support matrix

"Transfer" means upload/download, preserve format, store in history, reveal on
disk, and reuse an authorized asset ID. "Native" means an explicit Blender
action such as import, image preview, or adding a media strip.

| Exported type | Direction in sample | Relevance and recommended scope |
| --- | --- | --- |
| `boolean`, `number`, `string` | Both | Keep native controls. Add supplied/omitted state; preserve false, zero and empty text as real values. |
| `image` | Both | Core. Keep scene-image/file input and image preview/material actions. Preserve returned encoding instead of assuming PNG. |
| `image` + `isArray` | Both | Core. Ordered image/file/asset rows, multi-file selection, add/remove/reorder, per-item result actions. Useful for multi-view references and texture batches. Do not interpret every list as UDIMs or frames. |
| `mesh` | Both | Core. Keep GLB as the tested interchange format. Optional OBJ/PLY ingestion should import/convert to a self-contained GLB, after confirming actual backend support. |
| `mesh` + `isArray` | Both | Core. Ordered object/file/asset list. Export each row as a separate GLB; importing each output into its own collection is useful. Do not merge a list into a single scene asset. |
| `jpeg`, `webp`, `tga`, `tiff` | Output | High value, modest incremental work. Route through the raster-image UI while retaining the exact wire type and encoding. |
| `avif` | Output | Transfer immediately. Enable image actions only on tested builds with decoder support; keep download available elsewhere. Blender 5.1 documents AVIF, but the add-on promises Blender 4.0+. |
| `exr` | Both | High value for HDR lighting and compositing. File/asset transfer first; native float-preserving image export/load next. Single-layer image, multilayer render, and environment-map use are distinct operations. Do not run EXR through the PNG helper. |
| `usdz` | Both | Useful interchange. File/asset support first, then explicit USD import/export with preserved texture dependencies. Blender's USD support covers a subset of the format. |
| `scene` (`blend`) | Both | High Blender relevance. File/asset transfer first. Later offer a deliberate scene snapshot and append selected collections from results. Opening a complete result scene should be explicit, preferably in another Blender session. |
| `rig_animation` (`glb`) | Both | High relevance but more native complexity. Initially upload an animation GLB or reuse an asset, then import the resulting rig/clip. Later support armature + bound meshes + selected actions/range export. Retargeting is a separate feature. |
| `audio`, `video` | Both | Useful for animation/reference/sequence workflows. File transfer first; optional Add to Sequencer later, with explicit frame/channel choices. Do not add a renderer or transcoder merely to accept these types. |
| `svg` | Output | Useful for logos and curve-based geometry. Save/reveal first; optional Import as Curves where an importer exists. Blender's documented SVG importer handles path geometry, not complete browser-style SVG rendering. |
| `pdf` | Both | Secondary to Blender editing, but relevant to mixed workflows and reference documents. Upload/download/reveal or open externally. No embedded PDF editor or renderer recommended. |
| `agent_context` (`atlas-context.json`) | Both | Valuable for iterative agent workflows, especially alongside scene files. Send a UUID, never inline context JSON. Preserve the versioned context file and reuse its asset ID; keep linked asset references intact. Optional read-only message view later; it is neither a prompt string nor a request to execute recorded tools. |
| FBX (summary only) | Not present | Defer platform-specific mapping until a real export and response fixture establish its type/format. Blender's FBX capabilities alone do not establish Atlas support. |

## Implementation design

1. **Retain the wire contract.** Store raw type, format, `isArray`, optional
   required metadata, and whether a default was present. A small capability
   registry can map types to primitive/raster/mesh/scene/media/context/file
   families and supported input sources/actions. Keep transport separate from
   Blender adapters; do not duplicate upload/download code for each type.
2. **Normalize asset results at one boundary.** Target asset objects containing
   `fid`, download URL and metadata, with ordered asset objects for array
   outputs. Exact URL/metadata keys and array envelope need a response fixture.
   Keep raw UUID outputs as a narrow legacy compatibility case. Normalize both
   into one internal asset record; preserve the canonical ID, metadata and API
   origin in history. Download through the supplied URL using workspace auth;
   constrain credential forwarding to trusted API/download origins, including
   redirects. Chained inputs send only `fid` or an ordered list of IDs, never
   the whole output object. Keep workspace authorization on the server; do not
   promise that IDs work across environments/workspaces.
3. **Use files as the common fallback for known binary types.** File selection
   and authorized existing assets should work even without a native importer.
   Blender Data is an additional source only where an adapter exists. Unknown
   future types remain visible with an explanation; do not guess that every
   unknown type is a file or silently omit an unsupported input.
4. **Separate omission from values.** Offer an explicit Use server default/omit
   choice. An empty array, false, zero, and empty text must not automatically
   mean omitted. Required inputs must be supplied even when a default is shown;
   omission invokes the default only for optional inputs. Read requiredness
   from per-input metadata when supplied. The existing workflow JSON remains
   sufficient; no OpenAPI file or schema integration is required. Missing
   requiredness remains unknown and validation is left to Atlas. Do not label
   all inputs optional merely because the summary omitted metadata.
5. **Preserve file identity.** Use download metadata (validated MIME/filename)
   and the declared format to select an extension; never convert just by
   renaming. Generate local filenames from a safe parameter key and list index,
   retaining compound extensions such as `.atlas-context.json`. Stream large
   downloads to partial files and finalize atomically. Keep existing job-owned
   temporary storage and workflow isolation.
6. **Represent arrays explicitly.** Use an ordered Blender collection of input
   entries and ordered output items. Persist index, file ID, local path, format
   and per-item status. Preserve duplicates and server-returned order. Empty
   lists are valid where the contract permits them. A list of mesh files is not
   the same thing as one GLB containing several objects.
7. **Evolve history compatibly.** Extend `ParamSnapshot` with optional metadata
   and item records. Continue reading legacy scalar `FilePath` jobs. Avoid
   automatically loading/packing every asset in large output arrays; offer
   per-item actions and a deliberate batch import.
8. **Respect native semantics.** EXR retains float data and color-space intent;
   scene snapshots account for external textures/caches and unsaved changes;
   rig export includes dependencies. These are not all variants of static mesh
   export. Native `.blend` loading must not automatically replace the current
   scene or enable execution of embedded scripts.

## Assumptions and open questions

- Maintain the current Blender 4.0+ claim unless a separate version decision is
  made. Capability checks must cover importer/decoder availability, not merely
  the plugin recognizing a type string.
- Treat API role checks as server-owned. The supplied export has no role or
  permission metadata; do not hardcode UI access from the pasted node summary.
- Validate against a completed live status response containing scalar, array
  and context outputs before release. The implementation accepts `fid`,
  `download_url`/`url`, `mime`/`content_type`, `filename`, and `size_bytes`/`size`,
  with metadata at the top level or under `metadata`. Arrays are ordered lists.
  UUID strings remain supported, including context. These shapes are covered
  by local fixtures. The development endpoint tested on 2026-09-29 returns
  legacy UUID strings, including context and arrays; this path was verified live.
  Asset-object responses remain covered by fixtures until that deployment
  returns them. Live test executions used synthetic assets and the supplied key.
- Required/default behavior is confirmed. Missing requiredness is validated
  by the server. Array limits, supported mesh encodings and FBX availability
  remain deployment-specific follow-ups.
- Context asset reuse retains attachment references within its authorized
  workspace. Downloading the context JSON alone does not establish that its
  linked attachments are bundled for offline or cross-workspace use.
- Verify whether scene outputs are self-contained and which Blender version
  creates them. Full-scene compatibility and external caches are not guaranteed
  by a `.blend` extension.
- For animation, confirm which actions, frame ranges and rig conventions the
  workflow expects. Do not imply arbitrary character retargeting.
- A user-facing asset browser requires its own supported listing contract.
  Existing-asset ID input and reuse from job history can work without one.

## Out of scope

- Changes to the Atlas backend, API permissions, or deployment.
- A full chat client, PDF editor, video editor, transcoding service, or retargeter.
- Automatically opening returned scenes, generating renders for uploads, or
  executing instructions stored inside conversation files.
- Blind compatibility with undocumented future parameter/response types.

## Phases

### Phase 1 — Preserve and validate the exported schema

- **Deliverables:** Load the supplied export accurately and show actionable
  capability information for every field.

**Implementation checklist**

- [x] Extend `workflow_definition.py` with raw types, array metadata, optional
  required metadata, default-presence information, and retained output format.
- [x] Respect explicit per-input required flags; retain unknown when absent,
  leaving validation to Atlas without adding an OpenAPI dependency.
- [x] Add a compact type/capability registry and propagate metadata through
  `atlas_workflow_state.py` and the job-owned `WorkflowOutputResult`.
- [x] Add supplied/omitted input state; preserve false, zero, empty text and lists.
- [x] Create a sanitized all-types fixture with a placeholder API ID/origin.

**Tests / verification checklist**

- [x] Parse all 15 inputs and 21 outputs; identify the four array parameters.
- [x] Legacy five-type exports retain current behavior.
- [x] Requiredness from per-input flags validates correctly;
  missing metadata in the custom summary remains unknown.
- [x] A required input with a displayed default is still supplied; omission of
  an optional input leaves fallback selection to the server.
- [x] Unknown types remain visible and never produce a guessed payload.

### Phase 2 — General file transfer, arrays, and history

- **Deliverables:** Run the known file types through a common transfer layer,
  including ordered arrays and reuse of prior assets.

**Implementation checklist**

- [x] Extend `operators.py` upload planning for file, existing asset, and existing
  Blender sources; build arrays of file IDs instead of scalar replacements.
- [x] Normalize asset-object scalar/list outputs and legacy raw UUIDs in
  `api_client.py`; stream downloads from authenticated supplied URLs and retain
  MIME/filename/byte-size metadata using conventional fields covered by local
  fixtures. Live response verification remains pending.
- [x] Add ordered item records and optional asset metadata to `ParamSnapshot`
  in `job_manager.py`, preserving old scalar job history.
- [x] Add list editing, per-item progress/results, file reveal and compatible
  Use as Input actions in `ui_panel.py` and associated operators.

**Tests / verification checklist**

- [x] Scalar/list upload and download fixtures produce correct payload shapes,
  preserve order/duplicates, and distinguish omission from empty arrays.
- [x] Asset objects and supported legacy UUID responses normalize consistently;
  chaining sends UUIDs only. Context inputs never send inline JSON.
- [x] Authenticated downloads do not forward the workspace key to an untrusted
  origin or redirect destination.
- [x] Every known binary type reaches disk with the correct format, including
  compound extensions; files remain available without native Blender decoding.
- [x] Partial download failures preserve successful files and identify the
  failed item. Existing assets are not re-uploaded.
- [x] Legacy history, concurrent runs and workflow switching remain correct.
- [ ] Missing/cross-workspace asset IDs surface server errors clearly.

### Phase 3 — Core Blender images and meshes

- **Deliverables:** Native actions for the high-value raster/mesh families,
  image/mesh arrays, and controlled EXR support.

**Implementation checklist**

- [x] Map JPEG/WebP/TGA/TIFF and supported AVIF outputs to image actions while
  preserving the original API type and downloaded bytes.
- [x] Add float-preserving single-layer EXR input export and output loading.
  Keep multilayer EXR as unchanged file transfer until explicitly supported.
- [x] Export one selected object per mesh-array row; add per-item and explicit
  batch import actions without conflating arrays with multi-object scenes.
- [x] Enable native actions only where the installed Blender has the capability.

**Tests / verification checklist**

- [x] JPEG/WebP/TGA/TIFF/AVIF fixtures load and pack in Blender 5.1.
- [x] Verify AVIF's version-gated file-only fallback on Blender 4.0.2.
- [x] EXR values above 1.0 and alpha survive a round trip without PNG conversion
  or display-transform baking.
- [x] Array exports preserve order and object selection; batch imports create
  separate collections and output history retains per-item records.
- [x] Exercise Blender 4.0.2 and Blender 5.1; retain the
  existing regression suite.

### Phase 4 — Scene, USDZ and animation adapters

- **Deliverables:** Deliberate native actions for complete scenes and richer 3D
  assets, built on the file support already available in Phase 2.

**Implementation checklist**

- [x] `native_assets.py`: add a scene snapshot operation with a stated dependency policy and an
  explicit append/open-result choice that preserves the current project.
- [x] Add USDZ import/export with texture extraction into durable job storage.
- [x] Add rig/action-aware GLB export and explicit animation import; keep
  retargeting out of this adapter.
- [x] Allow scene/context output pairs to be selected as the next run's inputs.

**Tests / verification checklist**

- [x] Scene snapshot/append tests preserve the current file and selected data;
  missing external dependencies are reported.
- [x] USDZ textures remain available after temporary cleanup and Blender restart.
- [x] A rigged animation fixture retains skinning, clip/range and expected motion.
- [x] Context files round-trip unchanged and are never executed as commands.

### Phase 5 — Optional media conveniences

- **Deliverables:** Small host actions justified by user workflows, without
  delaying general type compatibility.

**Implementation checklist**

- [x] `native_assets.py` and `ui_panel.py`: add audio/video to the Sequencer at an explicit frame/channel when supported.
- [x] Offer SVG curve import only with a compatible installed importer; keep a
  file fallback for unsupported SVG constructs.
- [x] Optionally add a read-only conversation viewer; keep PDFs as files.

**Tests / verification checklist**

- [x] Media insertion respects timing/channel choices and survives job cleanup.
- [x] Missing codecs/importers retain usable downloaded files and explain why
  native actions are unavailable.
- [x] SVG fixtures demonstrate the supported path subset; no claim of complete
  SVG rendering. Conversation viewing causes no tool execution or scene changes.

## Recommended first release

Phases 1–3 supplied general file transfer and asset reuse. Phases 4–5 now add
scene snapshot/append, USDZ, active-action rig export/import, sequencer insertion,
SVG curves and a read-only context viewer. PDFs remain files. Detailed dependency
and format limits are documented in README.md.

## Sources

- User contract clarification in this task: asset-object file outputs,
  UUID-based context inputs/chaining, node required/default behavior, and
  required-list semantics for the actual schema export.
- Plugin: `atlas/workflow_definition.py`, `atlas/atlas_workflow_state.py`,
  `atlas/operators.py`, `atlas/api_client.py`, `atlas/job_manager.py`,
  `atlas/ui_panel.py`.
- Local backend (read only): `M:/Atlas/atlas_backend/backend/src/v2/api_creation/`
  (`api_creation.py`, `api_execution.py`, `file_types.py`),
  `M:/Atlas/atlas_backend/backend/src/v2/nodes/api.py`, and
  `M:/Atlas/atlas_backend/backend/src/v2/agent_context.py`.
- [Blender 5.1 image formats](https://docs.blender.org/manual/en/5.1/files/media/image_formats.html)
  — raster formats, AVIF and EXR precision.
- [Blender 4.0 USD documentation](https://docs.blender.org/manual/id/4.0/files/import_export/usd.html)
  — USDZ and texture-dependency handling.
- [Blender 4.5 Sequencer](https://docs.blender.org/manual/en/4.5/editors/video_sequencer/introduction.html)
  — images, video, sound and scenes on the timeline.
- [Blender 4.5 SVG importer](https://docs.blender.org/manual/es/4.5/addons/import_export/curve_svg.html)
  — path-geometry limitation.
