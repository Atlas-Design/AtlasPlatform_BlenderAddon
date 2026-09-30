# Example Workflows

This folder contains sanitized workflow JSON templates.

`all-types-v02.example.json` contains all 15 inputs and 21 outputs from the
supplied all-types export, including the four image/mesh arrays. It uses a
placeholder API ID and non-routable example host. It requires no OpenAPI schema.

Before running an example:

1. Replace the placeholder `api_id` with a real Atlas workflow API ID.
2. Confirm `base_url` and `version` match the target Atlas environment.
3. Import the JSON through **Atlas Workflow Library > Import** in Blender.

Runtime workflows saved inside Blender are stored in `atlas_workflows/`, which is ignored by Git.
