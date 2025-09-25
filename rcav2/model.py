# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

import json
import llm
from pydantic import BaseModel, Field
import textwrap


class RCAAnalysis(BaseModel):
    """
    Defines the structured output for the Root Cause Analysis.
    Validation is automatically handled by Pydantic upon instantiation.
    """

    summary: str = Field(
        ...,
        min_length=1,
        description="A brief, one-sentence summary of the root cause. Must not be empty.",
    )
    root_cause: str = Field(
        ...,
        min_length=1,
        description="A detailed explanation of the primary reason for the failure. Must not be empty.",
    )
    failed_step: str = Field(
        ...,
        min_length=1,
        description="The specific step, command, or component that failed. Must not be empty.",
    )
    log_evidence: str = Field(
        ...,
        min_length=1,
        description="A relevant snippet from the logs that directly supports the analysis. Must not be empty.",
    )
    suggested_fix: str = Field(
        ...,
        min_length=1,
        description="A concrete, actionable recommendation on how to fix the issue. Must not be empty.",
    )


def convert_to_markdown(analysis: str) -> str:
    """Convert an RCAAnalysis json string to properly formatted Markdown."""
    output: list[str] = []
    analysis = json.loads(analysis)
    if isinstance(analysis, dict):
        for key, value in analysis.items():
            title = key.replace("_", " ").capitalize()
            formatted_value = textwrap.dedent(value).strip()
            output.append(f"- **{title}:** {formatted_value}")
    return "\n".join(output)


async def query(env, model, system, prompt):
    env.log.info("Analyzing build with %s using %s bytes", model, len(prompt))
    model = llm.get_async_model(model)
    response = model.prompt(prompt, system=system, schema=RCAAnalysis)
    rca_analysis = await response.text()
    if rca_analysis:
        async for chunk in model.chain(
            f"Convert the RCA below in JSON to Markdown: {rca_analysis}",
            tools=[convert_to_markdown],
        ):
            yield (chunk, "chunk")

    usage = await response.usage()
    if usage:
        yield (dict(input=usage.input, output=usage.output), "usage")
