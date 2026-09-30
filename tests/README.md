# Blender regression checks

For the full manual and release procedure, including what remains unverified,
see [TESTING_GUIDE.md](../TESTING_GUIDE.md). This page is the automated-test quick reference.

Run in a separate background Blender process:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_regressions.py
```

Adjust the executable path for your Blender installation. The checks use real
Blender exporters, image data and material slots, with a fake Atlas transport.
They create isolated temporary job history and never call Atlas or modify user
preferences. They cover concurrent completion, workflow switching, cache safety,
mesh selection restoration, PNG encoding, relative paths, image application and
the workflow library timer.

The expanded checks cover the all-types export, mixed-source arrays, asset-ID
reuse, omission versus false/zero/empty values, partial download persistence,
context filenames, EXR HDR round trips and independent mesh exports.

Run the transport/parser tests with Python (the bundled HTTP dependencies are used):

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

These tests simulate asset objects and legacy IDs, authenticated streaming,
format selection, redirect handling and interrupted downloads.

For the native adapters and the full inherited regression suite:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_native_regressions.py
```

Validated with Blender 4.0.2 and 5.1. Tests include scene dependency packaging,
unsaved pixels, collection append, USDZ texture survival across reopening,
skinned animation and motion, SVG curves, media timing/overlap and context reuse.
The native suite now contains 39 checks (including the 30 base regressions);
the parser/transport suite contains 12. The original 27 native checks passed on
both versions during the API update. After the results UX changes, all 22 base
regressions passed on both versions, including stable history navigation,
concurrent completion notices, dismissal without deletion and execution phases.
The settings audit adds eight further regressions for output folder validation,
copy failures, notification toggles, logging, cleanup safety and preference helpers.
All 30 base regressions passed on both Blender versions on 2026-09-30; all 12
parser/transport checks also passed. Installed-UI settings checks remain manual.

`create_live_fixtures.py` generates small synthetic assets in a supplied directory
when run in factory-startup background Blender. `live_api_smoke.py` is an opt-in
integration check that uploads assets and executes a real workflow; it can consume
workflow credits. Supply `--workflow`, `--fixtures`, `--output` and optionally
`--chain` to verify a second execution with returned UUIDs. Credentials come only
from `API_KEY` or `ATLAS_TEST_KEY` in the process environment. It stores structural
reports without keys, UUIDs, signed URLs or conversation text.

On 2026-09-29, three executions of the supplied all-types development workflow
verified all 21 outputs, UUID chaining, and corrected MIME/filename handling.
That deployment returned legacy UUID strings; asset-object normalization remains
fixture-tested. See `ApiTypeSupportRoadmap.md` for the validation scope.
