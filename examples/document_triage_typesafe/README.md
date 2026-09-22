# Document Triage with TypeSafe Jev

Classify a folder of Markdown documents, score how complete each one is, and route
each document to `ready` or `needs_review`, one JSON file per source document.

[TypeSafe Jev](https://docs.typesafe.ai/) answers the two typed questions per document
(a `Choice` for the category, a `Score` against a written completeness rubric) and
returns probabilities plus a confidence value. CocoIndex owns everything around that
call: it walks the source folder, memoizes each Jev evaluation, applies the Python
review policy, and creates, updates, and deletes the JSON outputs as sources change.
No database, no vector store; one API key.

## How it works

The pipeline is split into two stages that are cached independently
([`main.py`](main.py), settings in [`triage.py`](triage.py)):

```python
@coco.fn(memo=True)
async def evaluate_document(text: str, config: EvaluationConfig) -> Evaluation:
    client = coco.use_context(JEV_CLIENT)
    response = await client.system_one(
        state=text,
        model=config.model,
        questions={
            "category": Choice(instructions=config.category_question, criteria=config.categories),
            "completeness": Score(instructions=config.completeness_question, criteria=config.completeness_levels),
        },
    )
    ...  # raw probabilities, confidence, and the model that answered

@coco.fn(memo=True)
async def process_document(file: FileLike, sourcedir, config: EvaluationConfig, policy: ReviewPolicy, outdir) -> None:
    evaluation = await evaluate_document(await file.read_text(), config)
    verdict = review(evaluation, policy)          # plain Python thresholds
    localfs.declare_file(outdir / relative_path.with_suffix(".json"), json.dumps(record), create_parent_dirs=True)
```

1. **Evaluation** (`evaluate_document`): document text plus `EvaluationConfig` (model,
   `revision`, question wording, category descriptions, rubric levels) go in; Jev's raw
   judgment comes out. Every field of `EvaluationConfig` is a function argument, so
   changing any of them invalidates the memo. The Jev client comes from a
   `ContextKey` without change detection, so the API key is never part of a memo key or
   an output.
2. **Review policy** (`review` in `triage.py`): the stored evaluation plus
   `ReviewPolicy` thresholds produce `review_status` and `review_reasons`. Reasons are
   rule codes from Python (`low_classification_confidence`,
   `insufficient_completeness`), not model explanations. Thresholds are never sent to
   Jev.

`process_document` is the per-file component. Its memo key covers the file content,
both config objects, and the output folder. Change only a threshold and every
component re-runs `review`, but `evaluate_document` hits its own memo, so Jev is not
called. Change the file, the questions, the model, or `revision`, and the evaluation
re-runs for the affected documents.

Outputs mirror the source tree (`guides/setup.md` becomes `guides/setup.json`), so a
file with the same name in another folder never collides.

## Run it

Run commands from this directory:

```sh
cd examples/document_triage_typesafe
```

**1. Install:**

```sh
pip install -e .
```

**2. Configure** the TypeSafe API key:

```sh
cp .env.example .env     # set TYPESAFE_API_KEY
```

**3. Run the pipeline** on the sample docs in `data/`:

```sh
cocoindex update main
```

Each `.md` under `data/` becomes a JSON file under `output_triage/`:

```sh
cat output_triage/guides/setup.json
```

```json
{
  "source_path": "guides/setup.md",
  "category": "tutorial",
  "category_probabilities": { "tutorial": 0.93, "troubleshooting": 0.02, "reference": 0.04, "other": 0.01 },
  "category_confidence": 0.9,
  "completeness_score": 2.7,
  "completeness_probabilities": { "0": 0.0, "1": 0.05, "2": 0.2, "3": 0.75 },
  "completeness_confidence": 0.66,
  "review_status": "ready",
  "review_reasons": [],
  "evaluation": { "model_requested": "jev-latest", "model_reported": "jev-1.13.0", "revision": 1 }
}
```

(Values are illustrative; the sample set includes stubs, a truncated guide, and
documents that sit between categories, so expect some `needs_review` results.)

**4. Try incremental updates.** Edit, add, or delete a file under `data/` and run
`cocoindex update main` again: only the changed file is re-evaluated, a new file gets
one evaluation, and a deleted file's JSON is removed without touching the others.

**5. Change the settings** in `triage.py` and re-run:

- `ReviewPolicy` thresholds only: every document's `review_status` is recomputed from
  the stored evaluations. Zero Jev calls.
- Question wording, category descriptions, rubric levels, or `model`: every document
  is re-evaluated.
- `revision`: bump it to force re-evaluation with otherwise identical settings.

## Tests

`test_triage.py` runs the real app against temporary source and output folders with a
persistent state database. Only the SDK's HTTP transport is replaced by a
deterministic fake (`httpx2.MockTransport`) that counts HTTP attempts separately from
logical evaluations, so the suite needs no API key:

```sh
pip install pytest pytest-asyncio
pytest test_triage.py
```

It covers first run, unchanged re-run, edit, add, delete, question and model changes,
threshold-only changes (including across separate Python processes sharing one state
database), same-named files in different folders, and an API outage (no fabricated
output, error counted, recovery re-evaluates only the failed files).

**Real API smoke test** (needs `TYPESAFE_API_KEY`; costs a few requests):

```sh
cocoindex update main            # 11 evaluations
cocoindex update main            # 0 evaluations: memo hits
```

Set `TYPESAFE_LOG_LEVEL=info` to see each request the SDK sends.

## Limitations

- **Hosted model aliases move.** `jev-latest` resolves to a new release when one ships,
  and CocoIndex cannot observe that: memoized evaluations stay valid until an input
  changes. Each output records `model_reported`, the versioned ID that actually
  answered. To re-evaluate after an alias moves, bump `revision`. To avoid the problem,
  pin a versioned model such as `jev-1.13.0` (TypeSafe documents versioned IDs as
  stable) and move on your own schedule.
- **Confidence is not accuracy.** `confidence` is computed from the shape of the
  probability distribution (1.0 when all mass is on one answer, 0 when uniform). It says
  how peaked the answer is, not how likely it is to be correct. The default thresholds
  are demonstration values; tune them on your own documents.
- **Retries.** The SDK retries 408/429/5xx responses and connection errors (2 retries,
  30s budget per call). A document whose evaluation still fails is logged, counted in
  the update stats, and produces no output; its previous JSON, if any, is left as is.
  The next run re-evaluates only the failed documents.
