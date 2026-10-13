"""Rückwärtskompatibler Importpfad für die aufgeteilten Fachmodelle.

Neue Anwendungsteile importieren aus :mod:`mailhelp.domain` beziehungsweise für
gespeicherte Zustände aus :mod:`mailhelp.persistence.schemas`.
"""

from __future__ import annotations

from .domain.duplicate import *
from .domain.extraction import *
from .domain.mail import *
from .domain.processing import *
from .domain.proposal import *

# Kept for callers that used this intentionally testable compatibility helper.
from .domain.proposal import required_revision_questions as required_revision_questions
from .domain.relevance import *
from .domain.run import *
from .domain.temporal import *
