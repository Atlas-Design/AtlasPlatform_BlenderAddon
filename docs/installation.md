# Installation

## Install the Addon

1. Download or clone the addon repository.
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Click **Install...** and select the addon folder or zip.
4. Enable **Atlas Workflow Integration**.
5. Open the 3D View sidebar with `N`, then choose the **Atlas** tab.

## Install Python Requests

The addon uses Python `requests` to communicate with the Atlas Platform API. If Blender reports that `requests` is missing, install it into Blender's bundled Python.

Example Windows workflow:

```powershell
"C:\Program Files\Blender Foundation\Blender 4.0\4.0\python\bin\python.exe" -m ensurepip
"C:\Program Files\Blender Foundation\Blender 4.0\4.0\python\bin\python.exe" -m pip install requests
```

Adjust the path for your Blender version and install location.

## API Key Setup

Atlas Platform API v0.2 workflows require a workspace API key.

You can provide the key in either place:

- **Blender preference:** **Edit > Preferences > Add-ons > Atlas Workflow Integration > API Settings > Workspace API Key**
- **Environment variable:** `API_KEY=atk_...`

Do not commit API keys to workflow JSON files, screenshots, or source control.

## Clean Install Test

Before distributing a build:

1. Install the addon from a fresh zip in a clean Blender profile.
2. Confirm the **Atlas** tab appears in the 3D View sidebar.
3. Set a workspace API key.
4. Import a workflow JSON.
5. Run one workflow that produces at least one image or mesh output.
6. Confirm outputs appear in **Jobs History**.
