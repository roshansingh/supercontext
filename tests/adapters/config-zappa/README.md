# Config Zappa Adapter Fixtures

The `false_positive/events.json` fixture intentionally has the same Zappa-shaped
content as the golden fixture but uses the wrong filename. This pins the v1
contract that only `zappa_settings.json` is treated as Zappa configuration.
