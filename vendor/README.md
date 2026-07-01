# Vendored Python Dependencies

The addon bundles its HTTP dependencies so Blender users do not need to install Python packages manually.

Bundled packages:

- `requests` 2.34.2
- `urllib3` 2.7.0
- `certifi` 2026.6.17
- `charset_normalizer` 3.4.7
- `idna` 3.18

These packages are installed from PyPI into `vendor/` and loaded only if Blender's Python environment does not already provide `requests`.

Each package includes its own `.dist-info` metadata, including license information where provided by the package.
