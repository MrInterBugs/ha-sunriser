# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Aedan Lawrence <aedan@mrinterbugs.uk>
"""Schema library used by Home Assistant.

Home Assistant 2026.10 replaced voluptuous with probatio, which keeps the
voluptuous API (and HA maps ``import voluptuous`` to it). Importing probatio
directly gives type checkers the schema types HA now expects; earlier releases
ship voluptuous.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio as vol
else:
    try:
        import probatio as vol
    except ImportError:  # Home Assistant before 2026.10
        import voluptuous as vol

__all__ = ["vol"]
