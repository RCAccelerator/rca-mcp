# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

import dspy  # type: ignore[import-untyped]

import rcav2.models.errors
import rcav2.agent.ansible
from rcav2.models.report import PossibleRootCause
from rcav2.worker import Worker


class RCAAccelerator(dspy.Signature):
    """
    You are a CI engineer, your goal is to find the RCA of this build failure.

    You are given a description of the job and the errors found in the logs.

    The log files are condensed in a single markdown errors file using the following format:

      ## {log file name}
      {errors}

    ============================================================================
    INVESTIGATION STRATEGY
    ============================================================================

    1. **Recognize Symptoms:**
       - The errors in `job-output.txt` are often just symptoms
       - The actual root cause likely occurred earlier

    2. **Trace Back to the Root Cause:**
       - Use the log file list to examine logs that came before `job-output.txt`
       - These earlier logs are critical for finding the initial point of failure

    3. **Analyze All Evidence:**
       - It is crucial that you analyze all the provided errors before drawing a conclusion
       - Do not stop at the first error you find

    4. **Identify the Root Cause:**
       - After a full analysis, identify all possible root causes (usually 1-3 possibilities)

    ============================================================================
    ROOT CAUSE REPORTING
    ============================================================================

    Provide a Summary:
    - Provide a concise summary of the root cause analysis
    - The summary should be a brief overview that helps someone quickly understand what went wrong
    - The summary should include the stage at which the root cause occurred
    - The summary should also include a small table showing the timeline
      for the errors that you have identified

    You should identify all possible root causes of the failure.

    For each root cause, provide:
    - cause: The root cause of the failure
    - evidences: The evidence that supports the root cause

    You should order the root causes by the likelihood of the root cause being the actual
    root cause, starting with the most likely root cause.

    You must preserve the log file name from the markdown heading when creating new evidences.
    """

    job: rcav2.agent.ansible.Job = dspy.InputField()

    errors: str = dspy.InputField()
    summary: str = dspy.OutputField()
    possible_root_causes: list[PossibleRootCause] = dspy.OutputField()


def make_agent() -> dspy.Predict:
    return dspy.ChainOfThought(RCAAccelerator, max_tokens=1024 * 1024)


async def call_agent(
    agent: dspy.Predict,
    job: rcav2.agent.ansible.Job | None,
    errors: rcav2.models.errors.Report,
    worker: Worker,
) -> tuple[list[PossibleRootCause], str]:
    if not job:
        job = rcav2.agent.ansible.Job(description="", actions=[])

    # Add log URL to job description if available
    if log_url := errors.log_url:
        job.description += f"\n\nBuild Log URL: {log_url}"

    await worker.emit("Calling RCAAccelerator", "progress")
    errors_report = report_to_prompt(errors)
    result = await agent.acall(job=job, errors=errors_report)
    await rcav2.model.emit_dspy_usage(result, worker)
    return (result.possible_root_causes, result.summary)


def report_to_prompt(report: rcav2.models.errors.Report) -> str:
    """Convert a report to a LLM prompt

    >>> report_to_prompt(rcav2.models.errors.json_to_report(TEST_REPORT))
    '\\n## zuul/overcloud.log\\noops'
    """
    lines = []
    for logfile in report.logfiles:
        lines.append(f"\n## {logfile.source}")
        for error in logfile.errors:
            for line in error.before:
                lines.append(line)
            lines.append(error.line)
            for line in error.after:
                lines.append(line)
    return "\n".join(lines)


TEST_REPORT = dict(
    target={"Zuul": {"job_name": "tox", "log_url": "https://logserver/build"}},
    log_reports=[
        dict(
            source={"RawFile": {"Remote": [12, "example.com/zuul/overcloud.log"]}},
            anomalies=[
                {"before": [], "anomaly": {"line": "oops", "pos": 42}, "after": []}
            ],
        )
    ],
)
