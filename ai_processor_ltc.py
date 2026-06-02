"""
ai_processor_ltc.py

Sends a resume to Claude AI and extracts all fields needed for the
Long Term Care (RN & LPN) template.

Mirrors Home Health / Hospice exactly — same structure, same rules — but
scoped to LTC context:
  - Additional Info captures LTC-specific items (MDS/RAI, wound care,
    restorative nursing, ADLs, dementia care, skilled nursing, etc.)
  - is_ltc flag distinguishes LTC jobs from hospital/HH/hospice roles
  - Patient Caseload is per day or per shift (not per week)
  - No web search — resume only. Anything not found = yellow highlight.
"""

import json
import os
import re
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def extract_resume_data_ltc(resume_text: str) -> dict:
    """
    Extracts all LTC template fields from a resume.
    Returns a structured dictionary ready for the document generator.
    """
    client = anthropic.Anthropic()

    system_prompt = """You are an expert healthcare resume analyst for a medical staffing company.
Your job is to extract information from long term care nursing resumes with perfect accuracy.

CRITICAL RULES YOU MUST FOLLOW:
1. NEVER invent, guess, estimate, or assume any information
2. ONLY use information explicitly written on the resume
3. If a field is not on the resume, set it to null — do not fill it in
4. For EMR/charting systems: only fill in if the resume explicitly names one
5. For patient caseload: only fill in if explicitly stated on the resume
6. For leadership/charge experience: only set to true for a specific job if
   that job's description mentions charge, leadership, preceptor, or similar
7. For bullet points: if the candidate listed responsibilities for a specific job, select
   MAXIMUM 5 (five) bullets — the most relevant and impactful ones a long term care hiring
   manager would find most valuable. Prioritize: specific clinical skills, wound care,
   MDS/RAI experience, restorative nursing, dementia/memory care, skilled nursing
   procedures, rehab coordination, and resident/family education. Skip vague or generic
   statements (e.g. "provided patient care", "worked with residents", "documented in EMR")
   unless they contain specific detail not captured elsewhere. Never invent, rephrase, or
   combine bullets — pull only from what the candidate wrote for THAT specific job.
   Use an empty array [] if none were listed.
   HARD LIMIT: return no more than 5 bullet strings in the array.
8. For additional_info: capture any LTC-specific details mentioned for that job —
   MDS/RAI assessments, wound care, restorative nursing, ADL assistance, fall prevention,
   dementia/Alzheimer's care, skilled nursing care, rehab coordination, care planning/
   care conferences, Medicare/Medicaid skilled care, therapy coordination, etc.
   Only include what is explicitly written for that job. Set to null if nothing found.
9. Employment type rules:
   - "Travel" if a separate agency employer is listed
   - "Per Diem" if the resume states per diem
   - "Staff" if regular employee (no agency, not per diem)
10. For "employed_through": agency name if Travel, "Direct" if Staff or Per Diem
11. For "is_ltc": set to true if the job is a long term care / skilled nursing position
    (SNF, nursing home, assisted living, memory care, rehab facility, LTC facility, etc.).
    Set to false for hospital, home health, hospice, clinic, or other non-LTC positions.
12. For "additional_info" — this is a LIST of bullet strings, not a single string:
    - If is_ltc is TRUE: extract LTC-specific items explicitly mentioned for that job
      (MDS/RAI, wound care, restorative care, ADLs, dementia care, skilled nursing,
      rehab coordination, care planning, payer mix, etc.). Only what is written.
      Return empty array [] if nothing LTC-specific is found.
    - If is_ltc is FALSE: extract a short list of the most relevant and marketable things
      from that job that an LTC hiring manager would value (e.g. wound care, IV therapy,
      medication management, patient/family education, specific diagnoses managed,
      restorative or rehab support). Pull only from what is written on the resume.
      Return empty array [] if nothing applicable is found.
    - NO DUPLICATES: do not list a term as its own bullet if that same term is already
      mentioned inside a longer bullet. Use the more descriptive bullet and drop the
      redundant short one.

FINDING THE CANDIDATE NAME:
- The name is almost always the first or most prominent text at the top
- It is a person's full name only — no phone numbers, emails, or credentials
- full_name must contain ONLY the person's name, nothing else

CONTACT INFORMATION — never include in output:
- Do NOT put phone numbers, email addresses, or home addresses in any field
- If a bullet is just contact info, skip it entirely"""

    user_prompt = f"""Please analyze this long term care nursing resume and extract all
information into the exact JSON structure below.

RESUME TEXT:
{resume_text}

Return ONLY a valid JSON object with this exact structure. No explanation, no markdown, just the JSON:

{{
  "candidate": {{
    "full_name": "candidate's full name only, no credentials",
    "credential": "RN or LPN",
    "phone_number": "candidate phone number exactly as written, or null if not found",
    "education": [
      {{
        "dates": "date range",
        "school": "school name in ALL CAPS",
        "location": "City, State",
        "degree": "degree name"
      }}
    ],
    "state_licenses": [
      "each nursing license exactly as written on the resume — include state, license number, expiration, or any details listed"
    ],
    "certifications": [
      "each certification listed on the resume e.g. BLS, CNA, CLTC, AANAC"
    ]
  }},
  "experience": [
    {{
      "organization_name": "ORGANIZATION NAME IN ALL CAPS",
      "organization_city_state": "City, ST",
      "employed_through": "Agency Name if travel, or Direct",
      "dates": "MM/YYYY – MM/YYYY or Present",
      "discipline": "RN or LPN",
      "employment_type": "Travel or Per Diem or Staff",
      "specialty": "LTC specialty or resident population from the resume",
      "role": "position title e.g. Charge Nurse, MDS Coordinator, DON, Supervisor, null if not listed",
      "is_ltc": true,
      "emr": "EMR system name if explicitly on resume, otherwise null",
      "patient_caseload": "caseload per day or per shift if explicitly stated, otherwise null",
      "leadership_charge": false,
      "additional_info": ["bullet string 1", "bullet string 2"],
      "bullets": []
    }}
  ],
  "clinical_experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "specialty_rotation": "description of the clinical rotation",
      "total_staffed_beds": null
    }}
  ]
}}

IMPORTANT REMINDERS:
- leadership_charge: true ONLY if that specific job mentions charge, leadership, or preceptor
- bullets: maximum 5 bullets — most relevant LTC-specific skills, wound care, MDS, and resident care details. Empty array [] if none listed.
- additional_info: a LIST of bullet strings — empty array [] if nothing applicable found
- is_ltc: true for SNF/nursing home/LTC/memory care/assisted living jobs, false for hospitals/HH/hospice/clinic
- state_licenses: include ALL nursing licenses listed — capture exactly as written. Do NOT include "Registered Nurse" or "Licensed Practical Nurse" as entries. If none found, use empty array []
- certifications: ONLY actual certifications — empty array [] if none found
- phone_number: candidate's phone only, not any facility phone numbers
- Return ONLY the JSON, nothing else"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt
    )

    response_text = message.content[0].text.strip()

    if response_text.startswith("```"):
        response_text = re.sub(r"```(?:json)?", "", response_text).strip()
        response_text = response_text.rstrip("`").strip()

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned an unexpected response format. "
            f"JSON error: {e}\n\nRaw response:\n{response_text[:500]}"
        )

    _validate_and_fill_defaults(data)
    _clean_candidate_name(data)

    return data


def _deduplicate_bullets(items: list) -> list:
    """
    Removes any bullet whose full text already appears as a substring inside
    a longer bullet in the same list. Collapses exact duplicates too.
    """
    if not items or len(items) < 2:
        return items

    cleaned = []
    for i, item in enumerate(items):
        item_lower = item.strip().lower()
        is_redundant = any(
            item_lower in other.strip().lower() and item_lower != other.strip().lower()
            for j, other in enumerate(items) if i != j
        )
        if not is_redundant:
            cleaned.append(item)

    seen = []
    for item in cleaned:
        if item not in seen:
            seen.append(item)
    return seen


def _validate_and_fill_defaults(data: dict):
    """Fills in safe defaults for any missing fields so nothing crashes."""
    if "candidate" not in data:
        raise ValueError("AI response is missing the 'candidate' section.")
    if "experience" not in data:
        raise ValueError("AI response is missing the 'experience' section.")

    candidate = data["candidate"]
    candidate.setdefault("full_name", "Unknown Candidate")
    candidate.setdefault("credential", "")
    candidate.setdefault("phone_number", None)
    candidate.setdefault("education", [])
    candidate.setdefault("state_licenses", [])
    candidate.setdefault("certifications", [])

    for edu in candidate.get("education", []):
        edu.setdefault("dates", "")
        edu.setdefault("school", "")
        edu.setdefault("location", "")
        edu.setdefault("degree", "")

    for job in data.get("experience", []):
        job.setdefault("organization_name", "UNKNOWN ORGANIZATION")
        job.setdefault("organization_city_state", "")
        job.setdefault("employed_through", None)
        job.setdefault("dates", "")
        job.setdefault("discipline", "")
        job.setdefault("employment_type", "")
        job.setdefault("specialty", None)
        job.setdefault("role", None)
        job.setdefault("emr", None)
        job.setdefault("patient_caseload", None)
        job.setdefault("is_ltc", True)
        job.setdefault("leadership_charge", False)
        job.setdefault("additional_info", [])
        job.setdefault("bullets", [])

        if job["bullets"] is None:
            job["bullets"] = []
        if job["additional_info"] is None:
            job["additional_info"] = []
        if isinstance(job["additional_info"], str):
            job["additional_info"] = [job["additional_info"]] if job["additional_info"] else []
        if job["leadership_charge"] is None:
            job["leadership_charge"] = False
        if job["is_ltc"] is None:
            job["is_ltc"] = True

        # Strip contact info from bullets
        job["bullets"] = [
            b for b in job["bullets"]
            if b and not re.search(r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b', str(b))
            and not re.search(r'\S+@\S+\.\S+', str(b))
        ]
        # Hard cap: never more than 5 bullets regardless of what the AI returned
        job["bullets"] = job["bullets"][:5]

        # Remove redundant additional_info bullets
        job["additional_info"] = _deduplicate_bullets(job["additional_info"])

    data.setdefault("clinical_experience", [])
    if data["clinical_experience"] is None:
        data["clinical_experience"] = []

    for entry in data.get("clinical_experience", []):
        entry.setdefault("facility_name", "")
        entry.setdefault("specialty_rotation", "")
        entry.setdefault("total_staffed_beds", None)


def _clean_candidate_name(data: dict):
    """Removes phone numbers, emails, and credentials from the name field."""
    name = data.get("candidate", {}).get("full_name", "")
    if not name:
        return
    name = re.sub(r'[\+\(]?\d[\d\s\-\.\(\)]{7,}\d', '', name)
    name = re.sub(r'\S+@\S+\.\S+', '', name)
    name = re.sub(r'\b(RN|LPN|BSN|MSN|DNP|NP|APRN|CNA|RRT|PT|OT|SLP|COTA|PTA)\b', '', name)
    name = re.sub(r'[\s,\-]+', ' ', name).strip().strip(',').strip()
    if name:
        data["candidate"]["full_name"] = name
