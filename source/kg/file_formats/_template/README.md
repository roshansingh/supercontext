# File Format Support Template

Copy this directory to `source/kg/file_formats/format_<name>/` and update
`format.py` to export a `FORMAT_SUPPORT` object. Keep extractor implementation
and shared helpers outside the support wrapper unless the format needs new code.
