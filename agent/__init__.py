"""Construction labor cost agent."""


def answer(query: str, rates: dict | None = None, offline: bool = False, hybrid_factory=None) -> dict:
    from agent.graph import answer as run

    return run(query, rates, offline, hybrid_factory)
