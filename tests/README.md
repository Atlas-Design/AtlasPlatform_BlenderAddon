# Blender regression checks

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
