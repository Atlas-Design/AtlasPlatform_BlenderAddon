@echo off
setlocal

set "PACKAGE_NAME=AtlasPlatform_BlenderAddon"
set "VERSION=%~1"

if "%VERSION%"=="" (
    set /p VERSION=Release version, for example v0.1.0: 
)

if "%VERSION%"=="" (
    echo ERROR: Release version is required.
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ADDON_ROOT=%%~fI"

set "STAGING_ROOT=%TEMP%\%PACKAGE_NAME%-%VERSION%-release-staging"
set "STAGING_ADDON=%STAGING_ROOT%\%PACKAGE_NAME%"
set "DIST_DIR=%ADDON_ROOT%\dist"
set "ZIP_PATH=%DIST_DIR%\%PACKAGE_NAME%.zip"

echo Packaging %PACKAGE_NAME% %VERSION%
echo Source: %ADDON_ROOT%
echo Output: %ZIP_PATH%

if exist "%STAGING_ROOT%" rmdir /s /q "%STAGING_ROOT%"
if not exist "%STAGING_ADDON%" mkdir "%STAGING_ADDON%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

robocopy "%ADDON_ROOT%" "%STAGING_ADDON%" /S /R:1 /W:1 ^
    /XD ".git" "__pycache__" "atlas" "atlas_jobs" "atlas_workflows" ".idea" ".vscode" "docs" "dist" "release-staging" "scripts" ^
    /XF "*.pyc" "*.pyo" "*.blend1" "*.blend2" ".DS_Store" "Thumbs.db" ".gitignore" "ROADMAP.md"

if errorlevel 8 (
    echo ERROR: Failed to copy release files.
    exit /b 1
)

robocopy "%ADDON_ROOT%\atlas" "%STAGING_ADDON%" "*.py" /R:1 /W:1 ^
    /XD "__pycache__" ^
    /XF "__init__.py" "*.pyc" "*.pyo"

if errorlevel 8 (
    echo ERROR: Failed to copy flattened addon modules.
    exit /b 1
)

python "%SCRIPT_DIR%create_portable_zip.py" "%STAGING_ADDON%" "%ZIP_PATH%"

if errorlevel 1 (
    echo ERROR: Failed to create release zip.
    exit /b 1
)

echo.
echo Release package created:
echo %ZIP_PATH%
echo.
echo Test this zip in Blender with Edit ^> Preferences ^> Add-ons ^> Install...

rmdir /s /q "%STAGING_ROOT%" >nul 2>nul

exit /b 0
