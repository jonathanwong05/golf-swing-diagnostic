"""
LLM client for the diagnostic reasoning layer.

Wraps the Anthropic messages API with:
- automatic mode detection via matcher.should_fall_back()
- forced tool use (emit_diagnosis tool derived from DiagnosticOutput)
- structural (Pydantic) + semantic (validate_against_kb) validation
- one retry on validation failure, using the tool_result / is_error
  pattern so the LLM sees a proper rejection and self-corrects
- prompt caching via the cache_control markers already set by
  prompt.build_prompt

Public API:
    generate_diagnosis(symptom, ranked, kb, *, n_swings, ...) -> DiagnosticOutput

``symptom`` is nullable (Phase 5.1). Pass ``None`` when the user has
not reported a specific ball-flight symptom; the general-mode prompt
and general-mode validation lookup are applied automatically.

Failure modes:
- API errors (network, auth, rate limit) propagate as anthropic.*
  exceptions — not caught here.
- Model doesn't emit a tool_use block despite tool_choice being
  forced: RuntimeError (should be impossible; defensive).
- LLM output fails validation twice in a row:
  DiagnosisValidationError with attempt history in the message.

Environment:
    ANTHROPIC_API_KEY must be set (or a client passed explicitly).
"""

from __future__ import annotations

import sys
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError

from golf_diagnostic.diagnosis.matcher import (
    RankedCause,
    should_fall_back,
)
from golf_diagnostic.diagnosis.output_schema import (
    DiagnosisValidationError,
    DiagnosticOutput,
    validate_against_kb,
)
from golf_diagnostic.diagnosis.prompt import build_prompt
from golf_diagnostic.kb.loader import KnowledgeBase

# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

# Matches the model referenced throughout project docs (phase3_notes,
# spec.md). Swap to a newer model by changing this one constant OR
# passing model= to generate_diagnosis. Sonnet 5 is the newer sibling
# but uses adaptive thinking by default which adds token cost/latency
# to structured tool-use calls; 4.6 is a cleaner fit here.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Output budget. Our structured DiagnosticOutput is small
# (~500-1000 tokens realistic). 2048 leaves comfortable headroom for
# longer explanations without paying for a runaway response.
DEFAULT_MAX_TOKENS = 2048

# How many total attempts to make. 1 retry (2 total attempts) is the
# right balance: one shot to self-correct after a clear error, then
# fail loud rather than looping.
DEFAULT_MAX_RETRIES = 1


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _extract_tool_use(response) -> Any:
    """
    Pull the tool_use content block out of an Anthropic response.

    Forced tool_choice guarantees the model emits a tool_use block,
    so this failing is a defensive check for API surprises.
    """
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return block
    raise RuntimeError(
        "Anthropic response contained no tool_use block despite "
        "tool_choice being forced. Content block types received: "
        f"{[getattr(b, 'type', None) for b in response.content]}"
    )


def _log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[generate_diagnosis] {msg}", file=sys.stderr)


def _serialize_assistant_content(response_content) -> list[dict[str, Any]]:
    """
    Convert response.content (list of ToolUseBlock / TextBlock etc.)
    into a plain list of dicts suitable for echoing back as an
    assistant message in a follow-up call. Uses .model_dump() so we
    do not depend on SDK-object identity across turns.
    """
    return [block.model_dump() for block in response_content]


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def generate_diagnosis(
    symptom: str | None,
    ranked: list[RankedCause],
    kb: KnowledgeBase,
    *,
    n_swings: int,
    user_context: str = "",
    client: Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    verbose: bool = False,
) -> DiagnosticOutput:
    """
    Run one full diagnostic LLM call.

    Determines mode (diagnosis vs fallback) from matcher output,
    builds the prompt, calls the Anthropic API with tool-use forced,
    parses and validates the response, retries once if validation
    fails.

    Parameters
    ----------
    symptom
        User-reported symptom (one of the 9 KB symptoms), or ``None``
        for Phase 5.1 general analysis mode. When ``None``, the
        prompt reframes to observational voice and the validation
        lookup uses pooled Causes across all loaded symptoms.
    ranked
        Full ranked-cause list from either ``matcher.match_symptom``
        (symptom is a string) or ``matcher.match_general`` (symptom
        is None). Do not pre-truncate; internal filtering picks the
        right subset per mode.
    kb
        Loaded KnowledgeBase. Used for semantic validation.
    n_swings
        How many swings the user uploaded. The LLM cites this in
        phrases like "on three of your four swings."
    user_context
        Optional free-text from the user. Rendered inside
        <user_context> tags in the prompt.
    client
        Injectable Anthropic client. Defaults to Anthropic() which
        reads ANTHROPIC_API_KEY from env. Pass a mock in tests.
    model, max_tokens
        Standard Anthropic parameters.
    max_retries
        Number of retries on validation failure. Default 1
        (2 total attempts).
    verbose
        If True, log per-attempt status to stderr. Useful for spike
        tests. Silent by default.

    Returns
    -------
    DiagnosticOutput
        Pydantic-validated and KB-consistent.

    Raises
    ------
    DiagnosisValidationError
        If both attempts fail validation. Message names both errors.
    RuntimeError
        If the API response is malformed (no tool_use block despite
        forced tool_choice). Defensive; should not occur.
    anthropic.*
        API-level errors (auth, rate limit, network) propagate.
    """
    client = client or Anthropic()

    mode = "fallback" if should_fall_back(ranked) else "diagnosis"
    _log(f"symptom={symptom!r} mode={mode} n_ranked={len(ranked)}", verbose)

    payload = build_prompt(
        symptom=symptom,
        ranked=ranked,
        kb=kb,
        n_swings=n_swings,
        mode=mode,
        user_context=user_context,
    )

    # ranked_ids is the anti-hallucination boundary — only cause_ids
    # from the ranked list are allowed in the output. Uses the full
    # ranked list (not the mode-filtered selection) since even in
    # diagnosis mode the LLM might reasonably cite a lower-scored
    # cause as secondary; validate_against_kb catches truly
    # hallucinated ids.
    ranked_ids = [rc.cause.cause_id for rc in ranked]

    # Copy so we can extend without mutating payload.messages.
    messages: list[dict[str, Any]] = list(payload.messages)

    last_error: Exception | None = None
    total_attempts = max_retries + 1

    for attempt_number in range(1, total_attempts + 1):
        _log(f"attempt {attempt_number}/{total_attempts}: calling API", verbose)

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=payload.system,
            tools=payload.tools,
            tool_choice=payload.tool_choice,
            messages=messages,
        )

        _log(
            f"attempt {attempt_number}: stop_reason={response.stop_reason} "
            f"usage(in={response.usage.input_tokens}, "
            f"out={response.usage.output_tokens}, "
            f"cache_read={getattr(response.usage, 'cache_read_input_tokens', 0)}, "
            f"cache_create={getattr(response.usage, 'cache_creation_input_tokens', 0)})",
            verbose,
        )

        tool_use = _extract_tool_use(response)

        try:
            output = DiagnosticOutput.model_validate(tool_use.input)
            validate_against_kb(output, ranked_ids, kb, symptom)
            _log(f"attempt {attempt_number}: validation passed", verbose)
            return output

        except (ValidationError, DiagnosisValidationError) as e:
            last_error = e
            _log(
                f"attempt {attempt_number}: validation FAILED "
                f"({type(e).__name__}): {e}",
                verbose,
            )

            if attempt_number >= total_attempts:
                # Exhausted — fall through to the raise below.
                break

            # Build the retry conversation: echo back the LLM's
            # malformed tool_use as an assistant turn, then send a
            # tool_result with is_error=True explaining what to fix.
            messages.append(
                {
                    "role": "assistant",
                    "content": _serialize_assistant_content(response.content),
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": (
                                f"Your emit_diagnosis call failed "
                                f"validation:\n\n{e}\n\n"
                                f"Please retry the emit_diagnosis "
                                f"tool call with a corrected input. "
                                f"All rules from the original system "
                                f"prompt still apply — do not invent "
                                f"cause_ids, use only valid feel_id "
                                f"and drill_id indices for each cited "
                                f"cause, and populate exactly one of "
                                f"(primary + optional secondary) or "
                                f"(fallback_message)."
                            ),
                            "is_error": True,
                        }
                    ],
                }
            )

    # Exhausted retries. Raise a DiagnosisValidationError that names
    # the last failure so callers get actionable info.
    assert last_error is not None  # loop always sets it before break
    raise DiagnosisValidationError(
        f"LLM output failed validation after {total_attempts} attempt(s). "
        f"Final error ({type(last_error).__name__}): {last_error}"
    )