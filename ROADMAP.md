# Atlas Blender Plugin Roadmap

> **Goal**: Achieve workflow identity with the Unity/Unreal plugins while maintaining Blender-native UI/UX.

## Current State Analysis

### ✅ Already Implemented
- Workflow JSON parsing (`workflow_definition.py`)
- Workflow library management (save/load/delete/rename)
- Dynamic input UI generation (all types: bool, number, string, image, mesh)
- Custom type icons
- Basic job execution with progress indication
- Output handling (images, meshes, primitives)

### ❌ Needs Update/Implementation
- **API**: Still uses old synchronous `api_execute` endpoint (needs async + polling)
- **Job History**: No persistence or history viewing
- **Running Jobs Panel**: Currently inline, should be separate/conditional
- **Settings/Preferences**: No configurable settings
- **Error Handling**: No structured error display (node info)

---

## Phase Overview

| Phase | Description | Priority |
|-------|-------------|----------|
| **1** | API Migration (async + polling) | Critical |
| **2** | Job Persistence & Data Model | Critical |
| **3** | Running Jobs Panel | High |
| **4** | Job History Panel (List) | High |
| **5** | Job History Panel (Detail Viewer) | High |
| **6** | Settings & Preferences | Medium |
| **7** | UI Polish & Workflow Identity | Medium |
| **8** | Testing & Documentation | Final |
| **9** | ~~External UI Exploration~~ | CANCELLED |

---

## Phase 1: API Migration (Async + Polling)

**Objective**: Update the API client to use the new async execution pattern.

### Tasks

#### 1.1 Create API Client Module
- [ ] Create new `api_client.py` module with clean separation
- [ ] Implement `upload_file(base_url, version, api_id, file_path) -> file_id`
- [ ] Implement `execute_async(base_url, version, api_id, payload) -> execution_id`
- [ ] Implement `poll_status(base_url, version, execution_id) -> status_data`
- [ ] Implement `download_file(base_url, version, api_id, file_id, output_path)`

#### 1.2 Update Execution Flow
- [ ] Replace `api_execute` call with `api_execute_async`
- [ ] Implement polling loop in background thread
- [ ] Update progress based on real API status (`pending`, `running`, `completed`, `failed`)
- [ ] Extract outputs from `status_data["result"]["outputs"]`

#### 1.3 Structured Error Handling
- [ ] Parse error response structure: `error.error`, `error.node_name`, `error.node_type`, `error.node_id`
- [ ] Display formatted error message with node context
- [ ] Store error details in job state

### Test Criteria
```
✓ Load a workflow with no file uploads (bool, number, string inputs)
✓ Execute workflow → see status transitions: pending → running → completed
✓ Verify outputs are received correctly
✓ Test with failing workflow → see structured error message with node info
✓ Test with file uploads (image, mesh) → verify upload → execute → download flow
```

---

## Phase 2: Job Persistence & Data Model

**Objective**: Save job data to disk for history tracking, matching Unity's structure.

### Tasks

#### 2.1 Define Job Storage Structure
- [ ] Create jobs directory: `{addon_dir}/atlas_jobs/{workflow_name}/{timestamp}_{job_id_short}/`
- [ ] Define `job.json` schema matching Unity:
  ```json
  {
    "JobId": "uuid",
    "WorkflowId": "api_id",
    "WorkflowName": "string",
    "WorkflowVersion": "string",
    "CreatedAtUtc": "ISO8601",
    "CompletedAtUtc": "ISO8601 | null",
    "Status": "pending|running|completed|failed",
    "ExecutionId": "uuid",
    "ErrorMessage": "string | null",
    "ErrorNodeName": "string | null",
    "ErrorNodeType": "string | null", 
    "ErrorNodeId": "string | null",
    "Progress01": 0.0-1.0,
    "InputsSnapshot": [...],
    "OutputsSnapshot": [...],
    "JobFolderPath": "string"
  }
  ```

#### 2.2 Create Job Manager Module
- [ ] Create `job_manager.py` module
- [ ] Implement `create_job(workflow_state) -> Job` - creates folder and initial job.json
- [ ] Implement `update_job(job, status, progress, error, outputs)` - updates job.json
- [ ] Implement `get_all_jobs() -> List[JobSummary]` - scans all job folders
- [ ] Implement `get_job(job_id) -> Job` - loads full job data
- [ ] Implement `delete_job(job_id)` - removes job folder

#### 2.3 Integrate with Execution Flow
- [ ] Create job record when workflow starts
- [ ] Update job status during polling
- [ ] Save final state (success or failure) when complete
- [ ] Copy input files to job folder (inputs/)
- [ ] Save output files to job folder (outputs/)

### Test Criteria
```
✓ Run a workflow → job folder created with correct structure
✓ Job.json contains all required fields
✓ Input files copied to inputs/ folder
✓ Output files saved to outputs/ folder
✓ Run multiple workflows → each has its own job folder
✓ Job timestamps are correct
```

---

## Phase 3: Running Jobs Panel

**Objective**: Create a dedicated panel for monitoring active job execution.

### Tasks

#### 3.1 Add Running Job State
- [ ] Add `AtlasRunningJobState` PropertyGroup:
  - `job_id: StringProperty`
  - `workflow_name: StringProperty`
  - `started_at: StringProperty`
  - `status: EnumProperty` (pending, running, uploading, downloading)
  - `progress: FloatProperty`
  - `elapsed_seconds: FloatProperty`
  - `status_message: StringProperty`

#### 3.2 Create Running Jobs Panel UI
- [ ] Create `ATLAS_PT_RunningJobsPanel` class
- [ ] Panel only visible when `job_running == True`
- [ ] Display:
  - Workflow name
  - "Started: {time}"
  - Status badge (color-coded)
  - Progress bar with percentage
  - Elapsed time "MM:SS"
  - Status message text

#### 3.3 Real-time Updates
- [ ] Update progress from polling status
- [ ] Calculate elapsed time from start timestamp
- [ ] Force UI redraw on timer

### Test Criteria
```
✓ Panel hidden when no job running
✓ Panel appears when job starts
✓ Progress bar updates in real-time
✓ Elapsed time counts up correctly
✓ Status message reflects current phase (uploading, executing, downloading)
✓ Panel hides when job completes
```

---

## Phase 4: Job History Panel (List)

**Objective**: Display a filterable list of past jobs.

### Tasks

#### 4.1 Create Job History State
- [ ] Add `AtlasJobHistoryState` PropertyGroup:
  - `jobs: CollectionProperty` of job summaries
  - `active_job_index: IntProperty`
  - `filter_status: EnumProperty` (All, Success, Failed, Running)
  - `filter_workflow: EnumProperty` (dynamic: all workflow names)
  - `filter_date: EnumProperty` (All Time, Today, Last 7 Days, Last 30 Days)

#### 4.2 Create UIList for Jobs
- [ ] Create `ATLAS_UL_JobHistoryList` class
- [ ] Display per item:
  - Status indicator (colored dot/icon)
  - Workflow name
  - Relative timestamp ("just now", "5m ago", "2h ago", "Yesterday")
- [ ] Group by date sections: "Today", "Yesterday", "Last 7 Days", "Older"

#### 4.3 Create Job History Panel
- [ ] Create `ATLAS_PT_JobHistoryPanel` class
- [ ] Add filter row at top (Status | Type | Date dropdowns)
- [ ] Embed UIList below filters
- [ ] Add refresh button to rescan jobs

#### 4.4 Implement Filtering Logic
- [ ] Filter jobs by status
- [ ] Filter jobs by workflow name (populate enum dynamically)
- [ ] Filter jobs by date range
- [ ] Apply combined filters

### Test Criteria
```
✓ Panel shows list of previous jobs
✓ Jobs sorted by date (newest first)
✓ Jobs grouped by date category
✓ Status filter works (show only failed, etc.)
✓ Workflow filter shows all workflow types
✓ Date filter restricts to time range
✓ Clicking a job highlights it
```

---

## Phase 5: Job History Panel (Detail Viewer)

**Objective**: Display full details of a selected job.

### Tasks

#### 5.1 Create Job Detail State
- [ ] Add `AtlasJobDetailState` PropertyGroup:
  - All fields from job.json loaded
  - Inputs collection
  - Outputs collection

#### 5.2 Create Job Detail Panel
- [ ] Create `ATLAS_PT_JobDetailPanel` class (sub-panel or collapsible box)
- [ ] Only visible when a job is selected
- [ ] Display:
  - Header: Workflow name + Status badge
  - Timestamps: Created, Completed, Duration
  - Inputs section (collapsible): show all input values/files
  - Outputs section (collapsible): show all output values/files
  - Error section (if failed): formatted error with node info

#### 5.3 Job Detail Actions
- [ ] "Open Job Folder" button - opens file explorer to job directory
- [ ] "Re-run with these inputs" button - loads inputs into current workflow
- [ ] Output file actions (for completed jobs):
  - Images: View, Apply to Object, Save As
  - Meshes: Import, Replace Active

#### 5.4 Load Job on Selection
- [ ] When job selected in list, load full job.json
- [ ] Populate detail panel with loaded data

### Test Criteria
```
✓ Selecting a job shows its details
✓ All metadata displayed correctly
✓ Inputs show correct values and file paths
✓ Outputs show values/file references
✓ Failed jobs show error details with node info
✓ "Open Job Folder" opens correct directory
✓ Output action buttons work (import mesh, apply image)
```

---

## Phase 6: Settings & Preferences

**Objective**: Add configurable settings matching Unity plugin.

### Tasks

#### 6.1 Create Addon Preferences
- [ ] Register addon preferences class `AtlasWorkflowPreferences`
- [ ] Add settings:
  - **Output Settings**:
    - `output_save_path: StringProperty` (directory for permanent saves)
  - **API Settings**:
    - `request_timeout: IntProperty` (seconds, default 300)
    - `no_timeout_limit: BoolProperty` (warning when enabled)
    - `poll_interval: FloatProperty` (seconds, default 2.0)
  - **Notifications**:
    - `notify_on_complete: BoolProperty`
  - **Temporary Storage**:
    - `max_storage_mb: IntProperty` (default 500)
    - `warn_when_exceeded: BoolProperty`
  - **Logging**:
    - `verbose_logging: BoolProperty`

#### 6.2 Create Preferences UI
- [ ] Draw preferences panel in addon settings
- [ ] Add "Clean Old Files" operator
- [ ] Add "Clear All Jobs" operator (with confirmation)
- [ ] Display current storage usage

#### 6.3 Integrate Settings
- [ ] Use timeout settings in API calls
- [ ] Use poll_interval in status polling
- [ ] Show Blender notification on job complete (if enabled)
- [ ] Check storage limit before creating new jobs
- [ ] Apply verbose logging to all log statements

### Test Criteria
```
✓ Preferences accessible in Blender addon settings
✓ Timeout settings affect API calls
✓ Poll interval affects polling frequency
✓ Notification appears on job complete (when enabled)
✓ "Clean Old Files" removes old temp directories
✓ Storage warning appears when limit exceeded
✓ Verbose logging produces detailed output
```

---

## Phase 7: UI Polish & Workflow Identity

**Objective**: Ensure the workflow feels identical to Unity/Unreal despite UI differences.

### Tasks

#### 7.1 Current Workflow Panel Refinements
- [ ] "Run {WorkflowName}" button text (not just "Run Workflow")
- [ ] Show "Last job: Succeeded/Failed (HH:MM:SS)" status line
- [ ] Outputs show "(pending)" label before first run
- [ ] Status dot colors match Unity (green=success, red=failed, orange=running)

#### 7.2 Workflow Library Improvements
- [ ] Add confirmation dialog for "Remove Workflow" (warn permanent)
- [ ] Show workflow version/API endpoint in dropdown tooltip
- [ ] Green dot indicator for valid/loaded workflows

#### 7.3 Input Validation
- [ ] Validate required inputs before run
- [ ] Show validation errors inline (red alert)
- [ ] Disable Run button if validation fails

#### 7.4 Output Enhancements
- [ ] Auto-import meshes to scene (optional setting)
- [ ] Auto-apply images to selected object (optional setting)
- [ ] Progress indication during file downloads

### Test Criteria
```
✓ Run button shows workflow name
✓ Last job status visible
✓ Outputs show pending state initially
✓ Status colors are consistent
✓ Delete confirmation dialog appears
✓ Validation prevents running with missing inputs
✓ User experience matches Unity plugin flow
```

---

## Phase 8: Testing & Documentation

**Objective**: Ensure reliability and provide user guidance.

### Tasks

#### 8.1 Integration Testing
- [ ] Test all workflow types (no uploads, image only, mesh only, mixed)
- [ ] Test error scenarios (network failure, API errors, invalid inputs)
- [ ] Test job history with 50+ jobs
- [ ] Test concurrent workflows (if supported)
- [ ] Test addon enable/disable/re-enable cycle

#### 8.2 Edge Case Testing
- [ ] Very large files (>100MB meshes)
- [ ] Long-running workflows (>10 minutes)
- [ ] Unicode in workflow names and paths
- [ ] Network disconnection during execution
- [ ] Blender crash recovery (job state persistence)

#### 8.3 Documentation
- [ ] Update README.md with new features
- [ ] Document workflow JSON schema
- [ ] Document job.json schema
- [ ] Add inline code comments
- [ ] Create user guide (basic usage)

### Test Criteria
```
✓ All workflow types execute successfully
✓ Errors are handled gracefully with user feedback
✓ History performs well with many jobs
✓ Edge cases don't crash the addon
✓ Documentation is complete and accurate
```

---

## Implementation Order & Dependencies

```
Phase 1 (API) ─────────────────┐
                               │
Phase 2 (Job Persistence) ─────┼──► Phase 3 (Running Jobs Panel)
                               │
                               ├──► Phase 4 (History List)
                               │         │
                               │         ▼
                               └──► Phase 5 (History Detail)
                                         │
                                         ▼
Phase 6 (Settings) ◄─────────────────────┘
         │
         ▼
Phase 7 (UI Polish)
         │
         ▼
Phase 8 (Testing)
         │
         ▼
Phase 9 (External UI) ──► CANCELLED (see rationale in Phase 9 section)
```

---

## Quick Reference: File Changes

| File | Changes |
|------|---------|
| `api_client.py` | **NEW** - Clean API abstraction |
| `job_manager.py` | **NEW** - Job persistence logic |
| `job_state.py` | **NEW** - Job-related PropertyGroups |
| `operators.py` | MODIFY - Use new API client, create jobs |
| `ui_panel.py` | MODIFY - Add Running Jobs, History panels |
| `atlas_workflow_state.py` | MODIFY - Add job history state |
| `__init__.py` | MODIFY - Register new modules |
| `preferences.py` | **NEW** - Addon settings |
| ~~`workspace_setup.py`~~ | CANCELLED - External UI exploration abandoned |

---

## Version Milestones

| Version | Phases | Description |
|---------|--------|-------------|
| **0.2.0** | 1, 2 | New API + Job Persistence |
| **0.3.0** | 3, 4, 5 | Complete Job History System |
| **0.4.0** | 6, 7 | Settings + UI Polish |
| **1.0.0** | 8 | Production Ready |
| ~~**1.1.0**~~ | ~~9~~ | ~~External UI~~ (CANCELLED) |

---

## ~~Phase 9: External UI Exploration~~ (CANCELLED)

> **Status**: CANCELLED - After evaluation, external UI approaches were deemed unprofessional
> for a production pipeline tool. The N-panel approach is the correct Blender-native solution.

### Decision Rationale

We explored several external UI approaches:

1. **Dedicated Blender Workspace** - Workable but added complexity without solving core UX issues
2. **Tkinter Floating Window** - Required external Python deps, felt disconnected
3. **Web UI (Flask + Browser)** - Clever hack but unprofessional for production tools

**Conclusion**: The N-panel IS the professional standard for Blender addons. The "cramped" feeling
is a **design challenge to solve**, not a limitation to circumvent with external hacks.

All major professional addons (Rigify, Hard Ops, BoxCutter, FLIP Fluids) use N-panels successfully.
Users expect tools to be IN the DCC app. External UIs create context-switching friction and feel
disconnected from the Blender workflow.

### Going Forward

Focus efforts on Phase 7 (UI Polish) instead:
- Design for N-panel constraints (progressive disclosure, collapsible sections)
- Use modal dialogs for complex detail views
- Prioritize workflow efficiency over UI real estate
- Study successful addons for design patterns

---

*Last Updated: 2026-02-05*
