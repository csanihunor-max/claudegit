from __future__ import annotations

import logging

from ..models import Deal

logger = logging.getLogger("hardverapro_arbitrage.deals")


def format_deal(deal: Deal) -> str:
    if deal.basis == "used_median":
        basis_line = (
            f"  reference: {deal.market_reference_price:,.0f} {deal.listing.currency} "
            f"(n={deal.sample_size} other listing(s))\n"
            f"  discount:  {deal.discount_fraction:.0%} vs. other resellers"
        )
    else:
        basis_line = (
            f"  reference: {deal.retail_reference_price:,.0f} {deal.listing.currency} (retail price)\n"
            f"  discount:  {deal.retail_discount_fraction:.0%} vs. retail "
            f"(confidence {deal.retail_match_confidence:.0%})"
        )

    return (
        f"DEAL: {deal.listing.title}\n"
        f"  price:     {deal.listing.price:,.0f} {deal.listing.currency}\n"
        f"{basis_line}\n"
        f"  save:      {deal.savings:,.0f} {deal.listing.currency}\n"
        f"  url:       {deal.listing.url}"
    )


class ConsoleNotifier:
    """Always-on fallback notifier: just logs. Safe default with zero
    configuration, and useful alongside any other notifier for a local
    audit trail.
    """

    def notify(self, deal: Deal) -> None:
        logger.info("\n%s", format_deal(deal))
