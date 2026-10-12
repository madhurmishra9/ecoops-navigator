"""Plain-English explanations.

The default is a deterministic template, so every sentence traces back to a field.
An optional LLM can rephrase it (OpenAI-compatible endpoint, e.g. a local Ollama), but it
only receives the structured facts and is told not to add numbers. Any failure falls back
to the template.
"""

from __future__ import annotations

import json
import os
import urllib.request

from .models import Opportunity
from .utils import fmt_qty


def explain(o: Opportunity, currency: str = "GBP") -> str:
    s = o.annual_savings
    observed = [e for e in o.evidence if e.provenance == "observed"][:3]
    facts = "; ".join(f"{e.label} {e.value}{(' ' + e.unit) if e.unit and e.unit not in ('share', 'ratio') else ''}" for e in observed)
    text = (
        f"{o.title}. Likely cause: {o.root_cause}. Observed: {facts}. "
        f"Indicative annual effect under stated assumptions: {fmt_qty(s.get('energy_kwh', 0), 'kWh')}, "
        f"{fmt_qty(s.get('co2e_kg', 0), 'kgCO2e')}, {fmt_qty(s.get('cost', 0), currency)} "
        f"(confidence {o.confidence:.2f}, effort {o.effort})."
    )
    if o.constraint_status == "blocked":
        text += " This action is blocked: " + " ".join(c.reason for c in o.constraints if c.effect == "block")
    elif o.constraint_status == "conditional":
        text += " Conditions: " + "; ".join(o.prerequisites) + "."
    text += f" Recommended next step: {o.next_step}."
    return text


def llm_explain(o: Opportunity, base_url: str | None = None, model: str | None = None, timeout: int = 30,
                currency: str = "GBP") -> str:
    """Rephrase the template with an LLM; returns the template on any error."""
    template = explain(o, currency)
    base_url = base_url or os.environ.get("ECOOPS_LLM_URL")
    model = model or os.environ.get("ECOOPS_LLM_MODEL", "llama3.1")
    if not base_url:
        return template
    facts = {
        "title": o.title, "root_cause": o.root_cause, "proposed_action": o.proposed_action,
        "evidence": [{"label": e.label, "value": str(e.value), "unit": e.unit, "provenance": e.provenance} for e in o.evidence],
        "annual_savings": {k: round(v, 1) for k, v in o.annual_savings.items()}, "currency": currency,
        "confidence": o.confidence, "constraint_status": o.constraint_status,
        "constraints": [c.reason for c in o.constraints], "next_step": o.next_step,
        "missing_information": o.missing_information,
    }
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You explain efficiency recommendations to executives in 3 sentences. "
             "Use ONLY the facts given. Do not invent or recompute numbers. Say which facts are assumptions. "
             "Never comment on individuals or teams."},
            {"role": "user", "content": json.dumps(facts)},
        ],
    }).encode()
    headers = {"Content-Type": "application/json"}
    if os.environ.get("ECOOPS_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['ECOOPS_LLM_API_KEY']}"
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-configured URL
            content = json.loads(resp.read())["choices"][0]["message"]["content"].strip()
            return content or template
    except Exception:  # noqa: BLE001 - narrative is optional; never break the analysis
        return template
