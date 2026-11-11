# Run controls — roadmap

## Goal
Make run starts obvious, expose individual finished-run deletion, and provide an
honestly labelled local Stop Tracking action without claiming server cancellation.

## Assumptions
- Checkpoint: `f9c6c46`. Installation and publishing are outside this change.
- No verified exported-API cancellation contract is available in the client,
  Atlas tool descriptions or shared specifications. Remote cancellation remains unverified.
- Stop Tracking waits for an in-flight HTTP request to return, then prevents more
  uploads, submission, polling or downloads. Already downloaded files stay in history.
- Deleting a run removes local history and its files, not output copies or remote assets.

## Phase 1 — Start feedback and deletion
**Implementation checklist**
- [x] Add persistent run-start feedback beside Run in `atlas/ui_panel.py`.
- [x] Add ID-based deletion with confirmation and active-run guards in `atlas/operators.py`.
**Tests / verification checklist**
- [x] Verify exact-run deletion, active-job protection, preserved copies and drafts.
- [x] Inspect native Run and Jobs controls at normal sidebar width.

## Phase 2 — Stop tracking
**Implementation checklist**
- [x] Add cooperative per-run stop signals and an explicit local terminal status.
- [x] Expose Stop Tracking in Jobs with remote-execution and in-flight-request explanation.
- [x] Preserve partial results, submitted IDs and execution ID without auto-importing stopped results.
**Tests / verification checklist**
- [x] Stop during upload, polling and download; verify no later work and no cross-run interference.
- [x] Check completion races, wait feedback, final history state and cleanup.
- [x] Run native regressions on Blender 4.0.2 and 5.1 plus transport checks; update docs.

## Evidence — 2026-10-01
- 49 native regressions pass independently on Blender 4.0.2 and 5.1; 12 transport/parser tests pass.
- Blender 5.1 native captures verify the persistent start banner, list deletion,
  running detail and stop dialog; Blender 4.0 captures verify deletion controls
  and confirmation with the existing test-only Item-category fallback. No draw errors.
- Partial downloads follow Output Copy Folder settings; stopped results never auto-import.
- Real server cancellation is unverified and not implemented. Local stopping waits
  for an in-flight HTTP call; No Limit can therefore wait indefinitely. No resume UI.
- Source changes are uncommitted after the checkpoint. Installed-addon and release-ZIP
  acceptance remains separate; no real API executions were needed for this change.
