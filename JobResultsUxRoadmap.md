# Job results UX — roadmap

## Goal
Keep results attached to each run in Job History, explain Expected Outputs,
and provide explicit navigation without interrupting workflow editing.

## Phases

### Phase 1 — Discoverable results
- **Deliverables:** Expected Outputs labels, per-run history links and completion notices.

**Implementation checklist**
- [x] Update `atlas/ui_panel.py` preview and View Results actions. Restore the native history header per user feedback; expansion and reordering remain user-controlled.
- [x] Extend `ATLAS_OT_SelectJob` to resolve stable job IDs and preserve selection during refresh.
- [x] Add dismissible session completion notices without automatic navigation.

**Tests / verification checklist**
- [x] Verify navigation after workflow switching, history reordering and restrictive filters.
- [x] Verify concurrent completion preserves the selected history job and workflow inputs.

### Phase 2 — Honest execution status
- **Deliverables:** Phase and elapsed time without simulated percentages.

**Implementation checklist**
- [x] Set uploading/submitting/downloading phases in `ATLAS_OT_RunWorkflow`.
- [x] Replace the progress slider with an activity indicator and update user documentation.

**Tests / verification checklist**
- [x] Run Blender regression checks on 4.0.2 and 5.1, including phase transitions (22 passed each).
- [x] Add interactive acceptance cases for notification and history layout (`TESTING_GUIDE.md`, UX-01–12; not yet executed).

## Out of scope
- Changes to Atlas APIs, automatic navigation on completion, or results in the workflow preview.
