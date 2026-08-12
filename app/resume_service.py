from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class ResumeParseError(ValueError):
    pass


def extract_resume_text(file_name: str, content: bytes) -> str:
    suffix = Path(file_name).suffix.lower()

    if suffix == ".txt":
        text = content.decode(
            "utf-8",
            errors="replace",
        )

    elif suffix == ".pdf":
        reader = PdfReader(BytesIO(content))

        pages = []

        for page in reader.pages:
            pages.append(
                page.extract_text()
                or ""
            )

        text = "\n".join(pages)

    elif suffix == ".docx":
        document = Document(BytesIO(content))

        text = "\n".join(
            paragraph.text
            for paragraph
            in document.paragraphs
        )

    else:
        raise ResumeParseError("Resume must be PDF, DOCX, or TXT.")

    text = text.strip()

    if not text:
        raise ResumeParseError("No readable text was found in the uploaded resume.")

    return text