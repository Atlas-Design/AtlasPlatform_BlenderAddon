# Workflow experience — roadmap

## Goal
One native Atlas panel with Run and Jobs views, preserved per-workflow drafts,
explicit input reuse, non-destructive image previews, and identifiable runs.

## Assumptions
- Drafts survive workflow/view switches within the Blender session. Disk-backed
  history survives restarts; scene datablocks remain tied to their Blender file.
- Use These Inputs restores original uploaded asset IDs where captured. An
  explicit alternative restores scene/file references to their current contents.
- Result completion updates counts without switching views. Only user actions navigate.

## Phases

### Phase 1 — Drafts and navigation
- **Deliverables:** Run/Jobs views and per-workflow editable state.

**Implementation checklist**
- [x] Add draft serialization/restoration and view state in `atlas_workflow_state.py`.
- [x] Consolidate registered sidebar panels in `ui_panel.py` under a native Atlas header.
- [x] Keep active runs and completion counts visible in either view.

**Tests / verification checklist**
- [x] Switch workflows with primitives, mixed arrays, omitted inputs and changed definitions.
- [x] Verify explicit result navigation and no automatic switch on completion.

### Phase 2 — Useful history
- **Deliverables:** Run numbers, labels, precise timestamps, summaries and reviewed state.

**Implementation checklist**
- [x] Extend `JobRecord` with backward-compatible metadata and workflow snapshots.
- [x] Capture uploaded input IDs and restore inputs with explicit source semantics.
- [x] Add rename and review actions; replace library notification cards with Jobs indicators.

**Tests / verification checklist**
- [x] Restore historical inputs after switching workflow/environment and restarting metadata reads.
- [x] Verify arrays/omission/order and missing legacy data without substituting current scene silently.
- [x] Verify concurrent completion, labels, unseen counts and legacy records.

### Phase 3 — Preview and verification
- **Deliverables:** Image previews that do not create scene objects, explicit scene actions, updated docs.

**Implementation checklist**
- [x] Separate Preview, Add Image Plane and Apply to Material operators.
- [x] Add a compact result thumbnail on demand without eagerly loading all files.
- [x] Update README and installed-UI acceptance tests.

**Tests / verification checklist**
- [x] Verify preview leaves scene objects/materials unchanged and explicit plane creation works.
- [x] Run Blender regressions on 4.0.2 and 5.1 and relevant contract checks.
- [x] Validate actual native UI drawing where possible; record interactive checks still outstanding.

## Out of scope
- The optional dedicated review workspace discussed as a later enhancement.
- Publishing, replacing the user's installed addon, or migrating their history files.

## Verification evidence — 2026-09-30
- Checkpoint before this change: `1c8c2c6`.
- 43 native regressions pass independently on Blender 4.0.2 and 5.1; 12 parser/transport checks pass.
- Native GUI Run/Jobs/detail/preview captures produced no draw exceptions on both versions.
  Blender 4.0's harness temporarily uses the Item category because its RNA cannot
  select a sidebar tab; the production addon still uses Atlas. Narrow 4.0 sidebars
  truncate longer labels and can be widened using Blender's standard controls.
- Source-level testing uses synthetic local results. Installed ZIP, realistic assets,
  upgrade and full interactive acceptance remain in `TESTING_GUIDE.md`.
- Implementation remains local and uncommitted after the checkpoint; no installed addon replacement.
