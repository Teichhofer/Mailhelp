"""Deprecated compatibility imports for the decomposed Telegram package."""

from __future__ import annotations

from ..persistence.ledger import *
from ..temporal_answers import *

# ``secrets`` remains exposed for older test/integration patch points.  The
# callbacks module uses the same module object, so patching token_hex still works.
from .authorization import *
from .callbacks import *
from .client import *
from .dialog import *
from .formatting import *
from .models import *
from .relevance import *
from .revisions import *
from .writes import *
