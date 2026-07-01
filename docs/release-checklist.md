# Release Checklist

Use this checklist before publishing the addon outside the team.

## Repository

- [ ] No generated files are tracked (`__pycache__`, `.pyc`, local job history, IDE files).
- [ ] `atlas_workflows/` and `atlas_jobs/` are ignored.
- [ ] Example workflow JSON files use placeholder API IDs only.
- [ ] README links resolve on GitHub.
- [ ] Screenshot placeholders have been captured or intentionally left as pending.

## Blender Install

- [ ] Install from zip in a clean Blender 4.x profile.
- [ ] Enable **Atlas Workflow Integration** without console errors.
- [ ] Confirm the 3D View sidebar shows the **Atlas** tab.
- [ ] Confirm missing optional icons do not block addon use.

## API Workflow

- [ ] Set workspace API key in addon preferences.
- [ ] Run a v0.2 workflow with primitive inputs/outputs.
- [ ] Run a workflow with image input and image output.
- [ ] Run a workflow with mesh input and mesh output.
- [ ] Confirm failures show useful error messages.

## Output UX

- [ ] Image **View** creates an aspect-ratio preview plane.
- [ ] Image **Apply** creates a new material on the selected object.
- [ ] Mesh **Import** imports GLB output.
- [ ] Text output opens in full-text dialog and copies to clipboard.
- [ ] Job history remains compact enough for normal sidebar use.

## Documentation

- [ ] Installation docs mention Blender version and `requests`.
- [ ] API key instructions warn not to commit secrets.
- [ ] Troubleshooting covers missing key, missing `requests`, and missing input files.
- [ ] License is present.
