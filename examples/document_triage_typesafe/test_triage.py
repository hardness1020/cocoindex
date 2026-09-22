"""Integration tests for the triage app against a deterministic fake Jev.

Real CocoIndex app, memoization, and file targets; only the HTTP boundary of the
TypeSafe SDK is replaced with an `httpx2.MockTransport`. No API key needed.

Fake answers are driven by a marker line in each test document:
    <!-- jev: category=tutorial p=0.9 level=2 -->
`p` is the probability of the chosen category; `level` is the rubric level that
gets 0.8 of the completeness mass (the next level gets 0.2). A document without
a marker is "other" at p=0.5, level 1.

Run: uv run pytest examples/document_triage_typesafe   (from the repo root)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any

import cocoindex as coco
import httpx2
import main
import pytest
from triage import EvaluationConfig, ReviewPolicy
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

_MARKER = re.compile(r"<!-- jev: category=(\w+) p=([\d.]+) level=(\d+) -->")


class FakeJev:
    """Deterministic stand-in for api.typesafe.ai. Counts HTTP attempts and logical evaluations."""

    def __init__(self, fail_titles: set[str] | None = None) -> None:
        self.fail_titles = fail_titles or set()
        self.http_attempts = 0
        self.evaluations = (
            0  # first attempts only; retries carry X-TypeSafe-Retry-Count
        )
        self.evaluated_titles: list[str] = []

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        title = body["state"].splitlines()[0]
        self.http_attempts += 1
        if "x-typesafe-retry-count" not in request.headers:
            self.evaluations += 1
            self.evaluated_titles.append(title)
        if title in self.fail_titles:
            return httpx2.Response(500, json={"detail": "fake outage"})

        m = _MARKER.search(body["state"])
        category, p, level = (m[1], float(m[2]), int(m[3])) if m else ("other", 0.5, 1)
        categories = list(body["questions"]["category"]["criteria"])
        levels = body["questions"]["completeness"]["criteria"]
        assert category in categories

        cat_probs = {c: (1 - p) / (len(categories) - 1) for c in categories}
        cat_probs[category] = p
        level_probs = {str(i): 0.0 for i in range(len(levels))}
        level_probs[str(level)] = 0.8
        level_probs[str(min(level + 1, len(levels) - 1))] += 0.2
        score = sum(int(k) * v for k, v in level_probs.items())

        def confidence(probs: dict[str, float]) -> float:
            n = len(probs)
            return (n * max(probs.values()) - 1) / (n - 1)

        return httpx2.Response(
            200,
            json={
                "model": "jev-fake-1.0.0",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {
                    "category": {
                        "type": "choice",
                        "choice": category,
                        "confidence": confidence(cat_probs),
                        "probabilities": cat_probs,
                    },
                    "completeness": {
                        "type": "score",
                        "score": score,
                        "confidence": confidence(level_probs),
                        "legend": {str(i): text for i, text in enumerate(levels)},
                        "probabilities": level_probs,
                    },
                },
            },
        )


def write_doc(
    srcdir: pathlib.Path, rel: str, category: str, p: float, level: int, body: str = ""
) -> None:
    path = srcdir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    title = pathlib.PurePath(rel).stem
    path.write_text(
        f"# {title}\n<!-- jev: category={category} p={p} level={level} -->\n{body}\n"
    )


def read_out(outdir: pathlib.Path, rel: str) -> dict[str, Any]:
    return json.loads((outdir / rel).with_suffix(".json").read_text())  # type: ignore[no-any-return]


def out_files(outdir: pathlib.Path) -> set[str]:
    return {p.relative_to(outdir).as_posix() for p in outdir.rglob("*.json")}


class Harness:
    """One CocoIndex environment, one App, and one fake Jev, shared by every run in a test.

    Tests change settings the way a user would edit `main.py` between runs: by mutating
    `config` / `policy` in place. The App holds those objects and re-reads them per update.
    """

    def __init__(self, tmp: pathlib.Path) -> None:
        self.tmp = tmp
        self.src = tmp / "src"
        self.out = tmp / "out"
        self.fake = FakeJev()
        self.config = EvaluationConfig()
        self.policy = ReviewPolicy()
        self._app: coco.App[Any, None] | None = None

    def seed(self) -> None:
        write_doc(
            self.src, "guides/setup.md", "tutorial", 0.9, 2
        )  # score 2.2, conf 0.867
        write_doc(self.src, "reference/setup.md", "reference", 0.9, 3)  # score 3.0
        write_doc(
            self.src, "notes/roadmap.md", "other", 0.5, 1
        )  # score 1.2, conf 0.333

    def _get_app(self) -> coco.App[Any, None]:
        if self._app is None:
            env = coco.Environment(coco.Settings.from_env(db_path=self.tmp / "db"))
            client = AsyncTypeSafeClient(
                api_key="fake-key",
                transport=self.fake.transport(),
                retry=RetryPolicy(max_retries=2, backoff_initial=0, backoff_max=0),
            )
            env.context_provider.provide(main.JEV_CLIENT, client)
            self._app = coco.App(
                coco.AppConfig(name="DocumentTriageTest", environment=env),
                main.app_main,
                sourcedir=self.src,
                outdir=self.out,
                config=self.config,
                policy=self.policy,
            )
        return self._app

    async def run(self) -> coco.ComponentStats:
        """One catch-up run. Returns the per-document component stats (the non-memoized
        root component always re-runs, so its stats are not interesting)."""
        handle = self._get_app().update()
        await handle.result()
        stats = handle.stats()
        assert stats is not None
        return stats.by_component["process_document"]


@pytest.fixture
def h(tmp_path: pathlib.Path) -> Harness:
    harness = Harness(tmp_path)
    harness.seed()
    return harness


@pytest.mark.asyncio
async def test_first_run_then_unchanged_rerun(h: Harness) -> None:
    stats = await h.run()
    assert h.fake.evaluations == 3 and h.fake.http_attempts == 3
    assert stats.num_errors == 0
    assert out_files(h.out) == {
        "guides/setup.json",
        "reference/setup.json",
        "notes/roadmap.json",
    }

    setup = read_out(h.out, "guides/setup.md")
    assert setup["source_path"] == "guides/setup.md"
    assert setup["category"] == "tutorial"
    assert setup["category_probabilities"]["tutorial"] == 0.9
    assert setup["completeness_score"] == pytest.approx(2.2)
    assert setup["review_status"] == "ready" and setup["review_reasons"] == []
    assert setup["evaluation"] == {
        "model_requested": "jev-latest",
        "model_reported": "jev-fake-1.0.0",
        "revision": 1,
    }
    roadmap = read_out(h.out, "notes/roadmap.md")
    assert roadmap["review_status"] == "needs_review"
    assert roadmap["review_reasons"] == [
        "low_classification_confidence",
        "insufficient_completeness",
    ]

    before = {f: (h.out / f).read_bytes() for f in out_files(h.out)}
    stats = await h.run()
    assert h.fake.evaluations == 3, "unchanged rerun must not call Jev"
    assert stats.num_reprocesses == 0
    assert {f: (h.out / f).read_bytes() for f in out_files(h.out)} == before


@pytest.mark.asyncio
async def test_edit_one_document_reevaluates_only_it(h: Harness) -> None:
    await h.run()
    write_doc(h.src, "guides/setup.md", "reference", 0.9, 3, body="rewritten")
    await h.run()
    assert h.fake.evaluations == 4
    assert h.fake.evaluated_titles[-1] == "# setup"
    assert read_out(h.out, "guides/setup.md")["category"] == "reference"
    assert read_out(h.out, "reference/setup.md")["category"] == "reference"


@pytest.mark.asyncio
async def test_add_then_delete_document(h: Harness) -> None:
    await h.run()
    write_doc(h.src, "guides/deploy.md", "tutorial", 0.8, 1)
    await h.run()
    assert h.fake.evaluations == 4 and h.fake.evaluated_titles[-1] == "# deploy"
    assert "guides/deploy.json" in out_files(h.out)

    (h.src / "guides/deploy.md").unlink()
    await h.run()
    assert h.fake.evaluations == 4, "deleting must not re-evaluate the others"
    assert out_files(h.out) == {
        "guides/setup.json",
        "reference/setup.json",
        "notes/roadmap.json",
    }


@pytest.mark.asyncio
async def test_question_definition_change_reevaluates_all(h: Harness) -> None:
    await h.run()
    h.config.categories["tutorial"] = "A how-to guide with numbered steps."
    await h.run()
    assert h.fake.evaluations == 6

    h.config.completeness_levels[0] = "Empty stub."
    await h.run()
    assert h.fake.evaluations == 9


@pytest.mark.asyncio
async def test_model_or_revision_change_reevaluates_all(h: Harness) -> None:
    await h.run()
    h.config.model = "jev-1.13.0"
    await h.run()
    assert h.fake.evaluations == 6
    assert (
        read_out(h.out, "guides/setup.md")["evaluation"]["model_requested"]
        == "jev-1.13.0"
    )

    h.config.revision = 2
    await h.run()
    assert h.fake.evaluations == 9
    assert read_out(h.out, "guides/setup.md")["evaluation"]["revision"] == 2


@pytest.mark.asyncio
async def test_threshold_only_change_reuses_evaluations(h: Harness) -> None:
    await h.run()
    assert read_out(h.out, "guides/setup.md")["review_status"] == "ready"

    h.policy.min_completeness = 2.5
    stats = await h.run()
    assert h.fake.evaluations == 3, "policy change must not call Jev"
    assert stats.num_reprocesses == 3, "every document re-applies the policy"
    setup = read_out(h.out, "guides/setup.md")
    assert setup["review_status"] == "needs_review"
    assert setup["review_reasons"] == ["insufficient_completeness"]
    assert read_out(h.out, "reference/setup.md")["review_status"] == "ready"

    h.policy.min_completeness = 2.0
    h.policy.min_category_confidence = 0.9
    await h.run()
    assert h.fake.evaluations == 3
    assert read_out(h.out, "guides/setup.md")["review_reasons"] == [
        "low_classification_confidence"
    ]


@pytest.mark.asyncio
async def test_same_filename_in_different_dirs(h: Harness) -> None:
    await h.run()
    a = read_out(h.out, "guides/setup.md")
    b = read_out(h.out, "reference/setup.md")
    assert (a["source_path"], a["category"]) == ("guides/setup.md", "tutorial")
    assert (b["source_path"], b["category"]) == ("reference/setup.md", "reference")


@pytest.mark.asyncio
async def test_api_error_is_visible_and_recovers(h: Harness) -> None:
    await h.run()
    write_doc(h.src, "guides/setup.md", "tutorial", 0.9, 3, body="v2")
    stale = read_out(h.out, "guides/setup.md")
    write_doc(h.src, "guides/new.md", "tutorial", 0.9, 3)

    h.fake.fail_titles = {"# setup", "# new"}
    attempts_before = h.fake.http_attempts
    stats = await h.run()
    assert stats.num_errors == 2
    assert h.fake.evaluations == 5, "two logical evaluations attempted"
    assert h.fake.http_attempts - attempts_before == 6, (
        "3 HTTP attempts each (SDK retries)"
    )
    assert "guides/new.json" not in out_files(h.out), (
        "no fabricated output for a failed new doc"
    )
    # Processing failed before submit: the previous run's output stays as-is.
    assert read_out(h.out, "guides/setup.md") == stale

    h.fake.fail_titles = set()
    stats = await h.run()
    assert stats.num_errors == 0
    assert h.fake.evaluations == 7, "only the two failed documents are retried"
    assert read_out(h.out, "guides/setup.md")["completeness_score"] == pytest.approx(
        3.0
    )
    assert read_out(h.out, "guides/new.md")["category"] == "tutorial"


@pytest.mark.asyncio
async def test_shipped_samples(tmp_path: pathlib.Path) -> None:
    h = Harness(tmp_path)
    shutil.copytree(pathlib.Path(__file__).parent / "data", h.src)
    stats = await h.run()
    assert stats.num_errors == 0 and h.fake.evaluations == 11
    assert len(out_files(h.out)) == 11
    assert {"guides/setup.json", "reference/setup.json"} <= out_files(h.out)


def _run_in_subprocess(tmp: pathlib.Path, min_completeness: float) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, __file__, str(tmp), str(min_completeness)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])  # type: ignore[no-any-return]


def test_reuse_across_processes(tmp_path: pathlib.Path) -> None:
    h = Harness(tmp_path)
    h.seed()
    first = _run_in_subprocess(tmp_path, 2.0)
    assert first == {"evaluations": 3, "num_errors": 0, "num_reprocesses": 0}
    assert read_out(h.out, "guides/setup.md")["review_status"] == "ready"

    again = _run_in_subprocess(tmp_path, 2.0)
    assert again == {"evaluations": 0, "num_errors": 0, "num_reprocesses": 0}

    raised = _run_in_subprocess(tmp_path, 2.5)
    assert raised == {"evaluations": 0, "num_errors": 0, "num_reprocesses": 3}
    assert read_out(h.out, "guides/setup.md")["review_reasons"] == [
        "insufficient_completeness"
    ]


if __name__ == "__main__":
    # Subprocess entry for test_reuse_across_processes: one run, fresh process, shared db.
    parser = argparse.ArgumentParser()
    parser.add_argument("tmp", type=pathlib.Path)
    parser.add_argument("min_completeness", type=float)
    args = parser.parse_args()

    async def _main() -> None:
        harness = Harness(args.tmp)
        harness.policy.min_completeness = args.min_completeness
        stats = await harness.run()
        print(
            json.dumps(
                {
                    "evaluations": harness.fake.evaluations,
                    "num_errors": stats.num_errors,
                    "num_reprocesses": stats.num_reprocesses,
                }
            )
        )

    import asyncio

    asyncio.run(_main())
