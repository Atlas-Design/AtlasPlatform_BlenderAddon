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
The native suite contains **49 checks**, including **40 base regressions**;
the parser/transport suite contains **12**. Both Blender versions pass the native
suite. Coverage includes per-workflow drafts, historical source reuse, run labels,
persistent unreviewed results, explicit navigation and non-destructive image preview,
as well as settings, storage safety and concurrent execution. Run-controls checks
cover exact-run deletion, active-run guards, stopping during upload/submission/
poll/download, interruptible polling waits, partial-file preservation, output
copies, independent concurrent runs and completion races.

For an actual native GUI smoke run with synthetic results (no Atlas calls):

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --factory-startup --python-exit-code 1 --python tests/blender_ui_smoke.py -- --output M:/P4-PLUGINS/Blender-QA/run-jobs-ui
```

Run in a separate disposable Blender process. The script captures Run, Jobs,
job details and the image preview popup, writes `report.json` with draw errors,
and quits. On Blender 4.0, the harness temporarily draws the panel under Item
because category selection is unavailable through RNA; production uses Atlas.
Inspect the captures as well as the report. It does not install the
release ZIP or replace the interactive acceptance cases in the testing guide.
Pass `--dialog stop` or `--dialog delete` to capture the corresponding confirmation
instead of the image popup; neither confirmation is accepted by the smoke script.

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
