"""Read CI evidence and render trusted summaries from untrusted report data."""

import html
import math
import os
import re
import xml.etree.ElementTree as ET


STATUS = {
    "success": "PASS",
    "failure": "FAIL",
    "cancelled": "CANCELLED",
    "skipped": "SKIPPED",
}


def safe(value):
    if value is None:
        return "unavailable"
    return html.escape(str(value)).translate(
        str.maketrans({c: f"&#{ord(c)};" for c in "|`[]()\\*_"})
        | str.maketrans({"\n": " ", "\r": " "})
    )


def step_status(outcomes, name, field="outcome"):
    entry = outcomes.get(name) if isinstance(outcomes, dict) else None
    value = entry.get(field) if isinstance(entry, dict) else None
    return STATUS.get(value, "NOT RUN") if isinstance(value, str) else "NOT RUN"


def run_reference():
    url = os.environ.get("CI_RUN_URL", "")
    if re.fullmatch(
        r"https://[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+",
        url,
    ):
        return f"[Actions run and artifacts]({url})"
    return safe(url) if url else "the current run’s artifact, when available"


def behavior_table(rows, limits):
    return (
        "\n".join(
            [
                "### What was tested and why it matters",
                "",
                "| Behavior checked | Actual result | Why it matters | Evidence / limit |",
                "|---|---|---|---|",
                *("| " + " | ".join(map(safe, row)) + " |" for row in rows),
                "",
                "**Gaps and limits.** " + limits,
                "",
            ]
        )
        + "\n"
    )


def junit(path):
    """Count case elements and preserve pytest's separate subtest-inclusive totals."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if root.tag not in ("testsuite", "testsuites") or not suites:
        raise ValueError("Unexpected JUnit root or empty suite")
    cases = [case for suite in suites for case in suite.findall("testcase")]
    if not cases:
        raise ValueError("Required test report contains zero test cases")
    if len(cases) != sum(1 for _ in root.iter("testcase")):
        raise ValueError("Unexpected JUnit test case placement")
    durations = [float(c.attrib["time"]) for c in cases if "time" in c.attrib]
    if any(not math.isfinite(value) or value < 0 for value in durations):
        raise ValueError("Invalid JUnit duration")

    declared = {}
    for attr, tag in (
        ("tests", None),
        ("failures", "failure"),
        ("errors", "error"),
        ("skipped", "skipped"),
    ):
        values = [int(suite.attrib[attr]) for suite in suites if attr in suite.attrib]
        if any(value < 0 for value in values):
            raise ValueError(f"Invalid JUnit {attr} total")
        if tag:
            for suite in suites:
                actual = sum(
                    len(case.findall(tag)) for case in suite.findall("testcase")
                )
                if attr in suite.attrib and int(suite.attrib[attr]) != actual:
                    raise ValueError(
                        f"JUnit {attr} total conflicts with the case evidence"
                    )
        # Pytest may count subtests here even though no separate case element is
        # serialized. An error after a failed test may also add a second element.
        if len(values) == len(suites):
            declared[attr] = sum(values)
    if declared.get("tests") == 0:
        raise ValueError("JUnit declares zero tests with nonempty cases")

    statuses = [case_status(case) for case in cases]
    counts = dict(
        tests=len(cases),
        failed=statuses.count("FAIL"),
        skipped=statuses.count("SKIPPED"),
        seconds=sum(durations) if len(durations) == len(cases) else None,
    )
    return cases, counts, declared


def case_status(case):
    if case.find("failure") is not None or case.find("error") is not None:
        return "FAIL"
    return "SKIPPED" if case.find("skipped") is not None else "PASS"


def case_id(case):
    return (case.get("classname", "") + "::" + case.get("name", "unnamed"))[:300]
