# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

import argparse
import asyncio
import sys

import rcav2.logjuicer
import rcav2.env
import rcav2.model
import rcav2.prompt
from rcav2.config import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT, COOKIE_FILE


def usage():
    parser = argparse.ArgumentParser(description="Root Cause Analysis (RCA)")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--local-logjuicer", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="The model name")
    parser.add_argument("--system", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("URL", help="The build URL")
    return parser.parse_args()


async def run(args, env: rcav2.env.Env):
    if args.local_logjuicer:
        report = await rcav2.logjuicer.get_report(env, args.URL)
    else:
        report = await rcav2.logjuicer.get_remote_report(env, args.URL, None)
    with open(".report.json", "w") as f:
        f.write(rcav2.logjuicer.dump_report(report))
    prompt = rcav2.prompt.report_to_prompt(report)
    with open(".prompt.txt", "w") as f:
        f.write(prompt)
    async for message, event in rcav2.model.query(env, args.model, args.system, prompt):
        if event == "report":
            print(message, end="", file=sys.stdout)
        elif event == "usage":
            print()
            env.log.info("Request usage: %s -> %s", message["input"], message["output"])


async def amain():
    args = usage()
    env = rcav2.env.Env(args.debug, cookie_path=COOKIE_FILE)
    try:
        await run(args, env)
    finally:
        env.close()


def main():
    asyncio.run(amain())
