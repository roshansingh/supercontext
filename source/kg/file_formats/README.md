# File Format Support

File-format support lives outside language extraction so config and IaC formats can evolve independently from Python, TypeScript, Java, or other source-language plugins. A support package may own a config-file scanner or a config literal normalization pass when the adapter still reads config/IaC files.

Each discoverable support package is named `format_<name>/` and exports `FORMAT_SUPPORT` from `format.py`. Discovery loads only those directories and skips `_shared/`, `_template/`, `adapters/`, and plain helper modules.

Use `_template/` when adding a new format. Put shared implementation helpers in `_shared/`; do not create a discoverable format package unless it returns one or more real adapters.
