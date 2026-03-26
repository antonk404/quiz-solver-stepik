"""Пакет stepik — клиент REST API Stepik."""

from .api_client import StepikAPIClient
from .exceptions import (
    StepikAPIError,
    StepikAuthError,
    StepikNotFoundError,
    StepikAPITransientError,
)
from .schemas import (
    StepData,
    AttemptData,
    ParsedStepURL,
    SourcePair,
    BlockSource,
    MatchingDataset,
    SortingDataset,
)
from .solvers import try_solve_matching, try_solve_sorting
from .reply_builders import (
    build_choice_reply,
    build_ordering_reply,
    build_string_reply,
    build_number_reply,
)
from .utils import strip_html, parse_step_url
from .http_client import StepikHTTPClient

__all__ = [
    # Client
    "StepikAPIClient",
    "StepikHTTPClient",
    # Exceptions
    "StepikAPIError",
    "StepikAuthError",
    "StepikNotFoundError",
    "StepikAPITransientError",
    # Schemas
    "StepData",
    "AttemptData",
    "ParsedStepURL",
    "SourcePair",
    "BlockSource",
    "MatchingDataset",
    "SortingDataset",
    # Solvers
    "try_solve_matching",
    "try_solve_sorting",
    # Builders
    "build_choice_reply",
    "build_ordering_reply",
    "build_string_reply",
    "build_number_reply",
    # Utils
    "strip_html",
    "parse_step_url",
]
