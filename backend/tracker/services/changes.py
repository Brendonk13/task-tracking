"""Body copy for ``field_change`` history entries (A5), shared by tickets and tasks."""


def render(value) -> str:
    """A5: null/empty renders as ``(none)``; lists comma-joined and sorted."""
    if value is None or value == "" or value == []:
        return "(none)"
    if isinstance(value, list):
        return ", ".join(str(item) for item in sorted(value))
    return str(value)


def field_change_body(actor_name: str, field: str, old, new) -> str:
    if field == "description":
        return f"{actor_name} changed description"
    return f"{actor_name} changed {field} from {render(old)} to {render(new)}"
