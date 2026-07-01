# Atlas Blender Addon Roadmap

> Goal: keep the Blender addon aligned with the Atlas Platform workflow model while preserving a Blender-native sidebar experience.

## Current Status

The addon is in internal beta shape. Core workflow execution is working with Atlas Platform API v0.2, including workspace API key authentication, async execution, job history, and output actions for images, meshes, text, numbers, and booleans.

## Completed

- Workflow JSON parsing and dynamic UI generation.
- Local workflow library support.
- Atlas Platform API v0.2 authentication and async polling.
- Image and mesh upload/download handling.
- Running job progress UI.
- Persistent job history stored locally in `atlas_jobs/`.
- Compact job detail view with outputs first and inputs collapsed by default.
- Image preview planes, image material application, mesh import, text output dialog, and copy actions.
- Atlas branding cleanup.
- Repository cleanup for generated files, local workflows, and job history.

## Public Release Checklist

### 1. Clean Install Validation

- [ ] Install from zip in a clean Blender 4.x profile.
- [ ] Confirm the **Atlas** tab appears in the 3D View sidebar.
- [ ] Confirm addon enable does not produce warnings that block use.
- [ ] Confirm `requests` installation instructions work on Windows.

### 2. Workflow Coverage

- [ ] Test a primitive-only v0.2 workflow.
- [ ] Test image input and image output.
- [ ] Test mesh input and mesh output.
- [ ] Test mixed image, mesh, text, number, and boolean outputs.
- [ ] Test failing workflow responses with structured node error information.

### 3. UX Polish

- [ ] Capture screenshots for `docs/images/`.
- [ ] Verify compact panel defaults on a normal laptop-height display.
- [ ] Decide whether optional custom icons should ship with the first public build.
- [ ] Review text wrapping for long prompts and generated text.
- [ ] Add confirmation around destructive history/library actions where needed.

### 4. Documentation

- [ ] Finalize README screenshots.
- [ ] Confirm installation docs for Blender's Python are correct for supported OS versions.
- [ ] Add a short support/contact path.
- [ ] Confirm example workflow JSON files use placeholder API IDs only.

### 5. Packaging

- [ ] Create a release zip with only runtime files, docs, examples, icons, README, and LICENSE.
- [ ] Exclude `.git/`, local job history, local workflow library, IDE files, and Python cache files.
- [ ] Smoke test the release zip in Blender.

## Out of Scope for First Public Release

- External browser or floating-window UI.
- Dedicated Blender workspace layout.
- Multi-job concurrent execution beyond the current running-job display.
- Built-in Atlas workflow marketplace/browser.

## Notes

Runtime Python modules intentionally live at the repository root because this is the expected layout for a directly installable Blender addon package.
