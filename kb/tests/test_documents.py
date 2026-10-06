from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from docx import Document
from pypdf import PdfWriter

from documents import (
    EmptyDocument,
    UnsupportedDocument,
    document_title,
    extract_text,
    source_id_for_key,
)


def test_title_and_source_id_from_key() -> None:
    assert document_title("labels/enhertu-label.pdf") == "enhertu label"
    assert source_id_for_key("labels/enhertu-label.pdf") == "curated_doc:labels/enhertu-label.pdf"


def test_plain_text_and_markdown() -> None:
    assert extract_text("notes/faq.md", b"# FAQ\n\nMembers only.") == "# FAQ\n\nMembers only."
    assert extract_text("notes/readme.txt", "plain".encode()) == "plain"


def test_unsupported_extension() -> None:
    with pytest.raises(UnsupportedDocument):
        extract_text("images/scan.png", b"not a document")


def test_empty_text_file() -> None:
    with pytest.raises(EmptyDocument):
        extract_text("notes/empty.txt", b"   \n")


def test_pdf_text() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)

    with patch("documents.PdfReader") as mock_reader:
        page = MagicMock()
        page.extract_text.return_value = "DESTINY-Breast03 results"
        mock_reader.return_value.pages = [page]
        assert extract_text("trials/db03.pdf", buffer.getvalue()) == "DESTINY-Breast03 results"


def test_docx_text() -> None:
    document = Document()
    document.add_paragraph("Pembrolizumab label excerpt")
    buffer = BytesIO()
    document.save(buffer)

    assert extract_text("labels/pembro.docx", buffer.getvalue()) == "Pembrolizumab label excerpt"


def test_pdf_with_no_extractable_text() -> None:
    with patch("documents.PdfReader") as mock_reader:
        page = MagicMock()
        page.extract_text.return_value = "  "
        mock_reader.return_value.pages = [page]
        with pytest.raises(EmptyDocument):
            extract_text("scans/image-only.pdf", b"%PDF")
