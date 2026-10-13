"""Deprecated compatibility imports for the decomposed Telegram package."""

from __future__ import annotations

# ``secrets`` remains exposed for older test/integration patch points.  The
# callbacks module uses the same module object, so patching token_hex still works.
from .authorization import *
from .callbacks import *
from .client import *
from .dialog import *
from .formatting import *
from .ledger import *
from .models import *
from .relevance import *
from .revisions import *
from .temporal import *
from .writes import *
