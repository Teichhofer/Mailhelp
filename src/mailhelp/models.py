"""Rückwärtskompatibler Importpfad für die aufgeteilten Fachmodelle.

Neue Anwendungsteile importieren aus :mod:`mailhelp.domain` beziehungsweise für
gespeicherte Zustände aus :mod:`mailhelp.persistence.schemas`.
"""
from .domain.run import *
from .domain.relevance import *
from .domain.temporal import *
from .domain.extraction import *
from .domain.proposal import *
from .domain.processing import *
from .domain.duplicate import *
from .domain.mail import *

# Kept for callers that used this intentionally testable compatibility helper.
from .domain.proposal import _required_revision_questions as _required_revision_questions
