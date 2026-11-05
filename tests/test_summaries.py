import pytest

from lanes.summaries import derive_open, derive_why


@pytest.mark.parametrize(
    "message, expected",
    [
        # Regression from the live run: '->' and '#' inside a sentence must survive
        ("I added `getItem(id: str) -> Item  # 404 if missing` to the contract.", "I added getItem(id: str) -> Item  # 404 if missing to the contract."),
        ("Renamed **cart_total** to `order_total`.", "Renamed cart_total to order_total."),
        ("## Summary\nFixed the tax rounding bug. Added tests. Also refactored.", "Fixed the tax rounding bug. Added tests."),
        ("> Quoted intro line that is long enough to stand on its own as the why.", "Quoted intro line that is long enough to stand on its own as the why."),
        ("- Added [the docs](docs/x.md) for setup and some more words here to be long.", "Added the docs for setup and some more words here to be long."),
        ("```py\ncode\n```\nDone.", "Done."),
        ("", ""),
    ],
)
def test_derive_why(message, expected):
    assert derive_why(message) == expected


def test_derive_why_is_capped():
    assert len(derive_why("word " * 200)) <= 220


def test_derive_open_finds_questions():
    msg = "Did the thing.\nShould totals include tax?\n```\nis this code?\n```\nWant me to add tests?"
    assert derive_open(msg) == "Should totals include tax?; Want me to add tests?"
