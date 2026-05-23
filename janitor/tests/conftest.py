import pytest


@pytest.fixture(autouse=True)
def isolate_from_localstack(monkeypatch):
    for name in (
        "AWS_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_EC2",
        "AWS_ENDPOINT_URL_S3",
        "AWS_ENDPOINT_URL_IAM",
        "AWS_ENDPOINT_URL_STS",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
