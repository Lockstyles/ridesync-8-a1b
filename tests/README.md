# Critical automated tests

These six tests cover the most important Assignment 2 workflows. The assignment asks for a few thoughtful tests rather than a coverage target.

1. Booking succeeds and produces the expected balance/audit result.
2. An active-trip conflict rolls the transaction back and reports the failure.
3. Insufficient balance produces a friendly error.
4. Revenue analytics exposes the 7-day moving average and DENSE_RANK results.
5. The map uses `$geoNear`, enforces the selected radius, and limits the response to 50 vehicles.
6. Reviews analytics uses `$facet` and returns rating, tag, and average-rating results.

Run with:

```bash
uv run pytest tests -q
```
