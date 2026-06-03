"""
ai_processor_hospice_ltc.py

Sends a resume to Claude AI and extracts all fields needed for the
combined Hospice / LTC / SNF (RN & LPN) template.

Handles both hospice and long-term care resumes in a single call.
The is_hospice flag on each job entry drives how the generator
renders that job:
  - is_hospice=True  → shows EMR/Charting + Patient Caseload,
                        uses hospice-specific Additional Info prompt
  - is_hospice=False → LTC/SNF job: no EMR or Caseload fields,
                        uses LTC-specific Additional Info prompt

No web search — resume only. Anything not found = yellow highlight.
"""

import json
import os
import re
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def extract_resume_data_hospice_ltc(resume_text: str) -> dict:
    """
    Extracts all Hospice/LTC template fields from a resume.
    Returns a structured dictionary ready for the document generator.
    """
    client = anthropic.Anthropic()

    system_prompt = """You are an expert healthcare resume analyst for a medical staffing company.
Your job is to extract information from hospice and long term care (LTC/SNF) nursing resumes
with perfect accuracy.

CRITICAL RULES YOU MUST FOLLOW:
1. NEVER invent, guess, estimate, or assume any information
2. ONLY use information explicitly written on the resume
3. If a field is not on the resume, set it to null — do not fill it in
4. For EMR/charting systems: only fill in if the resume explicitly names one
5. For patient caseload: only fill in if explicitly stated on the resume
6. For leadership/charge experience: only set to true for a specific job if
   that job's description mentions charge, leadership, preceptor, or similar
7. For bullet points: if the candidate listed responsibilities for a specific job, select
   MAXIMUM 5 (five) bullets — the most relevant and impactful ones a hiring manager
   would find most valuable.
   - For hospice jobs: prioritize end-of-life/comfort care, IDT involvement,
     symptom management, bereavement support, patient/family education
   - For LTC jobs: prioritize wound care, MDS/RAI experience, restorative nursing,
     dementia/memory care, skilled nursing procedures, rehab coordination
   Skip vague or generic statements (e.g. "provided patient care", "documented in EMR")
   unless they contain specific detail not captured elsewhere. Never invent, rephrase, or
   combine bullets — pull only from what the candidate wrote for THAT specific job.
   Use an empty array [] if none were listed.
   HARD LIMIT: return no more than 5 bullet strings in the array.
8. For additional_info:
   - If is_hospice is TRUE: capture hospice-specific items explicitly mentioned for
     that job — IDT (interdisciplinary team) meetings, bereavement support, comfort care,
     pain management, symptom management, end-of-life care, medication reconciliation,
     visit types, payer sources (Medicare/Medicaid), SOC/ROC/recertification visits,
     on-call duties, OASIS if applicable, etc.
   - If is_hospice is FALSE (LTC/SNF): capture LTC-specific items explicitly mentioned
     for that job — MDS/RAI assessments, wound care, restorative nursing, ADL assistance,
     fall prevention, dementia/Alzheimer's care, skilled nursing care, rehab coordination,
     care planning/care conferences, Medicare/Medicaid skilled care, therapy coordination
   Only include what is explicitly written for that job. Set to null if nothing found.
   NO DUPLICATES: do not list a term as its own bullet if it already appears inside
   a longer bullet. Use the more descriptive bullet and drop the redundant short one.
9. For "employed_through" (how the candidate was employed for that job):
   - "Travel"   — only if the resume lists a travel agency or explicitly says travel
   - "Per Diem" — only if the resume states per diem or PRN
   - "Direct"   — only if the resume explicitly states direct hire or direct employment
   - "Staff"    — default for all other regular/full-time/part-time employment; use when nothing specific is stated
10. For "role_level" (the candidate's staffing or supervisory level for that job):
    - Default is always "Staff"
    - Only use a different value if the resume explicitly states a supervisory title for that specific job
    - "Charge" if the resume mentions Charge Nurse, Charge RN, or similar
    - "Lead" if the resume mentions Lead Nurse or similar
    - "Supervisor" if the resume mentions Nursing Supervisor or similar
    - "Manager" if the resume mentions Nurse Manager or similar
    - NEVER infer a supervisory level — only use what is explicitly written
11. For "is_hospice": set to true if the job is a hospice position
    (hospice agency, inpatient hospice, palliative care, home hospice, etc.).
    Set to false for LTC/SNF/nursing home/assisted living/memory care/rehab facility,
    hospital, home health (non-hospice), or clinic positions.

For employment dates: only use dates you can confidently match to a specific job.
If the resume layout makes it unclear which date range belongs to which employer,
set "dates" to null — it will be highlighted yellow for recruiter verification.
Never assign a date to a job unless you are certain it is correct.

FINDING THE CANDIDATE NAME:
- The name is almost always the first or most prominent text at the top
- It is a person's full name only — no phone numbers, emails, or credentials
- full_name must contain ONLY the person's name, nothing else

CONTACT INFORMATION — never include in output:
- Do NOT put phone numbers, email addresses, or home addresses in any field
- If a bullet is just contact info, skip it entirely"""

    user_prompt = f"""Please analyze this nursing resume and extract all information into
the exact JSON structure below. This candidate works in hospice, long term care (LTC),
skilled nursing (SNF), or a mix of both.

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
      "each certification listed on the resume e.g. BLS, CHPN, CLTC, AANAC, OASIS-C, HCS-D"
    ]
  }},
  "experience": [
    {{
      "organization_name": "ORGANIZATION NAME IN ALL CAPS",
      "organization_city_state": "City, ST",
      "employed_through": "Staff or Direct or Travel or Per Diem — see rules above",
      "dates": "MM/YYYY – MM/YYYY or Present",
      "discipline": "RN or LPN",
      "role_level": "Staff — or Charge, Lead, Supervisor, Manager only if explicitly stated",
      "specialty": "hospice specialty or resident population from the resume",
      "role": "position title e.g. Case Manager, Charge Nurse, MDS Coordinator, Admissions Nurse, null if not listed",
      "is_hospice": true,
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
- is_hospice: true for hospice/palliative care jobs; false for LTC/SNF/nursing home/hospital/HH/clinic
- leadership_charge: true ONLY if that specific job mentions charge, leadership, or preceptor
- bullets: maximum 5 — most relevant specialty-specific skills, clinical procedures, and patient care details. Empty array [] if none listed.
- additional_info: a LIST of bullet strings (hospice-specific items for hospice jobs, LTC-specific for LTC jobs) — empty array [] if nothing applicable found
- emr and patient_caseload: only populate if explicitly on the resume
- state_licenses: include ALL nursing licenses listed — capture exactly as written. Do NOT include "Registered Nurse" or "Licensed Practical Nurse" as entries. Do NOT put certifications here. Empty array [] if none found.
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
        job.setdefault("employed_through", "Staff")
        job.setdefault("dates", "")
        job.setdefault("discipline", "")
        job.setdefault("role_level", "Staff")
        job.setdefault("specialty", None)
        job.setdefault("role", None)
        job.setdefault("emr", None)
        job.setdefault("patient_caseload", None)
        job.setdefault("is_hospice", True)
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
        if job["is_hospice"] is None:
            job["is_hospice"] = True

        # Strip contact info from bullets
        job["bullets"] = [
            b for b in job["bullets"]
            if b and not re.search(r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b', str(b))
            and not re.search(r'\S+@\S+\.\S+', str(b))
        ]
        # Hard cap: never more than 5 bullets
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
