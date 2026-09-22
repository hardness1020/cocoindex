"""Evaluation settings, the Jev result record, and the Python review policy."""

from __future__ import annotations

from dataclasses import dataclass, field

import cocoindex as coco


@dataclass
class EvaluationConfig:
    """Everything that shapes what Jev is asked. Changing any field re-evaluates every document."""

    model: str = "jev-latest"
    # Bump to force re-evaluation without changing anything else, e.g. after `jev-latest`
    # moved to a new release server-side (CocoIndex cannot observe that).
    revision: int = 1
    category_question: str = "What kind of document is this?"
    categories: dict[str, str] = field(
        default_factory=lambda: {
            "tutorial": "Step-by-step instructions that walk the reader through completing a task, in order.",
            "troubleshooting": "Describes a specific problem, error, or symptom and how to diagnose or fix it.",
            "reference": "Describes commands, options, parameters, or APIs for lookup, not in task order.",
            "other": "Anything else: notes, plans, announcements, or content that fits none of the above.",
        }
    )
    completeness_question: str = (
        "How complete is this document for its apparent purpose?"
    )
    completeness_levels: list[str] = field(
        default_factory=lambda: [
            "Placeholder or stub: a title with little or no usable content.",
            "Partial: covers some of the topic but has obvious gaps, unfinished sections, or TODOs.",
            "Mostly complete: a reader can accomplish the purpose, with minor gaps.",
            "Complete: covers the topic end to end with the details a reader needs.",
        ]
    )


@dataclass
class ReviewPolicy:
    """Thresholds applied in Python on stored evaluations. Never sent to Jev."""

    min_category_confidence: float = 0.6
    min_completeness: float = 2.0


@dataclass
class Evaluation:
    """Raw Jev output for one document, plus what identifies the run that produced it."""

    category: str
    category_probabilities: dict[str, float]
    category_confidence: float
    completeness_score: float
    completeness_probabilities: dict[str, float]
    completeness_confidence: float
    model_requested: str
    model_reported: str
    revision: int


@dataclass
class Review:
    status: str  # "ready" | "needs_review"
    reasons: list[str]


@coco.fn
def review(evaluation: Evaluation, policy: ReviewPolicy) -> Review:
    reasons = []
    if evaluation.category_confidence < policy.min_category_confidence:
        reasons.append("low_classification_confidence")
    if evaluation.completeness_score < policy.min_completeness:
        reasons.append("insufficient_completeness")
    return Review(status="needs_review" if reasons else "ready", reasons=reasons)
