"""
ai_processor.py

This is the brain of the tool. It takes the raw text from a resume and sends
it to Claude AI with very specific instructions. Claude reads the resume and
returns a perfectly organized, structured breakdown of every field we need
for the Acute Care template.

Rules Claude must follow (enforced in the prompt):
  - NEVER invent, guess, or assume any information
  - Only pull from what the candidate explicitly wrote on their resume
  - Mark missing fields as null so the web researcher can try to find them
  - Only note leadership/charge for the specific job it was mentioned
  - Only include bullet points for jobs where the candidate listed responsibilities
  - Employment type: Travel (if agency), Per Diem (if stated), Staff (if direct/full-time)
"""

import json
import os
import re
import anthropic
from dotenv import load_dotenv

# Load the API keys from the .env file in the project folder
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def extract_resume_data(resume_text: str) -> dict:
    """
    Main function. Takes the raw resume text and returns a structured
    dictionary (organized data) with everything mapped to our template fields.

    Fields marked as null need the web researcher to look them up.
    Fields marked as "NEEDS_HIGHLIGHT" couldn't be found anywhere and
    will be highlighted yellow in the final document.
    """

    client = anthropic.Anthropic()

    # The system prompt tells Claude what role it's playing
    system_prompt = """You are an expert healthcare resume analyst for a medical staffing company.
Your job is to extract information from nursing resumes with perfect accuracy.

CRITICAL RULES YOU MUST FOLLOW:
1. NEVER invent, guess, estimate, or assume any information
2. ONLY use information explicitly written on the resume
3. If a field is not on the resume, set it to null — do not fill it in
4. For EMR/charting systems: only fill in if the resume explicitly names one (e.g., Epic, Cerner, Meditech, Soarian)
5. For patient caseload: only fill in if the candidate explicitly stated their caseload
6. For leadership/charge experience: only set to true for a specific job if that job's description mentions charge, leadership, preceptor, or similar
7. For bullet points: if the candidate listed responsibilities for a specific job, select
   MAXIMUM 5 (five) bullets — the most relevant and impactful ones an acute care hiring
   manager would find most valuable. Prioritize: specific clinical skills, procedures,
   equipment, patient population details, measurable outcomes, and unit/specialty-specific
   experience. Skip vague or generic statements (e.g. "provided patient care", "worked as
   part of a team", "documented in the EMR") unless they contain specific detail not
   captured elsewhere. Never invent, rephrase, or combine bullets — pull only from what
   the candidate wrote for THAT specific job. Use an empty array [] if none were listed.
   HARD LIMIT: return no more than 5 bullet strings in the array.
8. For "employed_through" (how the candidate was employed for that job):
   - "Travel"   — only if the resume lists a travel agency or explicitly says travel
   - "Per Diem" — only if the resume states per diem or PRN
   - "Direct"   — only if the resume explicitly states direct hire or direct employment
   - "Staff"    — default for all other regular/full-time/part-time employment; use when nothing specific is stated
9. For "role_level" (the candidate's staffing or supervisory level for that job):
   - Default is always "Staff"
   - Only use a different value if the resume explicitly states a supervisory title for that specific job
   - "Charge" if the resume mentions Charge Nurse, Charge RN, or similar
   - "Lead" if the resume mentions Lead Nurse, Lead RN, or similar
   - "Supervisor" if the resume mentions Nursing Supervisor or similar
   - "Manager" if the resume mentions Nurse Manager or similar
   - NEVER infer a supervisory level — only use what is explicitly written

FINDING THE CANDIDATE NAME — very important:
- The candidate's name is almost always the very first line of the resume, or the largest/most prominent text at the top
- It is a person's full name — first name and last name (sometimes middle name too)
- It will NOT contain numbers, symbols, phone numbers, email addresses, or job titles
- NEVER put a phone number, email, address, or credential (RN, LPN, BSN) in the full_name field
- If the top of the resume has the name mixed with contact info, extract ONLY the name portion
- full_name must be ONLY the person's name — nothing else

CONTACT INFORMATION — never include in output:
- Do NOT put phone numbers, email addresses, or home addresses anywhere in the JSON
- These are personal contact details that do not belong in any field of our template
- If a bullet point is just contact info, skip it entirely"""

    # The user prompt gives Claude the resume and tells it exactly what to return
    user_prompt = f"""Please analyze this resume and extract all information into the exact JSON structure below.

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
      "each certification listed on the resume e.g. BLS, ACLS, PALS, CEN, specialty certs"
    ]
  }},
  "experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "facility_city_state": "City, ST",
      "employed_through": "Staff or Direct or Travel or Per Diem — see rules above",
      "dates": "MM/YYYY – MM/YYYY or Present",
      "discipline": "RN or LPN",
      "role_level": "Staff — or Charge, Lead, Supervisor, Manager only if explicitly stated",
      "specialty": "the unit/specialty they worked",
      "emr": "EMR system name if explicitly on resume, otherwise null",
      "total_staffed_beds": "number if on resume, otherwise null",
      "facility_type": "trauma level if on resume, otherwise null",
      "teaching_status": "Teaching Facility or Non-Teaching Facility if on resume, otherwise null",
      "patient_caseload": "caseload if explicitly stated on resume, otherwise null",
      "leadership_charge": false,
      "bullets": []
    }}
  ],
  "clinical_experience": [
    {{
      "facility_name": "FACILITY NAME IN ALL CAPS",
      "specialty_rotation": "description of the clinical rotation",
      "total_staffed_beds": "number if on resume, otherwise null"
    }}
  ]
}}

IMPORTANT REMINDERS BEFORE YOU RESPOND:
- leadership_charge must be true ONLY if that specific job mentions charge, leadership, or preceptor duties
- bullets: maximum 5 bullets — most relevant specialty-specific skills, procedures, and patient care details. Empty array [] if no responsibilities listed.
- emr and patient_caseload must be null if not explicitly written on the resume
- state_licenses: include ALL nursing licenses listed on the resume — state licenses, license numbers, compact licenses, multi-state licenses, expiration dates if listed. Capture each one exactly as written. Do NOT include "Registered Nurse" or "Licensed Practical Nurse" as entries — those are the discipline, not a license. Do NOT put certifications (BLS, ACLS, etc.) here. If none found, use empty array []
- certifications: ONLY include actual certifications (BLS, ACLS, PALS, CEN, CCRN, specialty certs, etc.). If none found, use empty array []
- Return ONLY the JSON, nothing else"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        system=system_prompt
    )

    # Get the text response from Claude
    response_text = message.content[0].text.strip()

    # Clean up the response in case Claude wrapped it in markdown code blocks
    # (sometimes AI responses include ```json ... ``` around the JSON)
    if response_text.startswith("```"):
        response_text = re.sub(r"```(?:json)?", "", response_text).strip()
        response_text = response_text.rstrip("`").strip()

    # Parse the JSON string into a Python dictionary
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned an unexpected response format. "
            f"JSON parsing error: {e}\n\nRaw response:\n{response_text[:500]}"
        )

    # Validate that the response has the structure we expect
    _validate_structure(data)

    # Safety check: clean the candidate name of any contact info that slipped through
    _clean_candidate_name(data)

    return data


def _clean_candidate_name(data: dict):
    """
    Makes sure the candidate's full_name field contains only a person's name.
    Removes phone numbers, emails, addresses, and credentials if they
    accidentally ended up in the name field.
    """
    import re
    name = data.get("candidate", {}).get("full_name", "")
    if not name:
        return

    # Remove anything that looks like a phone number (digits with dashes, dots, parens)
    name = re.sub(r'[\+\(]?\d[\d\s\-\.\(\)]{7,}\d', '', name)
    # Remove anything that looks like an email address
    name = re.sub(r'\S+@\S+\.\S+', '', name)
    # Remove credential suffixes (RN, LPN, BSN, MSN, etc.) — these go in the credential field
    name = re.sub(r'\b(RN|LPN|BSN|MSN|DNP|NP|APRN|CNA|RRT|PT|OT|SLP|COTA|PTA)\b', '', name)
    # Clean up extra spaces, commas, dashes left over
    name = re.sub(r'[\s,\-]+', ' ', name).strip().strip(',').strip()

    if name:
        data["candidate"]["full_name"] = name
    # If after cleaning the name is empty, leave it as-is so the yellow
    # fallback ("UNKNOWN CANDIDATE") makes it obvious to the recruiter


def _validate_structure(data: dict):
    """
    Makes sure Claude returned the minimum fields we need.
    Fills in safe defaults for anything optional that's missing,
    so a resume with an unusual structure doesn't crash the tool.
    """
    if "candidate" not in data:
        raise ValueError("AI response is missing the 'candidate' section.")
    if "experience" not in data:
        raise ValueError("AI response is missing the 'experience' section.")

    # Fill in safe defaults for any missing candidate fields
    candidate = data["candidate"]
    candidate.setdefault("full_name", "Unknown Candidate")
    candidate.setdefault("credential", "")
    candidate.setdefault("phone_number", None)
    candidate.setdefault("education", [])
    candidate.setdefault("state_licenses", [])
    candidate.setdefault("certifications", [])

    # Ensure education entries are complete
    for edu in candidate.get("education", []):
        edu.setdefault("dates", "")
        edu.setdefault("school", "")
        edu.setdefault("location", "")
        edu.setdefault("degree", "")

    # Fill in safe defaults for any missing fields on each job
    for i, job in enumerate(data.get("experience", [])):
        job.setdefault("facility_name", f"FACILITY #{i+1}")
        job.setdefault("facility_city_state", "")
        job.setdefault("employed_through", "Staff")
        job.setdefault("dates", "")
        job.setdefault("discipline", "")
        job.setdefault("role_level", "Staff")
        job.setdefault("specialty", None)
        job.setdefault("emr", None)
        job.setdefault("total_staffed_beds", None)
        job.setdefault("facility_type", None)
        job.setdefault("teaching_status", None)
        job.setdefault("patient_caseload", None)
        job.setdefault("leadership_charge", False)
        job.setdefault("bullets", [])
        # Ensure bullets is a list, not null
        if job["bullets"] is None:
            job["bullets"] = []
        # Remove any bullets that are just contact info (phone, email, address)
        import re
        job["bullets"] = [
            b for b in job["bullets"]
            if b and not re.search(r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b', str(b))
            and not re.search(r'\S+@\S+\.\S+', str(b))
        ]
        # Hard cap: never more than 5 bullets regardless of what the AI returned
        job["bullets"] = job["bullets"][:5]
        # Ensure leadership_charge is a boolean, not null
        if job["leadership_charge"] is None:
            job["leadership_charge"] = False

    # Ensure clinical_experience exists
    data.setdefault("clinical_experience", [])
    if data["clinical_experience"] is None:
        data["clinical_experience"] = []

    # Fill in safe defaults for clinical entries
    for entry in data.get("clinical_experience", []):
        entry.setdefault("facility_name", "")
        entry.setdefault("specialty_rotation", "")
        entry.setdefault("total_staffed_beds", None)


def summarize_missing_fields(data: dict) -> list:
    """
    Looks at the extracted data and returns a list of fields that are null
    (missing from the resume). These are the fields the web researcher will
    try to find.

    Returns a list of dictionaries, one per job that has missing fields.
    """
    missing = []

    for i, job in enumerate(data.get("experience", [])):
        job_missing = {
            "job_index": i,
            "facility_name": job["facility_name"],
            "facility_city_state": job["facility_city_state"],
            "missing_fields": []
        }

        # Check each field that might need web research
        searchable_fields = ["emr", "total_staffed_beds", "facility_type", "teaching_status"]
        for field in searchable_fields:
            if job.get(field) is None:
                job_missing["missing_fields"].append(field)

        # Patient caseload is NOT added to the web search list —
        # it must only come from the resume itself
        # (too variable to verify reliably from a web search)

        if job_missing["missing_fields"]:
            missing.append(job_missing)

    return missing


def print_summary(data: dict):
    """
    Prints a human-readable summary of what was extracted.
    Useful for checking the AI did its job correctly.
    """
    candidate = data["candidate"]
    print(f"\n{'='*60}")
    print(f"CANDIDATE: {candidate['full_name']}, {candidate['credential']}")
    print(f"{'='*60}")

    print(f"\nEDUCATION ({len(candidate['education'])} entries):")
    for edu in candidate["education"]:
        print(f"  {edu['dates']} — {edu['school']}, {edu['location']}")
        print(f"    {edu['degree']}")

    print(f"\nSTATE LICENSES:")
    licenses = candidate.get("state_licenses", [])
    if licenses:
        for lic in licenses:
            print(f"  • {lic}")
    else:
        print("  ⚠ None found on resume — will show yellow prompt")

    print(f"\nCERTIFICATIONS:")
    certs = candidate.get("certifications", [])
    if certs:
        for cert in certs:
            print(f"  • {cert}")
    else:
        print("  ⚠ None found on resume")

    print(f"\nEXPERIENCE ({len(data['experience'])} jobs):")
    for job in data["experience"]:
        print(f"\n  {job['dates']} — {job['facility_name']}, {job['facility_city_state']}")
        print(f"    Discipline: {job['discipline']} ({job['employment_type']})")
        print(f"    Specialty:  {job['specialty']}")
        print(f"    EMR:        {job['emr'] or '⚠ MISSING'}")
        print(f"    Beds:       {job['total_staffed_beds'] or '⚠ MISSING'}")
        print(f"    Trauma:     {job['facility_type'] or '⚠ MISSING'}")
        print(f"    Teaching:   {job['teaching_status'] or '⚠ MISSING'}")
        print(f"    Caseload:   {job['patient_caseload'] or '⚠ MISSING (will highlight yellow)'}")
        print(f"    Charge:     {'Yes' if job['leadership_charge'] else 'No'}")
        print(f"    Bullets:    {len(job['bullets'])} listed")

    if data.get("clinical_experience"):
        print(f"\nCLINICAL EXPERIENCE ({len(data['clinical_experience'])} entries):")
        for clinical in data["clinical_experience"]:
            print(f"  • {clinical['facility_name']} — {clinical['specialty_rotation']}")
