"""
ai_processor_therapy_new_grad.py

Sends a resume to Claude AI and extracts all fields needed for the
Therapy New Grad template (PT, OT, SLP, PTA, COTA, RRT — recent graduates).

Key differences from the standard therapy processor:
  - Clinical rotations are the PRIMARY experience section
  - Work experience is typically absent or minimal (early-career jobs only)
  - No travel contracts expected — is_travel is always false
  - Skills/volunteer/internship entries are captured in clinical_experience
  - No web search — resume only. Anything not found = yellow highlight.
"""

import json
import os
import re
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def extract_resume_data_therapy_new_grad(resume_text: str) -> dict:
    """
    Extracts all Therapy New Grad template fields from a resume.
    Returns a structured dictionary ready for the document generator.
    """
    client = anthropic.Anthropic()

    system_prompt = """You are an expert healthcare resume analyst for a medical staffing company.
Your job is to extract information from new graduate therapy resumes (PT, OT, SLP, PTA, COTA, RRT)
with perfect accuracy. These candidates are recent graduates whose primary experience is clinical
rotations and fieldwork placements, not professional employment.

CRITICAL RULES YOU MUST FOLLOW:
1. NEVER invent, guess, estimate, or assume any information
2. ONLY use information explicitly written on the resume
3. If a field is not on the resume, set it to null — do not fill it in
4. Clinical rotations, student affiliations, fieldwork placements, and internships
   all go in clinical_experience — they are the PRIMARY content for new grads.
5. For experience (work experience): only include therapy clinical positions where the
   candidate was a paid employee (e.g. early part-time PT aide, rehab tech, etc.).
   Exclude non-therapy jobs entirely (personal trainer, retail, food service, etc.).
   Leave experience as an empty array [] if the candidate has no qualifying work history.
6. For bullet points in clinical_experience: if the candidate listed tasks/skills for a
   rotation, select MAXIMUM 5 (five) — the most relevant and impactful ones a hiring
   manager would value. Prioritize: specific patient populations, treatment techniques,
   specialized equipment, measurable outcomes. Never invent, rephrase, or combine.
   Pull only from what the candidate wrote for THAT specific entry. Empty array [] if none.
   HARD LIMIT: no more than 5 bullets per entry.
7. For setting_specialty: derive from context — use terms like "Outpatient Orthopedic",
   "Acute Care", "Inpatient Rehab", "SNF/LTC", "Home Health", "School-Based",
   "Pediatrics", "Neuro Rehab", "Cardiac Rehab", "Sports Medicine". Null if unclear.
8. For credential: post-nominal letters exactly as written (e.g. "DPT", "DPT, PT",
   "MOT, OTR/L", "CCC-SLP", "PTA", "COTA", "RRT"). Null if the candidate has not yet
   passed boards (write null, not empty).
9. For profession: the full professional title:
   - PT or DPT → "Physical Therapist"
   - OT or OTR → "Occupational Therapist"
   - SLP or CCC-SLP → "Speech-Language Pathologist"
   - PTA → "Physical Therapy Assistant"
   - COTA → "Certified Occupational Therapy Assistant"
   - RRT or CRT → "Respiratory Therapist"
10. For clinical duration: capture exactly as written (e.g. "10 weeks", "8 weeks").
    Set to null if not stated.

FINDING THE CANDIDATE NAME:
- The name is almost always the first or most prominent text at the top
- full_name must contain ONLY the person's name, nothing else

CONTACT INFORMATION — never include in output:
- Do NOT put phone numbers, email addresses, or home addresses in any field"""

    user_prompt = f"""Please analyze this new graduate therapy resume and extract all
information into the exact JSON structure below.

RESUME TEXT:
{resume_text}

Return ONLY a valid JSON object with this exact structure. No explanation, no markdown, just the JSON:

{{
  "candidate": {{
    "full_name": "candidate's full name only, no credentials",
    "credential": "post-nominal letters exactly as on resume e.g. DPT or OTR/L, or null if not yet licensed",
    "profession": "full profession name e.g. Physical Therapist",
    "phone_number": "candidate phone number exactly as written, or null if not found",
    "education": [
      {{
        "dates": "MM/YYYY or date range",
        "school": "SCHOOL NAME IN ALL CAPS",
        "location": "City, State",
        "degree": "degree name e.g. Doctor of Physical Therapy, Bachelor of Science in Occupational Therapy"
      }}
    ],
    "state_licenses": [
      "each license exactly as written — include state, license number, expiration if listed. Empty array [] if none."
    ],
    "certifications": [
      "each certification e.g. BLS, CPR, ACLS. Empty array [] if none."
    ]
  }},
  "experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "facility_city_state": "City, ST",
      "dates": "MM/YYYY – MM/YYYY or Present",
      "discipline": "Physical Therapist or Physical Therapy Aide etc.",
      "employment_type": "Staff or Per Diem",
      "is_travel": false,
      "setting_specialty": "Outpatient Orthopedic or Acute Care etc., null if unknown",
      "bullets": []
    }}
  ],
  "clinical_experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "facility_city_state": "City, ST",
      "dates": "MM/YYYY – MM/YYYY",
      "role": "Physical Therapy Student or OT Fieldwork Student etc.",
      "duration": "10 weeks or null if not stated",
      "setting_specialty": "Outpatient Sports Orthopedic or Inpatient Rehab etc., null if unknown",
      "bullets": []
    }}
  ]
}}

IMPORTANT REMINDERS:
- clinical_experience: student rotations, fieldwork, clinical affiliations, and internships — this is the PRIMARY content
- experience: ONLY paid therapy positions — exclude all non-therapy jobs. Empty array [] if none.
- bullets: maximum 5 per entry — specialty-specific skills and patient care details. Empty array [] if none listed.
- is_travel: always false for new grad positions
- state_licenses: capture exactly as written. Empty array [] if none found.
- certifications: ONLY actual certifications. Empty array [] if none found.
- phone_number: candidate's phone only
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


def _validate_and_fill_defaults(data: dict):
    """Fills in safe defaults for any missing fields so nothing crashes."""
    if "candidate" not in data:
        raise ValueError("AI response is missing the 'candidate' section.")

    candidate = data["candidate"]
    candidate.setdefault("full_name", "Unknown Candidate")
    candidate.setdefault("credential", "")
    candidate.setdefault("profession", "")
    candidate.setdefault("phone_number", None)
    candidate.setdefault("education", [])
    candidate.setdefault("state_licenses", [])
    candidate.setdefault("certifications", [])

    for edu in candidate.get("education", []):
        edu.setdefault("dates", "")
        edu.setdefault("school", "")
        edu.setdefault("location", "")
        edu.setdefault("degree", "")

    data.setdefault("experience", [])
    if data["experience"] is None:
        data["experience"] = []

    for job in data.get("experience", []):
        job.setdefault("facility_name", "UNKNOWN FACILITY")
        job.setdefault("facility_city_state", "")
        job.setdefault("dates", "")
        job.setdefault("discipline", "")
        job.setdefault("employment_type", "Staff")
        job.setdefault("is_travel", False)
        job.setdefault("setting_specialty", None)
        job.setdefault("bullets", [])

        if job["bullets"] is None:
            job["bullets"] = []
        if job["is_travel"] is None:
            job["is_travel"] = False

        job["bullets"] = [
            b for b in job["bullets"]
            if b and not re.search(r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b', str(b))
            and not re.search(r'\S+@\S+\.\S+', str(b))
        ]
        job["bullets"] = job["bullets"][:5]

    data.setdefault("clinical_experience", [])
    if data["clinical_experience"] is None:
        data["clinical_experience"] = []

    for entry in data.get("clinical_experience", []):
        entry.setdefault("facility_name", "")
        entry.setdefault("facility_city_state", "")
        entry.setdefault("dates", "")
        entry.setdefault("role", "")
        entry.setdefault("duration", None)
        entry.setdefault("setting_specialty", None)
        entry.setdefault("bullets", [])

        if entry["bullets"] is None:
            entry["bullets"] = []
        entry["bullets"] = [
            b for b in entry["bullets"]
            if b and not re.search(r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b', str(b))
            and not re.search(r'\S+@\S+\.\S+', str(b))
        ]
        entry["bullets"] = entry["bullets"][:5]


def _clean_candidate_name(data: dict):
    """Removes phone numbers, emails, and credentials from the name field."""
    name = data.get("candidate", {}).get("full_name", "")
    if not name:
        return
    name = re.sub(r'[\+\(]?\d[\d\s\-\.\(\)]{7,}\d', '', name)
    name = re.sub(r'\S+@\S+\.\S+', '', name)
    name = re.sub(
        r'\b(DPT|MPT|OTD|MOT|OTR|COTA|CCC-SLP|SLP|PTA|RRT|CRT|PT|OT|'
        r'RN|LPN|BSN|MSN|DNP|NP|APRN|CNA)\b', '', name
    )
    name = re.sub(r'[\s,\-]+', ' ', name).strip().strip(',').strip()
    if name:
        data["candidate"]["full_name"] = name
