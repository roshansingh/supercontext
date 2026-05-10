from __future__ import annotations


KNOWN_STACK_CATEGORY_PREDICATE: dict[str, str] = {
    "web_framework": "EXPOSES_ENDPOINT",
    "transport": "PRODUCES_EVENT",
    "task_queue": "CONSUMES_EVENT",
}

KNOWN_STACK_IMPORTS: dict[str, dict[str, str]] = {
    "python": {
        "boto3": "transport",
        "django": "web_framework",
        "fastapi": "web_framework",
        "flask": "web_framework",
    },
    "javascript": {
        "express": "web_framework",
    },
}
