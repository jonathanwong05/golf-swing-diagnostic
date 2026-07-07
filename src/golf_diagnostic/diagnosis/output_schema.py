"""
Pydantic models for LLM diagnostic output.

The LLM emits its diagnosis via a tool call whose schema is derived
from these models. This gives us:
- A stable, machine-readable output contract
- Load-time validation like kb/loader.py — the LLM's output is
  parsed and validated the same way KB YAML is
- A single source of truth for the tool schema, generated from
  DiagnosticOutput.model_json_schema()

Semantic validation against the KB (cause_id was in the ranked list,
feel_id / drill_ids are valid indices for the referenced cause)
lives in validate_against_kb() rather than on the Pydantic model
itself. Pydantic can only see the model's own fields — it can't
know the KB or the ranked list. This mirrors how kb/loader.py
separates Pydantic-parseable structure from cross-file semantic
checks.

Populated one of two mutually exclusive ways:
- Normal diagnosis: summary + primary [+ secondary]
- Fallback: summary + fallback_message

A single model-level validator enforces the "exactly one path" rule.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from golf_diagnostic.kb.loader import KnowledgeBase


class CauseExplanation(BaseModel):
    """A single ranked cause, translated into coaching language."""

    cause_id: str = Field(
        description=(
            "The cause_id of a cause from the KB. Must exactly match "
            "the cause_id of one of the ranked causes provided in the "
            "input. Do not invent cause_ids or cite causes that were "
            "not in the ranked list."
        ),
    )
    feel_id: int = Field(
        ge=0,
        description=(
            "Zero-based index into the KB cause's feels list. Selects "
            "which feel to present to the user based on which "
            "indicators fired and the user's free-text context. Must "
            "be a valid index for the cause referenced by cause_id. "
            "The feel text itself is rendered from the KB by the "
            "frontend — do not restate or paraphrase the feel."
        ),
    )
    technical_explanation: str = Field(
        min_length=1,
        description=(
            "One-to-three sentence explanation of what the user is "
            "doing, citing the specific evidence from the matched "
            "indicators (e.g., 'your trail wrist was extended 52° at "
            "the top across all four swings'). Connect the cause to "
            "the user's actual feature values; do not restate the "
            "cause description verbatim."
        ),
    )
    bridge_to_feel: str = Field(
        min_length=1,
        description=(
            "One sentence connecting the technical explanation to the "
            "selected feel. Sets up the feel that the frontend will "
            "render immediately after. Do not restate the feel text."
        ),
    )
    drill_ids: list[int] = Field(
        default_factory=list,
        max_length=2,
        description=(
            "Zero to two indices into the KB cause's drills list. "
            "Each index must be valid for the referenced cause. "
            "Empty list if no drills apply."
        ),
    )


class DiagnosticOutput(BaseModel):
    """
    Top-level LLM output.

    Two mutually exclusive shapes:
    - Normal: summary + primary (+ up to two secondary)
    - Fallback: summary + fallback_message

    Enforced by the _exactly_one_path model validator.
    """

    summary: str = Field(
        min_length=1,
        description=(
            "One-to-two sentence framing of what is going on with the "
            "user's swing, in coaching language. The user reads this "
            "first; it sets up the detail that follows."
        ),
    )
    primary: CauseExplanation | None = Field(
        default=None,
        description=(
            "The highest-ranked cause. Populated when the matcher "
            "produced a diagnosable result. Null when in fallback mode."
        ),
    )
    secondary: list[CauseExplanation] = Field(
        default_factory=list,
        max_length=2,
        description=(
            "Zero to two additional causes worth mentioning alongside "
            "the primary. Only used in normal (non-fallback) output. "
            "Must be empty in fallback mode."
        ),
    )
    fallback_message: str | None = Field(
        default=None,
        description=(
            "Only populated when the matcher's fallback triggered. "
            "Explains what came close but did not clear the diagnostic "
            "threshold, references any invisible-axis blind spots "
            "(grip, alignment, weight distribution) that could be "
            "contributing, and suggests next steps. Null when a "
            "primary cause was produced."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_path(self) -> "DiagnosticOutput":
        in_fallback = self.fallback_message is not None
        has_primary = self.primary is not None

        if in_fallback and has_primary:
            raise ValueError(
                "DiagnosticOutput cannot populate both primary and "
                "fallback_message. In fallback mode, primary must be "
                "None."
            )
        if not in_fallback and not has_primary:
            raise ValueError(
                "DiagnosticOutput must populate either primary (normal "
                "diagnosis) or fallback_message (fallback mode)."
            )
        if in_fallback and self.secondary:
            raise ValueError(
                "DiagnosticOutput.secondary must be empty in fallback "
                "mode."
            )
        return self


class DiagnosisValidationError(ValueError):
    """
    Raised when an LLM output fails semantic validation against the
    KB — cited cause_id not in the ranked list, feel_id or drill_id
    out of range, or the same cause_id cited twice.

    Distinct from pydantic.ValidationError, which covers structural
    failures. The message is suitable for feeding back to the LLM
    in a retry.
    """


def validate_against_kb(
    output: DiagnosticOutput,
    ranked_cause_ids: list[str],
    kb: KnowledgeBase,
    symptom: str,
) -> None:
    """
    Confirm every cause_id in the output was in the ranked list, and
    every feel_id / drill_id is a valid index into the referenced
    cause's feels / drills lists. No-op in fallback mode (nothing to
    check against causes).

    Raises DiagnosisValidationError on the first failure. The message
    is informative enough to feed back into a retry prompt.

    Parameters
    ----------
    output
        The Pydantic-validated LLM output.
    ranked_cause_ids
        The cause_ids that were passed to the LLM in the prompt, in
        rank order. Any cause_id in the output must be in this set —
        this is the anti-hallucination boundary.
    kb
        The loaded KnowledgeBase. Used to look up the feels and
        drills lists for each cited cause.
    symptom
        The symptom being diagnosed. Used to scope the KB lookup.
    """
    all_explanations: list[tuple[str, CauseExplanation]] = []
    if output.primary is not None:
        all_explanations.append(("primary", output.primary))
    for i, exp in enumerate(output.secondary):
        all_explanations.append((f"secondary[{i}]", exp))

    if not all_explanations:
        # Fallback branch — nothing to validate against causes.
        return

    ranked_set = set(ranked_cause_ids)
    causes_by_id = {c.cause_id: c for c in kb.get_causes(symptom)}

    seen_ids: set[str] = set()
    for path, exp in all_explanations:
        if exp.cause_id not in ranked_set:
            raise DiagnosisValidationError(
                f"{path}.cause_id={exp.cause_id!r} is not in the "
                f"ranked list provided in the prompt. Valid "
                f"cause_ids for this diagnosis: {sorted(ranked_set)}."
            )
        if exp.cause_id in seen_ids:
            raise DiagnosisValidationError(
                f"cause_id={exp.cause_id!r} appears more than once "
                f"in the output. Each cause should be cited at most "
                f"once across primary and secondary."
            )
        seen_ids.add(exp.cause_id)

        # cause_id is in ranked_set, which is a subset of causes for
        # this symptom, so the KB lookup cannot miss.
        cause = causes_by_id[exp.cause_id]

        if exp.feel_id >= len(cause.feels):
            raise DiagnosisValidationError(
                f"{path}.feel_id={exp.feel_id} is out of range for "
                f"cause {exp.cause_id!r}, which has {len(cause.feels)} "
                f"feel(s) (valid indices: 0 to "
                f"{len(cause.feels) - 1})."
            )

        for j, did in enumerate(exp.drill_ids):
            if did >= len(cause.drills):
                n_drills = len(cause.drills)
                if n_drills == 0:
                    detail = (
                        f"cause {exp.cause_id!r} has no drills — "
                        f"drill_ids must be empty."
                    )
                else:
                    detail = (
                        f"cause {exp.cause_id!r} has {n_drills} "
                        f"drill(s) (valid indices: 0 to "
                        f"{n_drills - 1})."
                    )
                raise DiagnosisValidationError(
                    f"{path}.drill_ids[{j}]={did} is out of range. "
                    f"{detail}"
                )