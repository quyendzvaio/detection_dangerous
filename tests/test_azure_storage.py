from urllib.parse import parse_qs, urlsplit

from backend.storage import AzureBlobStorage

_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=industrialsafety;"
    "AccountKey=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWYwMTIzNDU2Nzg5YWJjZGVm"
    "MDEyMzQ1Njc4OWFiY2RlZg==;"
    "BlobEndpoint=http://127.0.0.1:10000/industrialsafety;"
)


def test_azure_storage_creates_scoped_sas_urls_and_required_put_headers():
    storage = AzureBlobStorage(
        connection_string=_CONNECTION_STRING,
        container="industrial-safety-evidence",
        public_blob_endpoint="http://127.0.0.1:10000/industrialsafety",
    )

    upload = storage.create_upload_lease(
        "evidence/camera-1/image.jpg", "image/jpeg", 300
    )
    upload_query = parse_qs(urlsplit(upload.url).query)

    assert storage.client.api_version == "2025-11-05"
    assert upload.url.startswith(
        "http://127.0.0.1:10000/industrialsafety/"
        "industrial-safety-evidence/evidence/camera-1/image.jpg?"
    )
    assert upload_query["sp"] == ["cw"]
    assert upload.headers == {
        "Content-Type": "image/jpeg",
        "x-ms-blob-type": "BlockBlob",
        "x-ms-blob-content-type": "image/jpeg",
    }
    assert upload.expires_in_seconds == 300

    download_query = parse_qs(
        urlsplit(
            storage.create_download_url("evidence/camera-1/image.jpg", 300)
        ).query
    )
    assert download_query["sp"] == ["r"]
