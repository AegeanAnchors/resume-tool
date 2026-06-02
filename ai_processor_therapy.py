"""
ai_processor_therapy.py

Sends a resume to Claude AI and extracts all fields needed for the
Therapy template (PT, OT, SLP, PTA, COTA, RRT).

Key differences from nursing templates:
  - Covers multiple therapy disciplines: PT, OT, SLP, PTA, COTA, RRT
  - credential field = post-nominal letters (DPT, PT / OT / CCC-SLP / etc.)
  - profession field = full profession name (Physical Therapist, etc.)
  - Experience has no Employed Through, EMR, or Patient Caseload lines
  - Travel jobs use "Worksite:" prefix instead of an "Employed Through" line
  - Each job has a setting_specialty line (e.g. Outpatient Orthopedic, Acute Care)
  - Clinical experience entries have dates, role, duration, setting, and bullets
  - Non-therapy jobs (personal trainer, fitness, admin, etc.) are excluded
  - No web search — resume only. Anything not found = yellow highlight.
"""

import json
import os
import re
import anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def extract_resume_data_therapy(resume_text: str) -> dict:
    """
    Extracts all Therapy template fields from a resume.
    Returns a structured dictionary ready for the document generator.
    """
    client = anthropic.Anthropic()

    system_prompt = """You are an expert healthcare resume analyst for a medical staffing company.
Your job is to extract information from therapy resumes (PT, OT, SLP, PTA, COTA, RRT) with
perfect accuracy.

CRITICAL RULES YOU MUST FOLLOW:
1. NEVER invent, guess, estimate, or assume any information
2. ONLY use information explicitly written on the resume
3. If a field is not on the resume, set it to null — do not fill it in
4. For setting_specialty: derive from context — use terms like "Outpatient Orthopedic",
   "Acute Care", "Inpatient Rehab", "SNF/LTC", "Home Health", "School-Based",
   "Pediatrics", "Neuro Rehab", "Cardiac Rehab", "Sports Medicine", "Inpatient &
   Outpatient Orthopedic", etc. Use null if the setting cannot be determined.
5. For bullet points: if the candidate listed responsibilities, select MAXIMUM 5 (five)
   bullets — the most relevant and impactful ones a therapy hiring manager would value.
   Prioritize: specific patient populations, treatment techniques, specialized equipment,
   measurable outcomes, and setting-specific experience. Skip generic statements
   (e.g. "provided therapy services", "worked with patients") unless they add specific
   detail. Never invent, rephrase, or combine — pull only from what the candidate wrote
   for THAT specific job. HARD LIMIT: no more than 5 bullets per entry.
6. ONLY include therapy-relevant work experience (clinical positions as PT, OT, SLP,
   PTA, COTA, RRT, or therapy support roles). Exclude non-clinical jobs such as personal
   trainer, fitness coordinator, retail, food service, administrative, etc.
7. Clinical rotations / student placements go in clinical_experience, NOT in experience.
8. For "is_travel": set to true if the position was a travel contract (the candidate
   worked at that facility through a staffing agency as a traveler). Set to false for
   staff, per diem, and independent contractor positions.
9. For employment_type:
   - "Travel" if travel contract through a staffing agency
   - "Per Diem" if per diem / PRN
   - "IC" if independent contractor / 1099
   - "Staff" if regular employed position
10. For credential: capture the post-nominal letters exactly as written on the resume
    (e.g. "DPT, PT", "PT", "MOT, OTR/L", "OT", "CCC-SLP", "MS, SLP", "PTA", "COTA",
    "RRT", "CRT"). Do not include the candidate's name in this field.
11. For profession: the full professional title matching their discipline:
    - PT or DPT → "Physical Therapist"
    - OT or OTR → "Occupational Therapist"
    - SLP or CCC-SLP → "Speech-Language Pathologist"
    - PTA → "Physical Therapy Assistant"
    - COTA → "Certified Occupational Therapy Assistant"
    - RRT or CRT → "Respiratory Therapist"
12. For clinical experience duration: capture exactly as written (e.g. "10 weeks",
    "8 weeks", "12 weeks"). Set to null if not stated.

FINDING THE CANDIDATE NAME:
- The name is almost always the first or most prominent text at the top
- It is a person's full name only — no phone numbers, emails, or credentials
- full_name must contain ONLY the person's name, nothing else

CONTACT INFORMATION — never include in output:
- Do NOT put phone numbers, email addresses, or home addresses in any field
- If a bullet is just contact info, skip it entirely"""

    user_prompt = f"""Please analyze this therapy resume and extract all information into
the exact JSON structure below.

RESUME TEXT:
{resume_text}

Return ONLY a valid JSON object with this exact structure. No explanation, no markdown, just the JSON:

{{
  "candidate": {{
    "full_name": "candidate's full name only, no credentials",
    "credential": "post-nominal letters exactly as on resume e.g. DPT, PT or OT or CCC-SLP",
    "profession": "full profession name e.g. Physical Therapist",
    "phone_number": "candidate phone number exactly as written, or null if not found",
    "education": [
      {{
        "dates": "MM/YYYY or date range",
        "school": "SCHOOL NAME IN ALL CAPS",
        "location": "City, State",
        "degree": "degree name"
      }}
    ],
    "state_licenses": [
      "each license exactly as written e.g. Licensed in Georgia — one entry per state"
    ],
    "certifications": [
      "each certification listed e.g. Certified Strength and Conditioning Specialist, BLS"
    ]
  }},
  "experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "facility_city_state": "City, ST",
      "dates": "MM/YYYY – MM/YYYY or Present",
      "discipline": "Physical Therapist or Occupational Therapist or Speech-Language Pathologist etc.",
      "employment_type": "Travel or Staff or Per Diem or IC",
      "is_travel": true,
      "setting_specialty": "Outpatient Orthopedic or Acute Care or Inpatient Rehab etc., null if unknown",
      "bullets": []
    }}
  ],
  "clinical_experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "facility_city_state": "City, ST",
      "dates": "MM/YYYY – MM/YYYY",
      "role": "Physical Therapy Student or OT Student etc.",
      "duration": "10 weeks or null if not stated",
      "setting_specialty": "Outpatient Sports Orthopedic or Inpatient Rehab etc., null if unknown",
      "bullets": []
    }}
  ]
}}

IMPORTANT REMINDERS:
- experience: ONLY therapy clinical positions — exclude personal trainer, fitness, admin, etc.
- clinical_experience: student rotations / clinical placements only
- bullets: maximum 5 per entry — specialty-specific skills and patient care details over generic statements
- is_travel: true only for travel contract positions (staffing agency placements)
- state_licenses: include ALL nursing/therapy licenses listed — capture exactly as written. Empty array [] if none found
- certifications: ONLY actual certifications. Empty array [] if none found
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
    if "experience" not in data:
        raise ValueError("AI response is missing the 'experience' section.")

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

        # Strip contact info and hard cap at 5
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
    # Remove common credential suffixes that may bleed into the name field
    name = re.sub(
        r'\b(DPT|MPT|OTD|MOT|OTR|COTA|CCC-SLP|SLP|PTA|RRT|CRT|PT|OT|'
        r'RN|LPN|BSN|MSN|DNP|NP|APRN|CNA)\b', '', name
    )
    name = re.sub(r'[\s,\-]+', ' ', name).strip().strip(',').strip()
    if name:
        data["candidate"]["full_name"] = name
