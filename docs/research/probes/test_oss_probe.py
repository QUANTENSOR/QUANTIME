"""Self-test for oss_probe failure classification. No network access.

Run: python docs/research/probes/test_oss_probe.py
Exits non-zero if any check fails.

Regression note: GitHub sends rate-limit headers capitalised
("X-RateLimit-Remaining"). An earlier version stored them via dict(...) and
looked them up in lowercase, so every rate-limit 403 was misreported as a plain
"forbidden". The checks below use the real capitalisation via HTTPMessage.
"""

from __future__ import annotations

import contextlib
import email.message
import importlib.util
import io
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("oss_probe", os.path.join(HERE, "oss_probe.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

FAILED: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED.append(name)


def msg(pairs: dict | None = None) -> email.message.Message:
    """Build a real HTTPMessage so lookups are case-insensitive, as urllib gives us."""
    m = email.message.Message()
    for k, v in (pairs or {}).items():
        m[k] = v
    return m


def raiser(code: int, headers: dict | None = None):
    def fake(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "err", msg(headers), None)
    return fake


def expect_error(fn, exc_type) -> Exception | None:
    try:
        fn()
    except exc_type as e:
        return e
    except Exception:
        return None
    return None


def main() -> int:
    orig = p.urllib.request.urlopen
    try:
        p.urllib.request.urlopen = raiser(404)
        check("404 -> NotFound", expect_error(lambda: p._request("https://x/y", None), p.NotFound) is not None)

        p.urllib.request.urlopen = raiser(401)
        e = expect_error(lambda: p._request("https://x/y", None), p.ProbeError)
        check("401 -> ProbeError naming credentials", e is not None and "credential" in str(e).lower())

        # Real GitHub capitalisation — the regression this file exists for.
        p.urllib.request.urlopen = raiser(403, {"X-RateLimit-Remaining": "0",
                                                "X-RateLimit-Reset": "1790000000"})
        e = expect_error(lambda: p._request("https://x/y", None), p.ProbeError)
        check("403 + capitalised headers -> rate-limited", e is not None and "rate-limited" in str(e))
        check("rate-limit message names GITHUB_TOKEN", e is not None and "GITHUB_TOKEN" in str(e))

        p.urllib.request.urlopen = raiser(403, {"X-RateLimit-Remaining": "57"})
        e = expect_error(lambda: p._request("https://x/y", None), p.ProbeError)
        check("403 with quota left -> not rate-limit", e is not None and "not rate-limit" in str(e))

        p.urllib.request.urlopen = raiser(500)
        e = expect_error(lambda: p._request("https://x/y", None), p.ProbeError)
        check("500 -> ProbeError", e is not None and "HTTP 500" in str(e))

        def neterr(req, timeout=None):
            raise urllib.error.URLError("dns boom")
        p.urllib.request.urlopen = neterr
        e = expect_error(lambda: p._request("https://x/y", None), p.ProbeError)
        check("network error -> ProbeError", e is not None and "network error" in str(e))

        # A non-404 failure must never be recorded as an absent repo.
        p.FAILURES.clear()
        p.urllib.request.urlopen = raiser(401)
        row = p.probe_repo("a/b", None)
        check("401 row is probe_failed, not absent", row["status"] == "probe_failed")
        check("401 registers a failure", len(p.FAILURES) == 1)

        p.FAILURES.clear()
        p.urllib.request.urlopen = raiser(404)
        row = p.probe_repo("a/b", None)
        check("404 row is absent_404", row["status"] == "absent_404")
        check("404 registers no failure", len(p.FAILURES) == 0)

        # Exit code and provenance fields.
        p.FAILURES.clear()
        saved_repos, saved_pypi = p.REPOS, p.PYPI_FOR_REPO
        p.REPOS, p.PYPI_FOR_REPO = ["a/b"], {}
        p.urllib.request.urlopen = raiser(403, {"X-RateLimit-Remaining": "0"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = p.main()
        p.REPOS, p.PYPI_FOR_REPO = saved_repos, saved_pypi
        check("main() non-zero when a probe fails", rc != 0)
        out = json.loads(buf.getvalue())
        check("output records auth_mode", out["auth_mode"] == "anonymous")
        check("output records failures", len(out["failures"]) == 1)

        # Token handling: stripped, no default, blank treated as absent.
        os.environ["GITHUB_TOKEN"] = "  abc  "
        check("token is stripped", p._token() == "abc")
        os.environ["GITHUB_TOKEN"] = "   "
        check("blank token -> None", p._token() is None)
        del os.environ["GITHUB_TOKEN"]
        check("absent token -> None (no default)", p._token() is None)

        # Link header parsing drives the commit count.
        link = ('<https://api.github.com/r?page=2>; rel="next", '
                '<https://api.github.com/r?page=7>; rel="last"')
        check("Link rel=last parsed", p._parse_link_last(msg({"Link": link})) == 7)
        check("no Link header -> None", p._parse_link_last(msg()) is None)
    finally:
        p.urllib.request.urlopen = orig

    print(f"\n{len(FAILED)} failing check(s)" + (": " + ", ".join(FAILED) if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
