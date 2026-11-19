"""Read-time ordering of existing cashflows; no new prices or stored valuations."""

from decimal import Decimal, ROUND_HALF_UP

DEFAULT = "edge"
METHODS = {
    "growth": dict(
        label="Kelly growth",
        column="Growth",
        unit="log bp",
        places=3,
        explanation="Growth = 10,000 × [p × ln(1 + f × win return) + (1 − p) × ln(1 + f × loss return)].",
    ),
    "ev": dict(
        label="Net EV",
        column="Net EV",
        unit="%",
        places=2,
        explanation="Net EV = p × win return + (1 − p) × loss return.",
    ),
    "score": dict(
        label="Kelly fraction",
        column="Kelly",
        unit="fraction × 10,000",
        places=0,
        explanation="Kelly fraction × 10,000. The original Opportunity Score.",
    ),
    "balanced": dict(
        label="Balanced (experimental)",
        column="Balanced",
        unit="index",
        places=2,
        explanation="Index = 10,000 × Net EV ÷ √(win return). This is an experimental payout-penalty heuristic.",
    ),
    "edge": dict(
        label="Probability edge",
        column="Edge",
        unit="pp",
        places=3,
        explanation="Edge = 100 × (reference win probability − after-fee break-even probability).",
    ),
}


def method(value=None):
    selected = value or DEFAULT
    if selected not in METHODS:
        raise ValueError("Unknown opportunity ranking")
    return selected


def catalog():
    """Shared browser metadata, generated from the same methods used by reads."""
    return dict(
        default=method(DEFAULT),
        methods={key: dict(value) for key, value in METHODS.items()},
    )


def fraction(path):
    # Paths are module-owned constants, never request text.
    text = "payload#>>'{" + path + "}'"
    return f"(split_part({text},'/',1)::numeric / COALESCE(NULLIF(split_part({text},'/',2),''),'1')::numeric)"


def expression(selected):
    """SQL ordering over the whole qualified cohort, before LIMIT/OFFSET."""
    selected = method(selected)
    ev = fraction("raw,net_ev")
    score = fraction("raw,opportunity_score")
    if selected == "ev":
        return f"100*{ev}"
    if selected == "score":
        return score
    p = fraction("reference,probability")
    committed = fraction("fee,committed_usd")
    win = f"({fraction('fee,cashflows,win,net_receipt_usd')}/{committed}-1)"
    loss = f"({fraction('fee,cashflows,loss,net_receipt_usd')}/{committed}-1)"
    if selected == "balanced":
        return f"CASE WHEN {win}>0 THEN 10000*{ev}/sqrt({win}) END"
    if selected == "edge":
        return f"100*({p}+{loss}/NULLIF({win}-{loss},0))"
    if selected != "growth":
        raise ValueError("Unsupported opportunity ranking calculation")
    f = f"({score}/10000)"
    # Zero-probability outcomes contribute zero, including a zero wealth factor.
    terms = []
    for probability, payoff in ((p, win), (f"(1-{p})", loss)):
        wealth = f"(1+{f}*{payoff})"
        terms.append(
            f"CASE WHEN {probability}=0 THEN 0 WHEN {wealth}>0 "
            f"THEN {probability}*ln({wealth}) END"
        )
    return "10000*(" + "+".join(terms) + ")"


def present(payload, value, selected):
    """Attach read-only ranking metadata; retain the original quote and score."""
    info = METHODS[method(selected)]
    places = info["places"]
    shown = None
    exact = None
    if value is not None:
        number = Decimal(str(value))
        # SQL text and psycopg Decimal can encode the same value differently.
        # Strip only insignificant zeroes; Decimal.normalize() could round long
        # values using the caller's precision and change the retained metric.
        exact = format(number, "f")
        if "." in exact:
            exact = exact.rstrip("0").rstrip(".")
        if not number:
            exact = "0"
        shown = format(
            number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP),
            f".{places}f",
        )
        if selected in ("ev", "edge") and Decimal(str(value)) >= 0:
            shown = "+" + shown
        if selected == "ev":
            shown += "%"
    return dict(
        payload,
        ranking=dict(
            method=selected,
            label=info["label"],
            column=info["column"],
            unit=info["unit"],
            value=exact,
            display=shown or "—",
        ),
    )
