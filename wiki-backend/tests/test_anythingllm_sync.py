import pytest

from app.anythingllm_sync import (
    calculate_content_hash,
    _extract_remote_document_name,
    _find_existing_remote_document,
    _flatten_remote_documents,
)


def test_extract_remote_document_name_prefers_location() -> None:
    payload = {
        "documents": [
            {
                "location": "custom-documents/test.md-e26171f3.json",
                "name": "test.md-e26171f3.json",
            }
        ]
    }

    assert _extract_remote_document_name(payload) == "custom-documents/test.md-e26171f3.json"


def test_extract_remote_document_name_falls_back_to_name() -> None:
    payload = {"documents": [{"name": "test.md-e26171f3.json"}]}

    assert _extract_remote_document_name(payload) == "test.md-e26171f3.json"


def test_extract_remote_document_name_rejects_missing_name() -> None:
    with pytest.raises(RuntimeError, match="缺少文档 name/location"):
        _extract_remote_document_name({"documents": [{}]})


def test_calculate_content_hash_is_stable() -> None:
    assert calculate_content_hash(b"wiki") == calculate_content_hash(b"wiki")
    assert calculate_content_hash(b"wiki") != calculate_content_hash(b"anythingllm")


def test_flatten_remote_documents_reads_nested_files() -> None:
    payload = {
        "localFiles": {
            "name": "documents",
            "type": "folder",
            "items": [
                {
                    "name": "custom-documents",
                    "type": "folder",
                    "items": [
                        {
                            "name": "custom-documents/test.md-hash.json",
                            "type": "file",
                            "title": "test.md",
                        }
                    ],
                }
            ],
        }
    }

    documents = _flatten_remote_documents(payload)

    assert len(documents) == 1
    assert documents[0]["name"] == "custom-documents/test.md-hash.json"


def test_find_existing_remote_document_prefers_saved_name() -> None:
    documents = [
        {"name": "custom-documents/new.md-hash.json", "title": "new.md"},
        {"name": "custom-documents/test.md-hash.json", "title": "test.md"},
    ]

    assert _find_existing_remote_document(
        documents,
        remote_name="custom-documents/test.md-hash.json",
        filename="other.md",
    ) == "custom-documents/test.md-hash.json"


def test_find_existing_remote_document_falls_back_to_title() -> None:
    documents = [{"name": "custom-documents/test.md-hash.json", "title": "test.md"}]

    assert _find_existing_remote_document(
        documents,
        remote_name=None,
        filename="test.md",
    ) == "custom-documents/test.md-hash.json"
