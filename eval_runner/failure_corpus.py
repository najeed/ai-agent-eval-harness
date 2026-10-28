import re
from typing import Any


def search(
    query: str,
    *,
    run_store: Any,
    context: dict[str, Any] | None = None,
) -> None:
    """Search provider-owned events for failure evidence.

    A shared master log is not a run authority.  The caller supplies the run
    provider that owns the requested scope, and each event is read through its
    run identifier.
    """
    print(f"Searching local Failure Corpus for: '{query}'...")

    regex_pattern = None
    try:
        if any(char in query for char in ".+*?^$()[]{}|\\"):
            regex_pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pass

    matches: list[dict[str, Any]] = []
    try:
        for run in run_store.list_runs(limit=10_000, context=context):
            run_id = run.get("run_id")
            if not isinstance(run_id, str):
                continue
            events = run_store.get_events(
                run_id,
                offset=0,
                limit=10_000_000,
                context=context,
            )
            for event in events:
                search_space = " ".join(
                    str(event.get(field, ""))
                    for field in ("event", "status", "triage_tag", "metric", "content")
                )
                if regex_pattern:
                    found = bool(regex_pattern.search(search_space))
                else:
                    found = all(term in search_space.lower() for term in query.lower().split())
                if found:
                    matches.append(event)

        if not matches:
            print(f"No matching failures found for '{query}'.")
            return
        print(f"Found {len(matches)} matching failure events:")
        for match in matches[:10]:
            print(
                f"  [{match.get('timestamp', 'N/A')}] "
                f"Run: {match.get('run_id', 'unknown')} | "
                f"Event: {match.get('event', 'unknown')} | "
                f"Triage: {match.get('triage_tag', 'NONE')}"
            )
        if len(matches) > 10:
            print(f"  ... and {len(matches) - 10} more.")
    except Exception as exc:
        print(f"Error searching corpus: {exc}")
