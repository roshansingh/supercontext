from __future__ import annotations


KNOWN_STACK_CATEGORY_PREDICATE: dict[str, str] = {
    "web_framework": "EXPOSES_ENDPOINT",
    "transport": "PRODUCES_EVENT",
    "task_queue": "CONSUMES_EVENT",
}
