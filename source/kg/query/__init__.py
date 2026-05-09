"""Query surfaces over JSONL KG snapshots."""

__all__ = ["KgSnapshot"]


def __getattr__(name: str):
    if name == "KgSnapshot":
        from source.kg.query.snapshot import KgSnapshot

        return KgSnapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
