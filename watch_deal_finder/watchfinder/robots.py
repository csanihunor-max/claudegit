"""A small robots.txt matcher with Google semantics.

Python's urllib.robotparser does plain prefix matching and ignores the `*`
and `$` wildcards that Jófogás relies on (e.g. `Disallow: /*?max_price`,
`Allow: /*?o=2$`), so it would answer "allowed" for URLs the site forbids.
This implements the parts we need: user-agent groups, `*` / `$` patterns
and longest-match-wins with Allow beating Disallow on ties.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)


class RobotsRules:
    def __init__(self, text: str):
        self.groups: list[_Group] = []
        current: _Group | None = None
        last_was_agent = False
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                # Consecutive User-agent lines share one group.
                if current is None or not last_was_agent:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
            elif key in ("allow", "disallow") and current is not None:
                if value:  # an empty Disallow allows everything
                    current.rules.append((key == "allow", value))
                last_was_agent = False
            else:
                last_was_agent = False

    def _group_for(self, user_agent: str) -> _Group | None:
        ua = user_agent.lower()
        best: tuple[int, _Group] | None = None
        for group in self.groups:
            for agent in group.agents:
                if agent != "*" and agent in ua and (best is None or len(agent) > best[0]):
                    best = (len(agent), group)
        if best:
            return best[1]
        return next((g for g in self.groups if "*" in g.agents), None)

    def allowed(self, url: str, user_agent: str) -> bool:
        group = self._group_for(user_agent)
        if group is None:
            return True
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        verdict, best_len = True, -1
        for allow, pattern in group.rules:
            if _matches(pattern, path):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    verdict, best_len = allow, length
        return verdict


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.match(regex + ("$" if anchored else ""), path) is not None
