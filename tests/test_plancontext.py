"""`lanes plan context` and the `/lanes-plan` command template."""

from __future__ import annotations

import pytest
from conftest import git

from lanes.cli import main
from lanes.install import init_repo
from lanes.plancontext import build_context, clusters, hub_candidates, import_graph, is_test

FILES = {
    # Python: a small package in a src layout, plus tests
    "src/shop/__init__.py": "",
    "src/shop/models.py": "class Item: ...\n",
    "src/shop/cart/__init__.py": "",
    "src/shop/cart/add.py": "from ..models import Item\nfrom . import totals\nimport json\n",
    "src/shop/cart/totals.py": "from shop.models import Item\n",
    "src/shop/search/index.py": "from shop.models import Item\nfrom .rank import score\n",
    "src/shop/search/rank.py": "def score(): ...\n",
    "src/shop/emails/send.py": "from shop.models import Item\n\ndef f():\n    from shop.cart import totals\n",
    "tests/conftest.py": "",
    "tests/test_cart.py": "from conftest import x\nfrom shop.cart.add import add\nfrom shop.models import Item\n",
    # JS/TS
    "web/api.ts": "export const get = () => 1\n",
    "web/pages/home.tsx": "import { get } from '../api'\nimport Button from './Button'\n",
    "web/pages/Button.tsx": "export default 1\n",
    "web/pages/about.tsx": "const api = require('../api.js')\nexport * from './Button'\n",
    "web/util/index.ts": "export const u = 1\n",
    "web/pages/home.test.tsx": "import home from './home'\n",
    "web/lazy.ts": "const m = import('./util')\nimport 'react'\n",
    "README.md": "# shop\n",
}


@pytest.fixture
def shop(repo):
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    (repo / ".lanes" / "PLAN.md").write_text("# Plan\n<!-- hidden note -->\n## Team\n- shaurya: the API\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "shop")
    return repo


def test_import_graph(shop):
    g = import_graph(shop, sorted(FILES))
    assert g["src/shop/cart/add.py"] == {"src/shop/models.py", "src/shop/cart/totals.py"}  # relative imports; json is external
    assert g["src/shop/cart/totals.py"] == {"src/shop/models.py"}  # absolute import through the src/ root
    assert g["src/shop/emails/send.py"] == {"src/shop/models.py", "src/shop/cart/totals.py"}  # import inside a function
    assert g["tests/test_cart.py"] == {"tests/conftest.py", "src/shop/cart/add.py", "src/shop/models.py"}
    assert g["web/pages/home.tsx"] == {"web/api.ts", "web/pages/Button.tsx"}
    assert g["web/pages/about.tsx"] == {"web/api.ts", "web/pages/Button.tsx"}  # require + .js -> .ts, export from
    assert g["web/lazy.ts"] == {"web/util/index.ts"}  # dynamic import of a folder index; bare 'react' ignored


def test_hubs_and_clusters(shop):
    g = import_graph(shop, sorted(FILES))
    hubs = hub_candidates(g)
    assert [h[0] for h in hubs] == ["src/shop/models.py"]  # used by cart, search and emails (tests don't count)
    comps = clusters(g, {h[0] for h in hubs})
    assert ["src/shop/cart/add.py", "src/shop/cart/totals.py", "src/shop/emails/send.py"] in comps
    assert ["src/shop/search/index.py", "src/shop/search/rank.py"] in comps
    assert not any("tests/test_cart.py" in c for c in comps)


@pytest.mark.parametrize(
    "path, expected",
    [("tests/test_x.py", True), ("pkg/x_test.py", True), ("web/a.test.tsx", True), ("web/__tests__/a.ts", True),
     ("src/conftest.py", True), ("src/testing_utils.py", False), ("src/contest.py", False)],
)
def test_is_test(path, expected):
    assert is_test(path) is expected


def test_build_context_sections(shop):
    text = build_context(shop, "friend")
    assert "based_on: " in text and "only the plan owner may write a proposal" in text
    assert "- shaurya: the API" in text and "hidden note" not in text
    assert "feature: checkout-v1" in text
    assert "### .lanes/contracts/cart-api.md (id cart-api, owner shaurya)" in text and "addItem" in text
    assert "- src/shop/models.py" in text and ".lanes/plan.yaml\n" not in text.split("## Files")[1].split("##")[0]
    assert "src/shop/cart/add.py -> src/shop/cart/totals.py, src/shop/models.py" in text
    assert "- src/shop/models.py (imported by 4 files from 4 areas)" in text
    assert "## Current ownership by area" in text
    assert "plan owner: shaurya · you: shaurya\n" in build_context(shop, "shaurya")


def test_cli_plan_context(shop, capsys, monkeypatch):
    monkeypatch.chdir(shop)
    monkeypatch.setenv("LANES_USER", "shaurya")
    assert main(["plan", "context"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Lanes planning context") and "## Import graph" in out


def test_init_installs_lanes_plan_command(tmp_path):
    git(tmp_path, "init", "-q")
    init_repo(tmp_path, member="me", runner="uv-local", git_hook=False)
    text = (tmp_path / ".claude" / "commands" / "lanes-plan.md").read_text()
    assert "Bash(uv run lanes plan context:*)" in text and "`uv run lanes plan accept`" in text
    assert "$ARGUMENTS" in text and "$lanes" not in text
    assert "Never write `.lanes/plan.yaml`" in text and "Edit(.lanes/proposal/**)" in text
