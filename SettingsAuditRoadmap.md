# Settings audit — roadmap

## Goal
Every visible preference has a working, accurately described effect. Custom
output folders receive copies; Job History keeps its own durable originals.

## Phases

### Phase 1 — Audit and preferences
- **Deliverables:** Connected notifications/logging, honest cleanup and storage labels.

**Implementation checklist**
- [x] Trace every `AtlasAddonPreferences` property and storage action to its consumer.
- [x] Connect notification toggles and verbose logging in `atlas/operators.py` and `atlas/preferences.py`.
- [x] Correct manual cleanup and warning threshold labels; preserve unfinished jobs during cleanup.

**Tests / verification checklist**
- [x] Exercise preference toggles, cleanup boundaries and logging configuration.

### Phase 2 — Output copies
- **Deliverables:** Per-run copy destinations with effective path displayed in preferences.

**Implementation checklist**
- [x] Capture the destination when a run starts and persist it on `JobRecord`.
- [x] Copy downloaded results after durable history persistence, and report copy failures.
- [x] Document settings behavior and manual acceptance checks.

**Tests / verification checklist**
- [x] Verify blank/custom/relative paths, concurrent run destinations and failed/interrupted copies.
- [x] Run regression checks in Blender 4.0.2 and 5.1 (30 each) and parser/transport tests (12), 2026-09-30.

## Audit findings and consumers

| Preference | Consumer / verified behavior |
| --- | --- |
| Workspace API Key | `get_workspace_api_key` → API client; environment fallback. |
| Request Timeout | `get_effective_timeout` → API client; zero disables timeout. |
| No Limit | Same helper; disables timeout and the timeout UI field. |
| Poll Interval | Worker poll loop. |
| Output Copy Folder | Captured at submission → `JobRecord.OutputCopyFolder` → `export_output_copies`. Formerly unused. |
| Auto-Import Meshes | `_process_import_plan`, single mesh results only. |
| Auto-Apply Images | `_process_import_plan`, single raster results only. |
| Storage Warning | `check_storage_limit`, warning threshold; no hard cap. |
| Warn | Run submission warning report. |
| Manual Cleanup Age | Cleanup dialog default; renamed from misleading Auto-Cleanup. |
| Notify on Complete | Completion reports. Formerly unused. Run/Jobs now keeps persistent new-result markers independently. |
| Notify on Error | Error reports; validation errors remain visible. Formerly unused. New-result markers remain available when muted. |
| Verbose Logging | Atlas-only logger configuration/update, registration and run startup. Formerly unused. |

Storage actions also checked: manual age cleanup, clear finished history, and
temporary cache cleanup. Finished-job deletion is constrained to managed job
folders and never deletes optional output copies. No visible preference remains
without a runtime consumer. Installed-UI acceptance remains in SET-01–12.

## Out of scope
- Automatic deletion schedules, migrating old jobs, and converting packaging to Blender Extensions.
