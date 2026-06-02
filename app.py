"""
app.py

The Streamlit web interface for the Resume Formatting Tool.

What the recruiter sees:
  1. Upload a resume file (.docx, .pdf, or image)
  2. Select a template from the dropdown
  3. Click "Process Resume"
  4. Watch a live progress log while the tool works
  5. Click "Download Formatted Resume" when done

This file calls all four backend files:
  resume_parser.py  → reads the uploaded file
  ai_processor.py   → Claude AI extracts and structures all fields
  web_researcher.py → fills in missing fields from web search
  doc_generator.py  → builds the final Word document
"""

import os
import tempfile
import traceback
import streamlit as st
from dotenv import load_dotenv

# ─────────────────────────────────────────────
#  SECRETS INJECTION
#  Injects Streamlit Cloud secrets into os.environ so all backend
#  modules (anthropic, tavily) pick them up via os.getenv().
#  Falls back to .env when running locally.
# ─────────────────────────────────────────────

try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Import backend modules AFTER secrets are in os.environ
from resume_parser import parse_resume, get_file_info
from ai_processor import extract_resume_data, summarize_missing_fields
from web_researcher import research_missing_fields
from doc_generator import generate_document
from ai_processor_home_health import extract_resume_data_home_health
from doc_generator_home_health import generate_document_home_health
from ai_processor_hospice_ltc import extract_resume_data_hospice_ltc
from doc_generator_hospice_ltc import generate_document_hospice_ltc
from ai_processor_therapy import extract_resume_data_therapy
from doc_generator_therapy import generate_document_therapy
from ai_processor_therapy_new_grad import extract_resume_data_therapy_new_grad
from doc_generator_therapy_new_grad import generate_document_therapy_new_grad


# ─────────────────────────────────────────────
#  PAGE CONFIGURATION
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Resume Formatting Tool",
    page_icon="📄",
    layout="centered"
)


# ─────────────────────────────────────────────
#  PASSWORD GATE
#  If APP_PASSWORD is set in secrets, require it before showing the app.
#  If not configured (local dev), the gate is bypassed automatically.
# ─────────────────────────────────────────────

def _check_password():
    """Returns True if the user is authenticated (or no password is required)."""
    try:
        required = st.secrets["APP_PASSWORD"]
    except Exception:
        return True  # No password configured — open access (local dev)

    if st.session_state.get("authenticated"):
        return True

    # ── Login screen ──
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            st.image("logo.png", use_container_width=True)
        except Exception:
            st.title("📄 Resume Formatting Tool")

        st.markdown("### Sign In")
        pwd = st.text_input(
            "Access Password",
            type="password",
            placeholder="Enter password to continue",
            key="login_password"
        )
        if st.button("Sign In", type="primary", use_container_width=True):
            if pwd == required:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")

    st.stop()


_check_password()


# ─────────────────────────────────────────────
#  TEMPLATE DEFINITIONS
# ─────────────────────────────────────────────

TEMPLATES = {
    "Acute Care (RN & LPN)": "acute_care",
    "Home Health (RN & LPN)": "home_health",
    "Hospice / LTC / SNF (RN & LPN)": "hospice_ltc",
    "Therapy (PT, OT, SLP, PTA, COTA, RRT)": "therapy",
    "Therapy (New Grad)": "therapy_new_grad",
}

ACCEPTED_FILE_TYPES = ["doc", "docx", "pdf", "png", "jpg", "jpeg", "tiff", "tif"]


# ─────────────────────────────────────────────
#  SESSION STATE INITIALIZATION
# ─────────────────────────────────────────────

if "output_ready" not in st.session_state:
    st.session_state.output_ready = False
if "output_bytes" not in st.session_state:
    st.session_state.output_bytes = None
if "output_filename" not in st.session_state:
    st.session_state.output_filename = "Formatted_Resume.docx"
if "candidate_name" not in st.session_state:
    st.session_state.candidate_name = ""
if "processing" not in st.session_state:
    st.session_state.processing = False


# ─────────────────────────────────────────────
#  PAGE HEADER
# ─────────────────────────────────────────────

st.title("📄 Resume Formatting Tool")
st.markdown("Upload a candidate's resume, select a template, and get a perfectly formatted Word document.")

# ── Privacy Notice ───────────────────────────
with st.expander("🔒 Data Privacy & Security"):
    st.markdown("""
**How candidate data is handled:**

- Uploaded resumes are processed **in memory only** — no candidate data is written to a database or permanent storage.
- Temporary files created during processing are **immediately and automatically deleted** once your formatted document is generated.
- Resume text is sent to **Anthropic's Claude API** for AI-assisted field extraction. Anthropic does not use API inputs to train its models. [Anthropic Privacy Policy →](https://www.anthropic.com/privacy)
- For **Acute Care** templates only, **facility names** (not personal data) are used in a supplemental web search to look up publicly available information such as bed count and trauma designation.
- The formatted Word document is delivered directly to your browser. **No candidate information is retained** by this application after your session ends.
""")

st.divider()


# ─────────────────────────────────────────────
#  STEP 1: FILE UPLOAD
# ─────────────────────────────────────────────

st.subheader("Step 1 — Upload Resume")
uploaded_file = st.file_uploader(
    label="Upload the candidate's resume",
    type=ACCEPTED_FILE_TYPES,
    help="Accepted formats: Word (.doc, .docx), PDF (.pdf), or image (.png, .jpg, .jpeg, .tiff)"
)

if uploaded_file:
    st.success(f"✅ File uploaded: **{uploaded_file.name}** ({round(uploaded_file.size / 1024, 1)} KB)")


# ─────────────────────────────────────────────
#  STEP 2: TEMPLATE SELECTION
# ─────────────────────────────────────────────

st.subheader("Step 2 — Select Template")
selected_template_label = st.selectbox(
    label="Choose the specialty template",
    options=list(TEMPLATES.keys()),
    help="Select the template that matches the candidate's specialty"
)
selected_template = TEMPLATES[selected_template_label]


# ─────────────────────────────────────────────
#  STEP 3: PROCESS BUTTON
# ─────────────────────────────────────────────

st.subheader("Step 3 — Process")

# Reset the output if a new file is uploaded
if uploaded_file and st.session_state.output_ready:
    if st.session_state.get("last_uploaded_filename") != uploaded_file.name:
        st.session_state.output_ready = False
        st.session_state.output_bytes = None

process_button = st.button(
    "⚙️ Process Resume",
    type="primary",
    disabled=uploaded_file is None,
    use_container_width=True
)


# ─────────────────────────────────────────────
#  PROCESSING PIPELINE
# ─────────────────────────────────────────────

if process_button and uploaded_file:
    # Reset any previous output
    st.session_state.output_ready = False
    st.session_state.output_bytes = None
    st.session_state.last_uploaded_filename = uploaded_file.name

    tmp_input_path  = None
    tmp_output_path = None

    with st.status("Processing resume...", expanded=True) as status:
        try:
            # ── Save uploaded file to a temporary location ──────────────
            st.write("📂 Saving uploaded file...")
            suffix = os.path.splitext(uploaded_file.name)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
                tmp_in.write(uploaded_file.read())
                tmp_input_path = tmp_in.name

            # ── Step 1: Parse the resume ─────────────────────────────────
            st.write("📖 Reading resume...")
            resume_text = parse_resume(tmp_input_path)
            st.write(f"   ✅ Resume read successfully ({len(resume_text.split())} words extracted)")

            # ── Step 2: AI extraction ────────────────────────────────────
            st.write("🤖 Sending to Claude AI for analysis...")

            if selected_template == "acute_care":
                data = extract_resume_data(resume_text)
            elif selected_template == "home_health":
                data = extract_resume_data_home_health(resume_text)
            elif selected_template == "hospice_ltc":
                data = extract_resume_data_hospice_ltc(resume_text)
            elif selected_template == "therapy":
                data = extract_resume_data_therapy(resume_text)
            elif selected_template == "therapy_new_grad":
                data = extract_resume_data_therapy_new_grad(resume_text)
            else:
                data = extract_resume_data(resume_text)  # fallback

            candidate      = data["candidate"]
            candidate_name = candidate.get("full_name", "Candidate")
            st.session_state.candidate_name = candidate_name
            job_count = len(data.get("experience", []))
            st.write(f"   ✅ Identified: **{candidate_name}**, **{job_count}** job(s) found")

            # ── Step 3: Web research (Acute Care only) ───────────────────
            if selected_template == "acute_care":
                missing_jobs = summarize_missing_fields(data)
                if missing_jobs:
                    total_missing = sum(len(j["missing_fields"]) for j in missing_jobs)
                    st.write(f"🔍 Searching web for **{total_missing}** missing field(s) across **{len(missing_jobs)}** job(s)...")
                    for job_info in missing_jobs:
                        st.write(f"   Researching: {job_info['facility_name']}...")
                    data = research_missing_fields(data, missing_jobs)
                    st.write("   ✅ Web research complete")
                else:
                    st.write("✅ All fields found on resume — no web search needed")
            else:
                st.write("✅ Resume-only template — no web search needed")

            # ── Step 4: Generate Word document ───────────────────────────
            st.write("📝 Building formatted Word document...")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_out:
                tmp_output_path = tmp_out.name

            if selected_template == "acute_care":
                generate_document(data, tmp_output_path)
            elif selected_template == "home_health":
                generate_document_home_health(data, tmp_output_path)
            elif selected_template == "hospice_ltc":
                generate_document_hospice_ltc(data, tmp_output_path)
            elif selected_template == "therapy":
                generate_document_therapy(data, tmp_output_path)
            elif selected_template == "therapy_new_grad":
                generate_document_therapy_new_grad(data, tmp_output_path)
            else:
                generate_document(data, tmp_output_path)  # fallback

            # Read the finished file into memory for the download button
            with open(tmp_output_path, "rb") as f:
                st.session_state.output_bytes = f.read()

            # Output filename = original uploaded filename + "_FORMATTED"
            original_name = os.path.splitext(uploaded_file.name)[0]
            st.session_state.output_filename = f"{original_name}_FORMATTED.docx"
            st.session_state.output_ready    = True

            status.update(
                label=f"✅ Done! **{candidate_name}** — {selected_template_label} resume ready.",
                state="complete",
                expanded=False
            )

        except Exception as e:
            status.update(label="❌ Something went wrong", state="error", expanded=True)
            st.error(f"**Error:** {str(e)}")
            with st.expander("Technical details (for troubleshooting)"):
                st.code(traceback.format_exc())
            st.info("💡 **Common fixes:** Make sure the file isn't password protected. "
                    "If uploading an image, make sure it's clear and readable.")

        finally:
            # ── Always clean up temp files, even on error ────────────────
            for path in (tmp_input_path, tmp_output_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception:
                        pass


# ─────────────────────────────────────────────
#  STEP 4: DOWNLOAD
# ─────────────────────────────────────────────

if st.session_state.output_ready and st.session_state.output_bytes:
    st.divider()
    st.subheader("Step 4 — Download")
    st.success(f"✅ **{st.session_state.candidate_name}** — formatted resume is ready!")

    st.download_button(
        label="⬇️ Download Formatted Resume",
        data=st.session_state.output_bytes,
        file_name=st.session_state.output_filename,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary",
        use_container_width=True
    )

    st.caption(
        "💡 Any fields highlighted in yellow could not be verified and should be reviewed "
        "by the recruiter before sending to a client."
    )


# ─────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────

st.divider()
st.caption(
    "Resume Formatting Tool — Core Medical Group  |  "
    "Fields highlighted yellow require recruiter verification  |  "
    "Candidate data is processed in memory only and is never stored."
)
