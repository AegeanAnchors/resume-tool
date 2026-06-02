"""
resume_parser.py

This file reads whatever resume file the recruiter uploads and converts it
into plain text. It handles four types of files:
  - Legacy Word documents (.doc)
  - Modern Word documents (.docx)
  - PDF files (.pdf)
  - Image files (.png, .jpg, .jpeg, .tiff, .bmp) — scans or photos of resumes

The output is always a single string of text that the AI can then read and
extract information from.
"""

import os
import base64
import subprocess
import tempfile
from docx import Document
import PyPDF2
from PIL import Image
import anthropic


def parse_resume(file_path: str) -> str:
    """
    Main function. Takes a file path, figures out what type of file it is,
    and returns all the text from it as a plain string.
    """
    # Get the file extension (e.g., ".pdf", ".docx") and make it lowercase
    _, extension = os.path.splitext(file_path)
    extension = extension.lower()

    if extension == ".doc":
        return _read_doc_file(file_path)

    elif extension == ".docx":
        return _read_word_document(file_path)

    elif extension == ".pdf":
        return _read_pdf(file_path)

    elif extension in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]:
        return _read_image(file_path)

    else:
        raise ValueError(
            f"Unsupported file type: '{extension}'. "
            "Please upload a .doc, .docx, .pdf, or image file (.png, .jpg, .jpeg, .tiff)."
        )


def _read_doc_file(file_path: str) -> str:
    """
    Reads a legacy .doc file (old binary Word format).

    python-docx cannot open .doc files directly.  macOS ships with a
    command-line tool called `textutil` that can silently convert .doc → .docx.
    We convert to a temporary .docx, parse it with our normal Word reader
    (which preserves header extraction, table reading, etc.), then delete the
    temp file.

    Falls back to plain-text extraction if the .docx conversion fails for any
    reason (e.g. a very old or malformed .doc file).
    """
    tmp_docx = None
    try:
        # Write the converted .docx to a temp file
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            tmp_docx = f.name

        result = subprocess.run(
            ["textutil", "-convert", "docx", file_path, "-output", tmp_docx],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0 and os.path.exists(tmp_docx):
            # Conversion succeeded — use the full Word reader (headers, tables, etc.)
            return _read_word_document(tmp_docx)

        # textutil returned an error — fall back to plain-text extraction
        raise RuntimeError(result.stderr or "textutil conversion returned non-zero exit code")

    except (FileNotFoundError, RuntimeError) as e:
        # textutil not available or conversion failed — try plain-text fallback
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            tmp_txt = f.name
        try:
            subprocess.run(
                ["textutil", "-convert", "txt", file_path, "-output", tmp_txt],
                capture_output=True,
                timeout=30,
            )
            if os.path.exists(tmp_txt):
                with open(tmp_txt, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read().strip()
                if text:
                    return text
        finally:
            if os.path.exists(tmp_txt):
                os.unlink(tmp_txt)

        raise ValueError(
            f"Could not read the .doc file. "
            f"Please try saving it as .docx in Microsoft Word and re-uploading. "
            f"(Technical detail: {e})"
        )
    finally:
        if tmp_docx and os.path.exists(tmp_docx):
            os.unlink(tmp_docx)


def _read_word_document(file_path: str) -> str:
    """
    Reads a Word document (.docx) and returns all its text.

    Important: many modern resume templates store the candidate's name
    and contact info in the Word document's header (not the body).
    We read headers FIRST so the name appears at the top of the text,
    exactly where Claude expects to find it.
    """
    doc = Document(file_path)
    lines = []

    # ── Step 1: Read headers first (name/contact often live here) ────────
    # We check both the regular header and the first-page header across
    # all sections, and add any text we find at the very top of the output.
    header_lines = []
    seen_header_text = set()
    for section in doc.sections:
        for header in [section.first_page_header, section.header]:
            try:
                for para in header.paragraphs:
                    text = para.text.strip()
                    if text and text not in seen_header_text:
                        seen_header_text.add(text)
                        header_lines.append(text)
            except Exception:
                pass  # Some headers can't be read — skip silently

    if header_lines:
        lines.extend(header_lines)

    # ── Step 2: Read all body paragraphs ─────────────────────────────────
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)

    # ── Step 3: Read any tables in the document ───────────────────────────
    for table in doc.tables:
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    row_text.append(cell_text)
            if row_text:
                lines.append(" | ".join(row_text))

    return "\n".join(lines)


def _read_pdf(file_path: str) -> str:
    """
    Reads a PDF file and returns all its text.
    Goes through every page and collects the text.
    """
    lines = []

    with open(file_path, "rb") as pdf_file:
        reader = PyPDF2.PdfReader(pdf_file)

        for page_number in range(len(reader.pages)):
            page = reader.pages[page_number]
            text = page.extract_text()
            if text:
                lines.append(text.strip())

    full_text = "\n".join(lines)

    # If PyPDF2 couldn't extract text (e.g., scanned PDF), let the user know
    if not full_text.strip():
        raise ValueError(
            "This PDF appears to be a scanned image and text could not be extracted directly. "
            "Please try saving it as a Word document or uploading it as an image file."
        )

    return full_text


def _read_image(file_path: str) -> str:
    """
    Reads an image file (photo or scan of a resume) and uses Claude's vision
    capability to extract all the text from it.

    This is the most powerful option — Claude can read handwriting, low-quality
    scans, and complex layouts that normal text-extraction tools would struggle with.
    """
    # Load the image and convert to base64 (a format the API can accept)
    with open(file_path, "rb") as image_file:
        image_data = base64.standard_b64encode(image_file.read()).decode("utf-8")

    # Figure out the correct media type for the image
    _, extension = os.path.splitext(file_path)
    extension = extension.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".bmp": "image/bmp",
    }
    media_type = media_type_map.get(extension, "image/jpeg")

    # Send the image to Claude and ask it to extract all the text
    client = anthropic.Anthropic()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is an image of a resume. Please extract ALL text from it exactly "
                            "as it appears, preserving the structure and layout as much as possible. "
                            "Include every word, date, facility name, credential, and detail you can see. "
                            "Do not summarize or interpret — just extract the raw text."
                        ),
                    },
                ],
            }
        ],
    )

    return message.content[0].text


def get_file_info(file_path: str) -> dict:
    """
    Returns basic information about the uploaded file.
    Useful for showing the recruiter what was uploaded.
    """
    _, extension = os.path.splitext(file_path)
    file_size = os.path.getsize(file_path)

    return {
        "filename": os.path.basename(file_path),
        "extension": extension.lower(),
        "size_kb": round(file_size / 1024, 1),
    }
