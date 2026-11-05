import pytest

from lanes.redact import MASK, is_env_file, redact

SECRETS = [
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnop",
    "AKIAIOSFODNN7EXAMPLE",
    "xoxb-1234567890-abcdefghij",
    "AIzaSyA-1234567890abcdefghijklmnopqrstu",
    "sk_live_51HabcdefghijklmnopQRST",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_token_shapes(secret):
    out = redact(f"we used {secret} here")
    assert secret not in out and MASK in out


def test_private_key_block():
    text = "before\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\nafter"
    out = redact(text)
    assert "b3BlbnNzaC1rZXktdjEAAAAA" not in out and out.startswith("before") and out.endswith("after")


@pytest.mark.parametrize(
    "line, leaked",
    [
        ("DATABASE_URL=postgres://u:hunter2@db/x", "hunter2"),
        ("export STRIPE_KEY=abc123def456", "abc123def456"),
        ('api_key = "abcdef123456"', "abcdef123456"),
        ("password: 'correct horse battery'", "correct horse"),
        ("client_secret=Zm9vYmFyYmF6cXV4MTIz", "Zm9vYmFyYmF6cXV4MTIz"),
        ("Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
        ("see https://admin:s3cretpass@example.com/x", "s3cretpass"),
    ],
)
def test_assignments_and_urls(line, leaked):
    out = redact(line)
    assert leaked not in out and MASK in out


@pytest.mark.parametrize(
    "safe",
    [
        "Renamed addItem(sku, qty) to addToCart(sku, qty, note=None)",
        "def login(username: str, password: str) -> Token:",
        "api_key: Optional[str] = None",
        "Changed CartTotal.tax from float to Decimal",
    ],
)
def test_ordinary_code_is_untouched(safe):
    assert redact(safe) == safe


@pytest.mark.parametrize(
    "name, expected",
    [(".env", True), (".env.local", True), ("config/prod.env", True), (".env.example", False), ("env.py", False)],
)
def test_is_env_file(name, expected):
    assert is_env_file(name) is expected
