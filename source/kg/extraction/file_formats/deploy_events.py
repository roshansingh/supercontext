import sys

from source.kg.file_formats._shared import deploy_events as _deploy_events

sys.modules[__name__] = _deploy_events
