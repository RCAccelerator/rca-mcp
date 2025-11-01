# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

"""
This module defines the RCA workflows.
"""

import json

from rcav2.env import Env
from rcav2.database import Engine
from rcav2.worker import Worker
from rcav2.config import JOB_DESCRIPTION_FILE
from rcav2.agent.ansible import Job
from rcav2.models.report import Report
from rcav2.model import TraceManager

import rcav2.tools.logjuicer
import rcav2.tools.zuul
import rcav2.agent.ansible
import rcav2.agent.logjuicer_agent
import rcav2.agent.jira_agent
import rcav2.agent.predict
import rcav2.agent.react


def load_job_description_file() -> str | None:
    """Load additional job description from file or URL specified by JOB_DESCRIPTION_FILE environment variable."""
    if not JOB_DESCRIPTION_FILE:
        return None

    # Check if it's a URL (starts with http:// or https://)
    if JOB_DESCRIPTION_FILE and JOB_DESCRIPTION_FILE.startswith(
        ("http://", "https://")
    ):
        try:
            import httpx

            response = httpx.get(JOB_DESCRIPTION_FILE, timeout=30.0)
            response.raise_for_status()
            return response.text.strip()
        except Exception as e:
            print(
                f"Error fetching job description from URL {JOB_DESCRIPTION_FILE}: {e}"
            )
            return None
    else:
        # Treat as local file path
        try:
            with open(JOB_DESCRIPTION_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            print(f"Job description file not found: {JOB_DESCRIPTION_FILE}")
            return None
        except Exception as e:
            print(f"Error reading job description file {JOB_DESCRIPTION_FILE}: {e}")
            return None


async def job_from_model(env: Env, name: str, worker: Worker) -> Job | None:
    await worker.emit("Reading job plays...", event="progress")
    zuul_info = await rcav2.tools.zuul.ensure_zuul_info(env)
    plays = await rcav2.tools.zuul.get_job_playbooks(zuul_info, name)
    if not plays:
        await worker.emit(f"Couldn't find job {name}", event="error")
        return None
    else:
        await worker.emit("Analyzing job...", event="progress")
        agent = rcav2.agent.ansible.make_agent(worker)
        return await rcav2.agent.ansible.call_agent(agent, plays, worker)


async def job_from_db(db: Engine, job_name: str, worker: Worker) -> Job | None:
    if events := rcav2.database.get_job(db, job_name):
        await worker.emit("Found a description in the cache", event="progress")
        return rcav2.agent.ansible.Job.model_validate(
            list(filter(lambda ev: ev[0] == "job", json.loads(events)))[0][1]
        )
    return None


async def describe_job_base(
    env: Env, db: Engine | None, job_name: str, worker: Worker
) -> Job | None:
    if db:
        if job := await job_from_db(db, job_name, worker):
            return job
    return await job_from_model(env, job_name, worker)


async def describe_job(
    env: Env, db: Engine | None, job_name: str, worker: Worker
) -> Job | None:
    job = await describe_job_base(env, db, job_name, worker)
    # Load additional job description from file if specified
    if desc := env.extra_description:
        additional_description = desc
    elif desc := load_job_description_file():
        additional_description = desc
        await worker.emit(
            f"Loaded additional job description from {JOB_DESCRIPTION_FILE}",
            event="progress",
        )
    else:
        additional_description = None
    if additional_description:
        if job:
            # Append additional description
            job.description += f"\n\nAdditional Context:\n{additional_description}"
        else:
            # Create a job with just the additional description if no job was found
            job = Job(description=additional_description, actions=[])

    return job


async def rca_predict(env: Env, db: Engine | None, url: str, worker: Worker) -> None:
    """A two step workflow with job description"""
    await worker.emit("predict", event="workflow")
    await worker.emit("Fetching build errors...", event="progress")
    errors_report = await rcav2.tools.logjuicer.get_report(env, url, worker)

    with TraceManager("predict", url):
        await worker.emit(f"Describing job {errors_report.target}...", event="progress")
        job = await describe_job(env, db, errors_report.target, worker)
        if job:
            await worker.emit(job.model_dump(), event="job")

        rca_agent = rcav2.agent.predict.make_agent()
        (possible_root_causes, summary) = await rcav2.agent.predict.call_agent(
            rca_agent, job, errors_report, worker
        )

        report = Report(
            summary=summary, possible_root_causes=possible_root_causes, jira_tickets=[]
        )
        await worker.emit(report.model_dump(), event="report")


async def rca_multi(env: Env, db: Engine | None, url: str, worker: Worker) -> None:
    """A three step workflow with job description and jira agent"""
    await worker.emit("multi", event="workflow")
    await worker.emit("Fetching build errors...", event="progress")
    errors_report = await rcav2.tools.logjuicer.get_report(env, url, worker)

    with TraceManager("multi", url):
        # Step1: Getting build description
        await worker.emit(f"Describing job {errors_report.target}...", event="progress")
        job = await describe_job(env, db, errors_report.target, worker)
        if job:
            await worker.emit(job.model_dump(), event="job")

        # Step2: Analyzing build errors
        rca_agent = rcav2.agent.logjuicer_agent.make_agent(errors_report, worker)
        possible_root_causes = await rcav2.agent.logjuicer_agent.call_agent(
            rca_agent, job, errors_report, worker
        )

        # Step3: Gathering additional context
        # Get the primary root cause description and evidences for Jira search
        primary_cause = possible_root_causes[0].cause if possible_root_causes else ""
        primary_evidences = (
            possible_root_causes[0].evidences if possible_root_causes else []
        )

        jira_agent = rcav2.agent.jira_agent.make_agent(worker, env)
        tickets = await rcav2.agent.jira_agent.call_agent(
            jira_agent, primary_cause, primary_evidences, worker
        )
        report = Report(possible_root_causes=possible_root_causes, jira_tickets=tickets)
        await worker.emit(report.model_dump(), event="report")


async def rca_react(env: Env, db: Engine | None, url: str, worker: Worker) -> None:
    """A two step workflow using a ReAct module"""
    await worker.emit("react", event="workflow")
    await worker.emit("Fetching build errors...", event="progress")
    errors_report = await rcav2.tools.logjuicer.get_report(env, url, worker)

    with TraceManager("react", url):
        await worker.emit(f"Describing job {errors_report.target}...", event="progress")
        job = await describe_job(env, db, errors_report.target, worker)
        if job:
            await worker.emit(job.model_dump(), event="job")

        predict = rcav2.agent.predict.make_agent()
        extra = await rcav2.agent.predict.call_agent(
            predict, job, errors_report, worker
        )

        rca_agent = rcav2.agent.react.make_agent(errors_report, worker, env)
        report = await rcav2.agent.react.call_agent(
            rca_agent, job, errors_report, extra[0], worker
        )
        await worker.emit(report.model_dump(), event="report")


async def run_workflow(
    env: Env, db: Engine | None, workflow: str, url: str, worker: Worker
) -> None:
    match workflow:
        case "predict":
            func = rcav2.workflows.rca_predict
        case "multi":
            func = rcav2.workflows.rca_multi
        case "react":
            func = rcav2.workflows.rca_react
        case _:
            raise RuntimeError(f"{workflow}: unknown workflow")
    await func(env, db, url, worker)
