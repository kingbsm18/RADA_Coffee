"""TEMPLATE for the real POS adapter. Rename the module and class once the vendor is known.

Nothing here is implemented on purpose: the vendor's endpoints and field names are
unknown, and guessing them would produce wrong credits. To implement it:
1. Get a real sample response (sensitive data masked) and docs/pos_integration.md filled in.
2. Map the vendor fields to ``PosSaleIn`` (use ``app.pos.normalizer`` helpers).
3. Make sure ``external_id`` is unique per sale LINE and that sale edits (paid ->
   voided/refunded) are returned again so R8 can react.
4. Register it in ``app.pos.registry`` and add tests with the real sample as a fixture.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.pos.base import ApiPosAdapter, ParseResult


class YourPosAdapter(ApiPosAdapter):
    name = "your_pos"

    def fetch_sales(
        self, *, site_id: str, since: datetime, until: datetime, tz: ZoneInfo
    ) -> ParseResult:
        raise NotImplementedError("POS vendor not chosen yet; see the module docstring")
