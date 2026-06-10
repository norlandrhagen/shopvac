import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import obstore as obs
from obstore.store import from_url

logger = logging.getLogger(__name__)


def _resolve_aws_credentials(profile: Optional[str]) -> Dict[str, str]:
    """Resolve AWS credentials via boto3's full credential chain."""
    import boto3

    session = boto3.Session(profile_name=profile)
    raw = session.get_credentials()
    if raw is None:
        logger.debug("boto3 found no credentials for profile %r", profile)
        return {}
    frozen = raw.get_frozen_credentials()
    creds: Dict[str, str] = {
        "access_key_id": frozen.access_key,
        "secret_access_key": frozen.secret_key,
    }
    if frozen.token:
        creds["session_token"] = frozen.token
    region = session.region_name
    if region:
        creds["region"] = region
    return creds


class CloudStoreProvider(ABC):
    @abstractmethod
    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        pass

    @abstractmethod
    def get_supported_schemes(self) -> list[str]:
        pass


class S3StoreProvider(CloudStoreProvider):
    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        store_kwargs = self._prepare_store_kwargs(bucket_url, kwargs)
        return from_url(bucket_url, **store_kwargs)

    def get_supported_schemes(self) -> list[str]:
        return ["s3"]

    def _prepare_store_kwargs(
        self, bucket_url: str, cli_kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        store_kwargs: Dict[str, Any] = {"client_options": {"timeout": "600s"}}

        param_mapping = {
            "aws_region": "region",
            "aws_access_key_id": "access_key_id",
            "aws_secret_access_key": "secret_access_key",
            "aws_session_token": "session_token",
            "aws_profile": "profile",
            "aws_endpoint": "endpoint",
        }

        for cli_param, store_param in param_mapping.items():
            value = cli_kwargs.get(cli_param)
            if value is not None:
                store_kwargs[store_param] = value

        # obstore 0.10.x doesn't support profile= in from_url, and its credential
        # chain times out on IMDSv2 (169.254.169.254) on non-EC2 machines. Load
        # the profile credentials explicitly instead.
        explicit_creds = any(
            cli_kwargs.get(k) for k in ["aws_access_key_id", "aws_secret_access_key"]
        )
        if not explicit_creds:
            creds = _resolve_aws_credentials(cli_kwargs.get("aws_profile"))
            for k, v in creds.items():
                store_kwargs.setdefault(k, v)

        if cli_kwargs.get("skip_signature"):
            store_kwargs["skip_signature"] = True

        # Allow HTTP for non-HTTPS custom endpoints (e.g. local moto server)
        endpoint = store_kwargs.get("endpoint", "")
        if isinstance(endpoint, str) and endpoint.startswith("http://"):
            store_kwargs["client_options"] = {
                **store_kwargs.get("client_options", {}),
                "allow_http": True,
            }

        if "region" not in store_kwargs and not store_kwargs.get(
            "skip_signature", False
        ):
            bucket_name = urlparse(bucket_url).netloc
            logger.debug("No region provided, inferring for %s", bucket_name)
            try:
                region = self._find_bucket_region(bucket_name)
                logger.debug("Inferred region: %s", region)
                store_kwargs["region"] = region
            except Exception as e:
                logger.warning("Could not infer region for %s: %s", bucket_name, e)

        return store_kwargs

    def _find_bucket_region(self, bucket_name: str) -> str:
        """Infer S3 bucket region via HTTP HEAD redirect (no boto3 required)."""
        import urllib.request

        url = f"https://{bucket_name}.s3.amazonaws.com/"
        req = urllib.request.Request(url, method="HEAD")
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            region = e.headers.get("x-amz-bucket-region")
            if region:
                return region
            raise
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error inferring region: {e}") from e
        # 200 means us-east-1 (no redirect)
        return "us-east-1"


class GCSStoreProvider(CloudStoreProvider):
    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        store_kwargs = self._prepare_store_kwargs(kwargs)
        return from_url(bucket_url, **store_kwargs)

    def get_supported_schemes(self) -> list[str]:
        return ["gs"]

    def _prepare_store_kwargs(self, cli_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        store_kwargs: Dict[str, Any] = {"client_options": {"timeout": "600s"}}

        param_mapping = {
            "gcp_service_account_path": "service_account_path",
            "gcp_project_id": "project_id",
        }

        for cli_param, store_param in param_mapping.items():
            value = cli_kwargs.get(cli_param)
            if value is not None:
                store_kwargs[store_param] = value

        return store_kwargs


class StoreFactory:
    def __init__(self):
        self._providers: Dict[str, CloudStoreProvider] = {
            "s3": S3StoreProvider(),
            "gs": GCSStoreProvider(),
        }

    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        parsed = urlparse(bucket_url)
        scheme = parsed.scheme

        if scheme not in self._providers:
            raise ValueError(
                f"Unsupported URL scheme: {scheme!r}. Supported: {list(self._providers)}"
            )

        return self._providers[scheme].create_store(bucket_url, **kwargs)

    def get_supported_schemes(self) -> list[str]:
        return list(self._providers)


store_factory = StoreFactory()
