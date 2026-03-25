"""Солверы по типам заданий."""

from .base import BaseSolver
from .choice import ChoiceSolver
from .matching import MatchingSolver
from .sorting import SortingSolver
from .text import TextSolver

__all__ = [
    "BaseSolver",
    "ChoiceSolver",
    "MatchingSolver",
    "SortingSolver",
    "TextSolver",
]
