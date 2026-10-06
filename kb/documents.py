"""Drop-zone documents for KB ingest.

An upload to the raw bucket (PDF, Word, or plain text) arrives as an S3
ObjectCreated event. This module reads the object and returns plain text.
Chunking, embedding, and the pgvector upsert stay in ingest.py, same as a
YouTube caption.
"""

from __future__ import annotations

import os
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from docx import Document
from pypdf import PdfReader

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".text", ".docx"}


class DocumentError(Exception):
    pass


class UnsupportedDocument(DocumentError):
    """File type we do not parse. The upload should be ignored, not retried."""


class EmptyDocument(DocumentError):
    """Parser ran and found no text."""


class DocumentUnavailable(DocumentError):
    """Object is gone. Retrying will not help."""


class DocumentFetchError(DocumentError):
    """Transient S3 failure."""


def _s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def _extension(key: str) -> str:
    name = key.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    if dot <= 0:
        return ""
    return name[dot:].lower()


def document_title(key: str) -> str:
    name = key.rsplit("/", 1)[-1]
    ext = _extension(key)
    stem = name[: -len(ext)] if ext and name.lower().endswith(ext) else name
    title = stem.replace("_", " ").replace("-", " ").strip()
    return title or name


def source_id_for_key(key: str) -> str:
    return f"curated_doc:{key}"


def _plain_text(data: bytes) -> str:
    return data.decode("utf-8")


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _docx_text(data: bytes) -> str:
    document = Document(BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())


def extract_text(key: str, data: bytes) -> str:
    ext = _extension(key)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDocument(f"unsupported file type for {key}")

    try:
        if ext == ".pdf":
            text = _pdf_text(data)
        elif ext == ".docx":
            text = _docx_text(data)
        else:
            text = _plain_text(data)
    except UnicodeDecodeError as exc:
        raise EmptyDocument(f"could not decode {key} as utf-8") from exc
    except Exception as exc:
        raise EmptyDocument(f"could not parse {key}: {exc}") from exc

    text = text.strip()
    if not text:
        raise EmptyDocument(f"no text extracted from {key}")
    return text


def _get_object(bucket: str, key: str) -> bytes:
    try:
        response = _s3_client().get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise DocumentUnavailable(f"s3://{bucket}/{key} not found") from exc
        raise DocumentFetchError(f"s3 get failed for s3://{bucket}/{key}: {exc}") from exc
    except Exception as exc:
        raise DocumentFetchError(f"s3 get failed for s3://{bucket}/{key}: {exc}") from exc

    return response["Body"].read()


def load_document(bucket: str, key: str) -> tuple[str, str]:
    """Return (plain text, title) for one drop-zone object."""
    return extract_text(key, _get_object(bucket, key)), document_title(key)
