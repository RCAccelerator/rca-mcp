# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

from rcav2.errors import Report
from rcav2.env import Env
from rcav2.worker import Worker
import rcav2.errors


def make_local_report(url: str) -> Report:
    import subprocess
    import json

    # This need: https://github.com/logjuicer/logjuicer/pull/178
    return rcav2.errors.json_to_report(
        json.loads(
            subprocess.check_output(
                ["logjuicer", "--report", "/dev/stdout", "errors", url]
            )
        )
    )


async def wait_report(env: Env, wurl: str, report_id: int, worker: None | Worker):
    import httpx_ws

    wurl = f"{wurl}/logjuicer/wsapi/report/{report_id}"

    try:
        # type: ignore
        async with httpx_ws.aconnect_ws(  # type: ignore
            wurl, env.httpx, auth=env.auth, keepalive_ping_timeout_seconds=None
        ) as ws:
            while True:
                ev = await ws.receive_text()
                match ev:
                    case "...":
                        ...
                    case "Done":
                        break
                    case _:
                        if worker:
                            await worker.emit(ev, event="progress")
                        else:
                            print(ev)
    except httpx_ws.WebSocketUpgradeError as e:
        if e.response.status_code == 404:
            # The report must have been already created.
            pass
        else:
            raise


async def do_get_remote_report(env: Env, url: str, worker: None | Worker) -> Report:
    from rcav2.config import SF_URL

    # Step1: request report
    env.log.info("%s: Requesting errors report", url)
    curl = f"{SF_URL}/logjuicer/api/report/new?target={url}&errors=true"
    create_resp = (await env.httpx.put(curl, auth=env.auth)).raise_for_status()
    [report_id, status] = create_resp.json()

    if worker:
        report_url = f"{SF_URL}/logjuicer/report/{report_id}"
        await worker.emit(report_url, event="logjuicer_url")
    # Step2: wait for status, from: https://github.com/logjuicer/logjuicer/blob/ba53c7566797cec44a8064dc905c3f78743045c0/crates/report/src/report_row.rs#L47-L51
    match status:
        case "Pending":
            env.log.info("%s: Waiting for errors report %s", url, report_id)
            wurl = "wss" + SF_URL[len("https") :]
            await wait_report(env, wurl, report_id, worker)
        case "Completed":
            pass
        case error:
            raise RuntimeError(f"{url}: report creation failed: {error}")

    # Step3: download report
    curl = f"{SF_URL}/logjuicer/api/report/{report_id}/json"
    report = (await env.httpx.get(curl, auth=env.auth)).raise_for_status().json()
    return rcav2.errors.json_to_report(report)


async def get_remote_report(env: Env, url: str, worker: None | Worker) -> Report:
    import rcav2.auth
    import httpx_ws

    # Ensure we are authenticated, otherwise the redirection will fail to PUT
    await rcav2.auth.ensure_cookie(env)

    # It looks like there is an issue with httpx_ws which might raise an exception too early.
    # So we can safely retry in that case, because the step1 status will have progressed.
    while True:
        try:
            return await do_get_remote_report(env, url, worker)
        except httpx_ws.WebSocketNetworkError as e:
            env.log.error("WS error :/", e)


async def get_report(env: Env, url: str) -> Report:
    import os
    import rcav2.auth

    if not os.environ.get("LOGJUICER_HTTP_AUTH"):
        await rcav2.auth.ensure_cookie(env)
        os.environ["LOGJUICER_HTTP_AUTH"] = (
            f"Cookie: mod_auth_openidc_session={env.cookie}"
        )
    env.log.info("Ingesting build log from %s", url)
    return await get_remote_report(env, url, None)


def dump_report(report: Report) -> str:
    import json
    import rcav2.errors

    report_dict = rcav2.errors.report_to_json(report)
    return json.dumps(report_dict, indent=2)
