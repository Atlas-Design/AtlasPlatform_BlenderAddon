# Workflow JSON

Workflow JSON files tell the addon which Atlas API endpoint to call and which controls to show in Blender.

## Minimal Shape

```json
{
  "version": "0.2",
  "api_id": "00000000-0000-0000-0000-000000000000",
  "base_url": "https://api.prod-market.atlas.design",
  "name": "Example_Workflow",
  "inputs": [],
  "outputs": []
}
```

## Top-Level Fields

| Field | Required | Notes |
| --- | --- | --- |
| `version` | Yes | Atlas API version, for example `0.2`. |
| `api_id` | Yes | Atlas workflow API ID. |
| `base_url` | Yes | Atlas API base URL. |
| `name` | Yes | Display name in Blender. |
| `inputs` | Yes | Array of input parameters. |
| `outputs` | Yes | Array of output parameters. |

## Supported Types

| Type | Blender Input UI | Output Behavior |
| --- | --- | --- |
| `boolean` | Checkbox | Shows `Yes` or `No`. |
| `number` | Number field | Shows numeric value and copy action. |
| `string` | Text field | Shows preview, full text dialog, and copy action. |
| `image` | Scene image or image file | Downloads PNG/JPEG-style output and can preview/apply as material. |
| `mesh` | Scene object or GLB/GLTF file | Downloads GLB output and can import it. |

## Input Parameter

```json
{
  "id": "input_text",
  "type": "string",
  "label": "Prompt",
  "default_value": ""
}
```

`default_value` is optional. Image and mesh inputs do not need a default value.

## Output Parameter

```json
{
  "id": "output_image",
  "type": "image",
  "format": "png"
}
```

`format` is optional, but useful for binary outputs such as images and meshes.

## Examples

See `examples/` for sanitized templates. Replace placeholder `api_id` values before running them.
