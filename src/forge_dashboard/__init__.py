"""Optional local dashboard adapter around the Forge domain core.

This package is a bring-your-own-key (BYOK) exception to Forge's normal
"no LLM provider API key" rule. See `docs/DECISIONS.md` D-033 and
`docs/ARCHITECTURE.md` "Dashboard Mode" before changing anything here.

Nothing in `forge.*` (the MCP server and domain core) imports this package,
and nothing here is installed unless the `dashboard` extra is requested.
"""

from __future__ import annotations
