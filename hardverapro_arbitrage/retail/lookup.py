"""Look up a retail price for one item: search árukereső.hu, parse the
results, and pick the best match (if any).
"""
from __future__ import annotations

import logging

from ..models import RetailPrice
from .client import ArukeresoClient, FetchError
from .matcher import best_match
from .parser import build_search_url, parse_search_results

logger = logging.getLogger(__name__)


def find_retail_price(query_text: str, client: ArukeresoClient) -> RetailPrice | None:
    """`query_text` should be the listing's `normalized_key` — already
    stripped of sale-filler words and punctuation, which makes for both a
    cleaner search query and (since `score_match` re-normalizes internally
    anyway) an equivalent basis for the match-confidence score.
    """
    try:
        html = client.get(build_search_url(query_text))
    except FetchError:
        logger.exception("retail lookup failed for %r", query_text)
        return None

    candidates = parse_search_results(html)
    return best_match(query_text, candidates)
