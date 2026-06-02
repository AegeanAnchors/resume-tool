# Resume Formatting Tool — Security & Data Handling Overview

**Prepared for:** CIO Review  
**Environment:** Demo / Testing  
**Date:** June 2026  
**Status:** Demo environment — not yet configured for long-term production deployment

---

## 1. Purpose & Scope

The Resume Formatting Tool is an internal web application that allows recruiters to upload a candidate's raw resume and receive a standardized, formatted Word document. The tool uses AI-assisted extraction to identify and organize candidate information according to specialty-specific templates.

This document describes the security posture, data handling practices, and known limitations of the current demo environment, along with recommended steps before full production deployment.

---

## 2. System Architecture

```
Recruiter (Browser)
        │
        ▼
Streamlit Community Cloud  (HTTPS)
        │
        ├──▶  Anthropic Claude API  (AI field extraction)
        │
        ├──▶  Tavily Search API     (Acute Care only — facility data lookup)
        │
        └──▶  Output .docx delivered to browser
```

**No database. No file storage. No logging of candidate data.**

All processing occurs in memory within the Streamlit session. Temporary files written to disk during processing are immediately and automatically deleted before the session returns a result.

---

## 3. Candidate Data — What Is Processed

The following personally identifiable information (PII) is contained in uploaded resumes and processed by the tool:

| Data Element | How It Is Used | Stored? |
|---|---|---|
| Full name | Placed in formatted output document | ❌ No |
| Phone number | Placed in document header | ❌ No |
| Email address | Extracted but not placed in output | ❌ No |
| Work history (employer, dates, role) | Placed in formatted output | ❌ No |
| Education (school, degree, dates) | Placed in formatted output | ❌ No |
| State licenses & certifications | Placed in formatted output | ❌ No |

**No candidate data is written to a database, log file, or any persistent storage at any point.**

---

## 4. Data Flow — Step by Step

1. **Upload:** Recruiter uploads a resume file (.docx, .pdf, or image) via the browser. The file is transmitted over HTTPS to Streamlit's hosting infrastructure.

2. **Temporary file:** The uploaded file is written to a temporary location on the Streamlit server's ephemeral disk. This file exists only for the duration of processing (seconds).

3. **Text extraction:** The resume text is extracted from the temporary file into memory.

4. **AI extraction:** The extracted resume text is sent to **Anthropic's Claude API** via an encrypted HTTPS call. Claude identifies and structures the relevant fields (name, employer, dates, credentials, etc.) and returns a JSON object. No data is stored in this call beyond Anthropic's standard API data policy (see Section 6).

5. **Web research (Acute Care only):** For Acute Care templates, **facility names only** (not personal data) are sent to the **Tavily Search API** to retrieve publicly available facility information such as bed count and trauma level designation.

6. **Document generation:** The structured data is used to populate a formatted Word document entirely in memory on the Streamlit server.

7. **Delivery:** The completed .docx file is read into memory and delivered directly to the recruiter's browser as a download.

8. **Cleanup:** Both the input temporary file and the output temporary file are deleted immediately after the document is read into memory. This deletion occurs inside a `finally` block, meaning it happens even if an error occurs during processing.

9. **Session end:** When the recruiter's session ends, all session state (including the in-memory document bytes) is discarded by Streamlit automatically.

---

## 5. Security Controls Currently in Place

| Control | Implementation |
|---|---|
| Encrypted transport | All traffic served over HTTPS via Streamlit Community Cloud (TLS 1.2+) |
| Access control | Password gate on the application — required before any functionality is accessible |
| Secret management | API keys and app password stored in Streamlit's encrypted secrets vault — never in source code or version control |
| No persistent storage | No database, no file system writes beyond ephemeral temp files that are immediately deleted |
| Temp file cleanup | Guaranteed cleanup via `finally` block — runs even on processing errors |
| `.gitignore` enforcement | `.env` file, `secrets.toml`, and all test output documents are excluded from the GitHub repository |
| Private-ready repository | GitHub repository can be set back to private at any time without affecting the deployed app |

---

## 6. Third-Party Services — Data Policy Summary

### Anthropic (Claude API)
- **What is sent:** Full resume text (contains PII as listed in Section 3)
- **Anthropic's policy:** Anthropic does not use API inputs or outputs to train its models. API data is not used for any purpose other than providing the requested service.
- **Retention:** Anthropic may retain API inputs/outputs for up to 30 days for trust and safety review. This is standard for API customers and is separate from any model training activity.
- **Reference:** [https://www.anthropic.com/privacy](https://www.anthropic.com/privacy)

### Tavily (Search API)
- **What is sent:** Facility/employer names only — no personal candidate data
- **Purpose:** Looks up publicly available information about healthcare facilities (bed count, trauma level, teaching status) to fill fields not present on the resume
- **Used only for:** Acute Care (RN & LPN) template
- **Reference:** [https://tavily.com/privacy](https://tavily.com/privacy)

### Streamlit Community Cloud
- **What is hosted:** Application code and secrets (API keys, app password)
- **Candidate data:** Passes through ephemerally during session processing — not stored by Streamlit
- **Infrastructure:** Hosted on Google Cloud Platform
- **Reference:** [https://streamlit.io/privacy-policy](https://streamlit.io/privacy-policy)

---

## 7. Current Limitations — Demo Environment

The following are known gaps between the current demo environment and a fully hardened production deployment. These are expected for a testing environment and do not represent security incidents.

| Gap | Risk Level | Notes |
|---|---|---|
| Single shared password | Medium | Suitable for demo; production should use per-user authentication |
| No audit log | Medium | No record of who processed which resume or when |
| GitHub repository is public | Low | Source code only — no secrets or candidate data are in the repository |
| No rate limiting | Low | A single user could make excessive API calls; no business impact currently |
| No formal DPA with Anthropic | Medium | Data Processing Agreement recommended before production rollout |
| Streamlit Community Cloud (shared infrastructure) | Low–Medium | Suitable for demo/testing; production may warrant dedicated hosting |
| No session timeout | Low | Sessions persist until browser is closed |

---

## 8. Recommended Steps Before Full Production Deployment

1. **Per-user authentication** — Replace the shared password with individual user accounts (e.g., via Streamlit's built-in authentication, Okta SSO, or Azure AD)
2. **Audit logging** — Log (without PII) each processing event: timestamp, template used, recruiter ID, success/failure
3. **Data Processing Agreement** — Execute a formal DPA with Anthropic under their enterprise/business terms
4. **Dedicated hosting** — Move from Streamlit Community Cloud to a dedicated environment (AWS, Azure, or GCP) for greater control and compliance documentation
5. **Private GitHub repository** — Repository should be set back to private once a GitHub App integration is configured
6. **Formal privacy notice** — Display a formal data handling notice to users consistent with company policy
7. **Penetration testing** — Light security review of the hosted application before broader rollout
8. **IT security review** — Formal sign-off from IT/security team on Anthropic and Tavily as approved third-party processors

---

## 9. Source Code

All source code is available in the GitHub repository:  
**https://github.com/AegeanAnchors/resume-tool**

Key files:

| File | Purpose |
|---|---|
| `app.py` | Main application — UI, password gate, processing pipeline, privacy notice |
| `ai_processor*.py` | Claude API calls — one file per specialty template |
| `doc_generator*.py` | Word document generation — one file per specialty template |
| `resume_parser.py` | Extracts text from .docx, .pdf, and image files |
| `web_researcher.py` | Tavily API calls for Acute Care facility data |
| `requirements.txt` | All Python dependencies with pinned versions |
| `.gitignore` | Excludes secrets, credentials, and test files from version control |

---

## 10. Summary

For a demo and testing environment, the current security posture is appropriate:

- ✅ All candidate data is processed in memory and never stored
- ✅ Temporary files are deleted immediately after processing
- ✅ All traffic is encrypted in transit (HTTPS)
- ✅ Access is password-protected
- ✅ API keys are stored in an encrypted secrets vault, not in code
- ✅ No candidate data exists in the GitHub repository
- ⚠️ Third-party AI processing (Anthropic) involves transmission of resume PII — covered by Anthropic's standard API data policy; a formal DPA is recommended before production
- ⚠️ Per-user authentication and audit logging are recommended before broader internal rollout

---

*This document reflects the state of the demo environment as of June 2026. It should be updated prior to any production deployment.*
