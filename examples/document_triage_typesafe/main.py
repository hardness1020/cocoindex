import json
import pathlib
from collections.abc import AsyncIterator

import cocoindex as coco
from cocoindex.connectors import localfs
from cocoindex.resources.file import FileLike, PatternFilePathMatcher
from triage import Evaluation, EvaluationConfig, ReviewPolicy, review
from typesafe_sdk import AsyncTypeSafeClient, Choice, Score

# The client is infrastructure, not an input: the API key never enters memo keys or outputs.
JEV_CLIENT = coco.ContextKey[AsyncTypeSafeClient]("jev_client")


@coco.lifespan
async def coco_lifespan(builder: coco.EnvironmentBuilder) -> AsyncIterator[None]:
    # API key from TYPESAFE_API_KEY. The SDK retries 408/429/5xx and connection errors
    # (2 retries, 30s budget per call by default); no extra retry layer here.
    async with AsyncTypeSafeClient(timeout=30.0) as client:
        builder.provide(JEV_CLIENT, client)
        yield


@coco.fn(memo=True)
async def evaluate_document(text: str, config: EvaluationConfig) -> Evaluation:
    client = coco.use_context(JEV_CLIENT)
    response = await client.system_one(
        state=text,
        model=config.model,
        questions={
            "category": Choice(
                instructions=config.category_question, criteria=config.categories
            ),
            "completeness": Score(
                instructions=config.completeness_question,
                criteria=config.completeness_levels,
            ),
        },
    )
    category = response.choices["category"]
    completeness = response.scores["completeness"]
    return Evaluation(
        category=category.choice,
        category_probabilities=dict(category.probabilities),
        category_confidence=category.confidence,
        completeness_score=completeness.score,
        completeness_probabilities={
            str(k): v for k, v in completeness.probabilities.items()
        },
        completeness_confidence=completeness.confidence,
        model_requested=config.model,
        model_reported=response.model,
        revision=config.revision,
    )


@coco.fn(memo=True)
async def process_document(
    file: FileLike,
    sourcedir: pathlib.Path,
    config: EvaluationConfig,
    policy: ReviewPolicy,
    outdir: pathlib.Path,
) -> None:
    relative_path = file.file_path.path.relative_to(sourcedir)
    evaluation = await evaluate_document(await file.read_text(), config)
    verdict = review(evaluation, policy)
    record = {
        "source_path": relative_path.as_posix(),
        "category": evaluation.category,
        "category_probabilities": evaluation.category_probabilities,
        "category_confidence": evaluation.category_confidence,
        "completeness_score": evaluation.completeness_score,
        "completeness_probabilities": evaluation.completeness_probabilities,
        "completeness_confidence": evaluation.completeness_confidence,
        "review_status": verdict.status,
        "review_reasons": verdict.reasons,
        "evaluation": {
            "model_requested": evaluation.model_requested,
            "model_reported": evaluation.model_reported,
            "revision": evaluation.revision,
        },
    }
    localfs.declare_file(
        outdir / relative_path.with_suffix(".json"),
        json.dumps(record, indent=2) + "\n",
        create_parent_dirs=True,
    )


@coco.fn
async def app_main(
    sourcedir: pathlib.Path,
    outdir: pathlib.Path,
    config: EvaluationConfig,
    policy: ReviewPolicy,
) -> None:
    files = localfs.walk_dir(
        sourcedir,
        recursive=True,
        path_matcher=PatternFilePathMatcher(included_patterns=["**/*.md"]),
    )
    await coco.mount_each(
        process_document, files.items(), sourcedir, config, policy, outdir
    )


app = coco.App(
    coco.AppConfig(name="DocumentTriageTypeSafe", max_inflight_components=8),
    app_main,
    sourcedir=pathlib.Path("./data"),
    outdir=pathlib.Path("./output_triage"),
    config=EvaluationConfig(),
    policy=ReviewPolicy(),
)
