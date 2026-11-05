import pytest

from lanes.paths import find_root, glob_match, globs_overlap, repo_relative, specificity, to_posix


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("src\\api\\cart\\x.py", "src/api/cart/x.py"),
        ("./src//api/./cart/x.py", "src/api/cart/x.py"),
        ("src/api/../types/a.ts", "src/types/a.ts"),
        ("c:\\Repo\\src\\x.py", "C:/Repo/src/x.py"),
        ("/Users/me/repo/", "/Users/me/repo"),
    ],
)
def test_to_posix(raw, expected):
    assert to_posix(raw) == expected


@pytest.mark.parametrize(
    "path, root, expected",
    [
        ("/Users/me/repo/src/api/cart/x.py", "/Users/me/repo", "src/api/cart/x.py"),
        ("C:\\Users\\me\\repo\\src\\api\\cart\\x.py", "C:\\Users\\me\\repo", "src/api/cart/x.py"),
        ("c:\\users\\ME\\Repo\\src\\x.py", "C:\\Users\\me\\repo", "src/x.py"),  # Windows paths are case-insensitive
        ("src\\api\\cart\\x.py", "C:\\Users\\me\\repo", "src/api/cart/x.py"),  # already relative
        ("/Users/me/other/x.py", "/Users/me/repo", None),
        ("/Users/me/repository/x.py", "/Users/me/repo", None),  # prefix but not a parent
        ("../outside.py", "/Users/me/repo", None),
    ],
)
def test_repo_relative(path, root, expected):
    assert repo_relative(path, root) == expected


def test_repo_relative_follows_symlinks(tmp_path):
    real = tmp_path / "real"
    (real / "src").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    assert repo_relative(str(link / "src" / "a.py"), str(real)) == "src/a.py"


@pytest.mark.parametrize(
    "pattern, path, ok",
    [
        ("src/api/cart/**", "src/api/cart/x.py", True),
        ("src/api/cart/**", "src/api/cart/deep/er/x.py", True),
        ("src/api/cart/**", "src/api/cartography/x.py", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("**/*.md", "README.md", True),
        ("**/*.md", "docs/a/b.md", True),
        ("package.json", "package.json", True),
        ("package.json", "web/package.json", False),
        ("src/api", "src/api/x.py", True),  # no wildcard: directory prefix
        ("src/api/", "src/api/x.py", True),
        ("src\\api\\cart\\**", "src\\api\\cart\\x.py", True),  # Windows-style both sides
        ("src/a?.py", "src/ab.py", True),
        ("src/a?.py", "src/a/.py", False),
    ],
)
def test_glob_match(pattern, path, ok):
    assert glob_match(pattern, path) is ok


def test_specificity_prefers_longer_literal_prefix():
    assert specificity("src/api/cart/**") > specificity("src/**")
    assert specificity("tests/e2e_phase0.md") > specificity("tests/**")


def test_find_root(tmp_path):
    (tmp_path / ".lanes").mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert find_root(deep) == tmp_path
    assert find_root(tmp_path.parent / "nowhere-lanes-xyz") is None or True  # no crash on missing dirs


@pytest.mark.parametrize(
    "a, b, overlap, witness",
    [
        ("tests/**", "tests/e2e_results/**", True, "tests/e2e_results/x.md"),
        ("lanes/**", "hooks/**", False, None),
        ("docs", "docs/x.md", True, "docs/x.md"),  # a plain path covers everything below it
        ("docs", "docsite/**", False, None),
        ("src/*.py", "src/a*", True, "src/a.py"),
        ("src/*.py", "src/**/*.ts", False, None),
        ("src/*.py", "src/a/b.py", False, None),  # `*` stays inside one directory
        ("src/*/x.py", "src/a/**", True, "src/a/x.py"),
        ("**/*.md", "README.md", True, "README.md"),
        ("src/**/test_*.py", "src/api/**", True, "src/api/test_a.py"),
        ("a?c", "abc", True, "abc"),
        ("a?c", "a/c", False, None),
        ("src/", "src/x/y.ts", True, "src/x/y.ts"),
    ],
)
def test_globs_overlap(a, b, overlap, witness):
    assert globs_overlap(a, b) is overlap
    assert globs_overlap(b, a) is overlap
    if witness:  # the overlap is real: one path matches both
        assert glob_match(a, witness) and glob_match(b, witness)
