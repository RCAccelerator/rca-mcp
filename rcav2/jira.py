# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

import json
import llm
import httpx
from pydantic import BaseModel, Field

from . import config
from .env import Env

SYSTEM_PROMPT = """
You are an expert assistant that converts a Root Cause Analysis (RCA) Root Cause of a build failure into a precise Jira Query Language (JQL) string.

Your goal is to find existing Jira tickets that may be related to this failure.

Follow these rules:
1.  Carefully analyze the provided RCA Root Cause to identify key information:
    - Specific error messages (e.g., "Connection timed out", "Promotion criteria failed to match").
    - Failing components, services, or modules.
    - Technologies or libraries involved (e.g., "python", "openstack", "dnf").
    - Any mentioned hostnames or infrastructure details.
2.  Construct a JQL query to search for this information in the `summary`, `description`, and `comment` fields.
3.  Use the `~` (CONTAINS) operator for all text searches to allow for partial matches. Combine multiple terms with `AND` or `OR` where appropriate to broaden or narrow the search.
4.  Prioritize recent issues by adding `ORDER BY updated DESC` to the query.
5.  Format your response as a JSON object that strictly adheres to the provided schema.

Example RCA Root Cause: "The job 'periodic-rhel-9-rhos-18-dlrn-check-promotion-criteria-podified-ci-testing-to-current-podified' explicitly repo
rted a failure due to promotion criteria not being met, meaning the conditions required for promoting a specific build or set of package
s were not satisfied."
"""


class JQLQuery(BaseModel):
    """
    A Pydantic model for a JQL query.
    """

    jql: str = Field(
        description='A valid JQL query string. Example: (summary ~ "promotion criteria" OR description ~ "promotion criteria" OR comment ~ "promotion criteria") AND (summary ~ "not met" OR description ~ "not met" OR comment ~ "not met" OR summary ~ "failed" OR description ~ "failed" OR comment ~ "failed" OR summary ~ "not satisfied" OR description ~ "not satisfied" OR comment ~ "not satisfied") ORDER BY updated DESC'
    )


class JiraSearchTool:
    """
    A tool to search Jira by converting an RCA Root Cause to JQL using an LLM.
    """

    def __init__(self, env: Env, model_name: str):
        """
        Initializes the tool.
        """
        self.env = env
        self.model = llm.get_model(model_name)

    def generate_jql(self, root_cause: str) -> str:
        """
        Uses an LLM to generate a JQL string from an RCA Root Cause.
        """
        self.env.log.info("Generating JQL from RCA Root Cause...")

        try:
            response = self.model.prompt(
                system=SYSTEM_PROMPT,
                prompt=root_cause,
                schema=JQLQuery,
            )
            jql = json.loads(response.text())
            self.env.log.info(f"Generated JQL: {jql['jql']}")
            return jql["jql"]
        except Exception as e:
            self.env.log.error(f"Failed to generate JQL from LLM: {e}")
            raise

    async def search_jira(self, jql: str, max_results: int = 5) -> dict:
        """
        Executes a JQL query against the Jira API.
        """
        search_url = f"{config.JIRA_URL}/rest/api/2/search"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.JIRA_TOKEN}",
        }
        params: dict[str, int | str] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,assignee",
        }

        self.env.log.info("Executing search on Jira API...")
        try:
            response = await self.env.httpx.get(
                search_url, headers=headers, params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            self.env.log.error(f"Jira API returned an error: {e.response.status_code}")
            self.env.log.error(f"Response body: {e.response.text}")
            raise
        except Exception as err:
            self.env.log.error(
                f"An unexpected error occurred during Jira search: {err}"
            )
            raise

    async def run(self, root_cause: str) -> dict:
        """
        Main execution flow.
        """
        try:
            generated_jql = self.generate_jql(root_cause)
            if not generated_jql:
                self.env.log.warning(
                    "LLM returned an empty JQL query. Skipping Jira search."
                )
                return {}

            project_jql = f"project in ({', '.join(config.DEFAULT_JIRA_PROJECTS)}) AND {generated_jql}"
            self.env.log.info(f"Final JQL with project constraint: {project_jql}")

            results = await self.search_jira(project_jql)
            total_issues = results.get("total", 0)

            if total_issues == 0:
                self.env.log.info("No Related Jira Issues Found.")
                return {}

            issues_list: list[dict[str, str]] = []
            for issue in results.get("issues", []):
                key = issue.get("key")
                fields = issue.get("fields", {})
                summary = fields.get("summary", "N/A")
                issue_url = f"{config.JIRA_URL}/browse/{key}"
                issues_list.append(
                    {
                        "id": key,
                        "summary": summary,
                        "url": issue_url,
                    }
                )
            return {"jira_issues": issues_list}

        except Exception as e:
            self.env.log.error(f"Error during Jira Search: {e}")
            return {}
