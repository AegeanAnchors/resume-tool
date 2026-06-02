"""
web_researcher.py

This file searches the web to fill in fields that weren't on the resume.
It uses Tavily to search, then asks Claude to evaluate whether the results
contain a confident, specific answer for THAT facility.

Strict rules:
  - Only fills in a field if the answer is specific to that exact facility
  - Never uses general statistics (e.g., "most ICUs have 1-2 patients")
  - Patient caseload is NEVER filled from web search — resume only
  - If search results are ambiguous or vague, the field stays null (yellow highlight)

Strategy:
  - One "general info" search per hospital to get beds, trauma level, teaching status
  - One separate "EMR" search per hospital if EMR is missing
  - Claude evaluates all results and extracts only confident answers
"""

import os
import json
import re
import anthropic
from tavily import TavilyClient
from dotenv import load_dotenv

# Load the API keys from the .env file
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def research_missing_fields(data: dict, missing_jobs: list) -> dict:
    """
    Main function. Takes the structured resume data and the list of jobs
    with missing fields. Returns the same data with as many fields filled
    in as possible from web research.

    Any field still null after research will be highlighted yellow in the
    final document.
    """
    if not missing_jobs:
        print("No missing fields to research.")
        return data

    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    claude = anthropic.Anthropic()

    for job_info in missing_jobs:
        job_index = job_info["job_index"]
        facility_name = job_info["facility_name"]
        city_state = job_info["facility_city_state"]
        missing_fields = job_info["missing_fields"]

        print(f"\n  Researching: {facility_name}, {city_state}")
        print(f"  Missing fields: {missing_fields}")

        job = data["experience"][job_index]

        # --- SEARCH 1: General facility info (beds, trauma level, teaching status) ---
        general_fields_needed = [f for f in missing_fields
                                  if f in ["total_staffed_beds", "facility_type", "teaching_status"]]

        if general_fields_needed:
            general_results = _search_facility_info(tavily, facility_name, city_state)
            if general_results:
                filled = _extract_facility_info(claude, facility_name, city_state, general_results)
                print(f"    General search found: {filled}")

                # Only update fields that are still null and were actually found
                for field in ["total_staffed_beds", "facility_type", "teaching_status"]:
                    if job.get(field) is None and filled.get(field):
                        job[field] = filled[field]
                        print(f"    ✅ Filled {field}: {filled[field]}")

        # --- SEARCH 2: EMR system ---
        if "emr" in missing_fields:
            emr_results = _search_emr(tavily, facility_name, city_state)
            if emr_results:
                emr_found = _extract_emr(claude, facility_name, city_state, emr_results)
                if emr_found:
                    job["emr"] = emr_found
                    print(f"    ✅ Filled EMR: {emr_found}")
                else:
                    print(f"    ⚠ EMR not found with confidence — will highlight yellow")

    return data


def _search_facility_info(tavily: TavilyClient, facility_name: str, city_state: str) -> str:
    """
    Searches for general hospital information: bed count, trauma level,
    teaching status. Returns the raw search results as a string.
    """
    query = (
        f"{facility_name} {city_state} hospital "
        f"total beds trauma center level teaching hospital"
    )

    try:
        results = tavily.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True
        )

        # Combine the answer summary and the top result snippets into one text block
        text_parts = []

        if results.get("answer"):
            text_parts.append(f"SUMMARY: {results['answer']}")

        for result in results.get("results", []):
            if result.get("content"):
                text_parts.append(
                    f"SOURCE ({result.get('url', 'unknown')}):\n{result['content'][:800]}"
                )

        return "\n\n".join(text_parts)

    except Exception as e:
        print(f"    Web search error for {facility_name}: {e}")
        return ""


def _search_emr(tavily: TavilyClient, facility_name: str, city_state: str) -> str:
    """
    Searches specifically for what EMR/EHR system a hospital uses.
    Returns the raw search results as a string.
    """
    query = (
        f"{facility_name} {city_state} "
        f"EMR EHR electronic health record system Epic Cerner Meditech"
    )

    try:
        results = tavily.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer=True
        )

        text_parts = []

        if results.get("answer"):
            text_parts.append(f"SUMMARY: {results['answer']}")

        for result in results.get("results", []):
            if result.get("content"):
                text_parts.append(
                    f"SOURCE ({result.get('url', 'unknown')}):\n{result['content'][:800]}"
                )

        return "\n\n".join(text_parts)

    except Exception as e:
        print(f"    EMR search error for {facility_name}: {e}")
        return ""


def _extract_facility_info(claude: anthropic.Anthropic,
                            facility_name: str,
                            city_state: str,
                            search_results: str) -> dict:
    """
    Sends the search results to Claude and asks it to extract specific,
    confident values for bed count, trauma level, and teaching status.

    Claude must only return a value if it is clearly stated in the search
    results for THIS specific facility — not general estimates.
    """
    prompt = f"""I searched the web for information about {facility_name} in {city_state}.
Here are the search results:

{search_results}

Based ONLY on these search results, extract the following information about {facility_name} specifically.
Return a JSON object with these exact keys. Set a value to null if you are not confident it refers specifically to {facility_name}.

Rules:
- total_staffed_beds: must be a specific number (e.g., "781") — null if not clearly stated
- facility_type: must be a specific trauma level (e.g., "Level I Trauma Center", "Level II Trauma Center") — null if not clearly stated
- teaching_status: must be either "Teaching Facility" or "Non-Teaching Facility" — null if not clearly stated
- Do NOT guess or infer — if the result is about a different facility or is ambiguous, use null

Return ONLY this JSON, nothing else:
{{
  "total_staffed_beds": null,
  "facility_type": null,
  "teaching_status": null
}}"""

    try:
        message = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text.strip()

        # Clean up markdown code blocks if present
        if response_text.startswith("```"):
            response_text = re.sub(r"```(?:json)?", "", response_text).strip()
            response_text = response_text.rstrip("`").strip()

        result = json.loads(response_text)
        return result

    except Exception as e:
        print(f"    Error extracting facility info: {e}")
        return {}


def _extract_emr(claude: anthropic.Anthropic,
                 facility_name: str,
                 city_state: str,
                 search_results: str) -> str | None:
    """
    Sends the EMR search results to Claude and asks it to extract the
    specific EMR system used by this hospital.

    Returns the EMR name as a string, or None if not found with confidence.
    """
    prompt = f"""I searched the web for information about what EMR/EHR system {facility_name} in {city_state} uses.
Here are the search results:

{search_results}

Based ONLY on these search results, what EMR or EHR system does {facility_name} use?
Common systems include: Epic, Cerner, Meditech, Soarian, Allscripts, CPSI, PointClickCare, MatrixCare.

Rules:
- Only provide an answer if the search results clearly state the EMR for {facility_name} specifically
- Do NOT guess based on what similar hospitals use
- If the result is ambiguous or about a different facility, return null

Return ONLY a JSON object, nothing else:
{{"emr": "System Name"}} or {{"emr": null}}"""

    try:
        message = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text.strip()

        # Clean up markdown code blocks if present
        if response_text.startswith("```"):
            response_text = re.sub(r"```(?:json)?", "", response_text).strip()
            response_text = response_text.rstrip("`").strip()

        result = json.loads(response_text)
        return result.get("emr")

    except Exception as e:
        print(f"    Error extracting EMR: {e}")
        return None


def print_research_summary(data: dict):
    """
    Prints a summary of what was filled in by web research and what
    still needs to be highlighted yellow.
    """
    print("\n=== WEB RESEARCH RESULTS ===")
    for job in data.get("experience", []):
        print(f"\n  {job['facility_name']}, {job['facility_city_state']}")

        fields_to_check = {
            "emr": "EMR",
            "total_staffed_beds": "Beds",
            "facility_type": "Trauma Level",
            "teaching_status": "Teaching Status",
            "patient_caseload": "Patient Caseload"
        }

        for field, label in fields_to_check.items():
            value = job.get(field)
            if value:
                print(f"    ✅ {label}: {value}")
            else:
                print(f"    🟡 {label}: will be highlighted yellow")
