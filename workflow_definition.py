from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Enum for parameter types
# ---------------------------------------------------------------------------

class ParamType(str, Enum):
    BOOL = "boolean"
    NUMBER = "number"
    STRING = "string"
    IMAGE = "image"
    MESH = "mesh"

    @staticmethod
    def from_str(value: str) -> "ParamType":
        """Map raw JSON type strings to ParamType, with validation."""
        value = value.lower()
        try:
            return ParamType(value)
        except ValueError:
            raise ValueError(f"Unsupported parameter type: {value!r}")


# ---------------------------------------------------------------------------
# Input / Output parameter definitions (pure data, no Blender)
# ---------------------------------------------------------------------------

@dataclass
class InputParamDef:
    id: str
    type: ParamType
    label: str
    default_value: Any = None

    # Future extensions:
    # min_value: Optional[float] = None
    # max_value: Optional[float] = None
    # step: Optional[float] = None
    # help_text: Optional[str] = None


@dataclass
class OutputParamDef:
    id: str
    type: ParamType
    format: Optional[str] = None  # e.g. "png", "glb"


# ---------------------------------------------------------------------------
# Workflow definition
# ---------------------------------------------------------------------------

@dataclass
class WorkflowDefinition:
    version: str
    api_id: str
    base_url: str
    name: str

    inputs: List[InputParamDef] = field(default_factory=list)
    outputs: List[OutputParamDef] = field(default_factory=list)

    # -------- Convenience lookups --------

    def get_input(self, param_id: str) -> Optional[InputParamDef]:
        for p in self.inputs:
            if p.id == param_id:
                return p
        return None

    def get_output(self, param_id: str) -> Optional[OutputParamDef]:
        for p in self.outputs:
            if p.id == param_id:
                return p
        return None

    # -------- Construction helpers --------

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "WorkflowDefinition":
        """Create a WorkflowDefinition from a dict parsed from JSON."""
        # Basic required fields
        try:
            version = data["version"]
            api_id = data["api_id"]
            base_url = data["base_url"]
            name = data["name"]
        except KeyError as e:
            raise ValueError(f"Missing required field in workflow json: {e}") from e

        # Inputs
        raw_inputs = data.get("inputs", [])
        inputs: List[InputParamDef] = []
        for idx, item in enumerate(raw_inputs):
            try:
                pid = item["id"]
                ptype = ParamType.from_str(item["type"])
            except KeyError as e:
                raise ValueError(f"Missing field in inputs[{idx}]: {e}") from e
            except ValueError as e:
                raise ValueError(f"Error in inputs[{idx}]: {e}") from e

            label = item.get("label", pid)
            default = item.get("default_value")
            inputs.append(
                InputParamDef(
                    id=pid,
                    type=ptype,
                    label=label,
                    default_value=default,
                )
            )

        # Outputs
        raw_outputs = data.get("outputs", [])
        outputs: List[OutputParamDef] = []
        for idx, item in enumerate(raw_outputs):
            try:
                pid = item["id"]
                ptype = ParamType.from_str(item["type"])
            except KeyError as e:
                raise ValueError(f"Missing field in outputs[{idx}]: {e}") from e
            except ValueError as e:
                raise ValueError(f"Error in outputs[{idx}]: {e}") from e

            fmt = item.get("format")
            outputs.append(
                OutputParamDef(
                    id=pid,
                    type=ptype,
                    format=fmt,
                )
            )

        return WorkflowDefinition(
            version=version,
            api_id=api_id,
            base_url=base_url,
            name=name,
            inputs=inputs,
            outputs=outputs,
        )

    @staticmethod
    def from_json_str(json_str: str) -> "WorkflowDefinition":
        data = json.loads(json_str)
        return WorkflowDefinition.from_dict(data)

    @staticmethod
    def from_json_file(path: str, encoding: str = "utf-8") -> "WorkflowDefinition":
        with open(path, "r", encoding=encoding) as f:
            data = json.load(f)
        return WorkflowDefinition.from_dict(data)

    # Optional: if you have a fixed pattern for the endpoint, define it here.
    def build_endpoint_url(self) -> str:
        """
        Construct the full endpoint URL for this workflow.

        Adjust this to match your real backend convention, e.g.:
          f"https://{self.base_url}/v1/api/{self.api_id}/run"
        """
        return f"https://{self.base_url}/v1/api/{self.api_id}/run"


# ---------------------------------------------------------------------------
# Quick manual test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_json = r'''
    {
        "version": "0.1",
        "api_id": "23485120-0ca5-4b4e-8a55-a3034328637e",
        "base_url": "api.prod.atlas.design",
        "name": "my_api_name",
        "inputs": [
            {
                "id": "input_use_texture",
                "type": "boolean",
                "label": "input_use_texture",
                "default_value": true
            },
            {
                "id": "input_number",
                "type": "number",
                "label": "input_number",
                "default_value": 100
            },
            {
                "id": "input_text_style",
                "type": "string",
                "label": "input_text_style",
                "default_value": "Medieval"
            },
            {
                "id": "input_text_prompt",
                "type": "string",
                "label": "input_text_prompt",
                "default_value": "Helmet"
            }
        ],
        "outputs": [
            {
                "id": "output_text_finalPrompt",
                "type": "string"
            },
            {
                "id": "output_image",
                "type": "image",
                "format": "png"
            },
            {
                "id": "output_mesh",
                "type": "mesh",
                "format": "glb"
            },
            {
                "id": "output_number_seed",
                "type": "number"
            },
            {
                "id": "output_boolean_usedTexture",
                "type": "boolean"
            }
        ]
    }
    '''

    wf = WorkflowDefinition.from_json_str(sample_json)

