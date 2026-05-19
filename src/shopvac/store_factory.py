# src/shopvac/store_factory.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import requests
from urllib.parse import urlparse
import configparser
from pathlib import Path

import obstore as obs
from obstore.store import from_url


class CloudStoreProvider(ABC):
    """Abstract base class for cloud storage providers."""

    @abstractmethod
    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        """Create an obstore instance for the provider."""
        pass

    @abstractmethod
    def get_supported_schemes(self) -> list[str]:
        """Return list of URL schemes this provider supports."""
        pass


class S3StoreProvider(CloudStoreProvider):
    """AWS S3 store provider."""

    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        """Create S3Store using from_url with AWS-specific options."""
        store_kwargs = self._prepare_store_kwargs(bucket_url, kwargs)
        return from_url(bucket_url, **store_kwargs)

    def get_supported_schemes(self) -> list[str]:
        return ["s3"]

    def _prepare_store_kwargs(
        self, bucket_url: str, cli_kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare kwargs for from_url, handling S3-specific logic."""
        store_kwargs = {"client_options": {"timeout": "600s"}}

        # Determine which profile to use
        profile_name = cli_kwargs.get(
            "aws_profile", "default"
        )  # Default to 'default' profile

        # Try to load AWS profile credentials (only if no explicit credentials provided)
        explicit_creds = any(
            cli_kwargs.get(key)
            for key in ["aws_access_key_id", "aws_secret_access_key"]
        )

        if not explicit_creds:
            creds = self._load_aws_profile_credentials(profile_name)
            if creds:
                store_kwargs.update(creds)
                if cli_kwargs.get("aws_profile"):
                    print(f"Loaded credentials from AWS profile: {profile_name}")
                else:
                    print(
                        f"Loaded credentials from default AWS profile: {profile_name}"
                    )

        # Map CLI parameters to from_url parameters (these will override profile credentials)
        param_mapping = {
            "aws_region": "region",
            "aws_access_key_id": "access_key_id",
            "aws_secret_access_key": "secret_access_key",
            "aws_session_token": "session_token",
            "aws_endpoint": "endpoint",
            "skip_signature": "skip_signature",
        }

        # Add provided parameters (these will override profile credentials)
        for cli_param, store_param in param_mapping.items():
            if cli_kwargs.get(cli_param) is not None:
                store_kwargs[store_param] = cli_kwargs[cli_param]

        # Allow HTTP when using a non-HTTPS custom endpoint (e.g. local moto server)
        endpoint = store_kwargs.get("endpoint", "")
        if endpoint.startswith("http://"):
            store_kwargs["client_options"] = {
                **store_kwargs.get("client_options", {}),
                "allow_http": True,
            }

        # Handle region inference if needed
        if "region" not in store_kwargs and not store_kwargs.get(
            "skip_signature", False
        ):
            bucket_name = urlparse(bucket_url).netloc
            print(
                f"No region provided for S3 bucket. Attempting to infer region for {bucket_name}..."
            )
            try:
                inferred_region = self._find_bucket_region(bucket_name)
                print(f"Inferred region: {inferred_region}")
                store_kwargs["region"] = inferred_region
            except Exception as e:
                print(f"Warning: Could not infer region for bucket {bucket_name}: {e}")
                print("You may need to specify --aws-region explicitly")

        return store_kwargs

    def _find_bucket_region(self, bucket_name: str) -> str:
        """Find the AWS region for an S3 bucket using a HEAD request."""
        resp = requests.head(f"https://{bucket_name}.s3.amazonaws.com")
        return resp.headers["x-amz-bucket-region"]

    def _load_aws_profile_credentials(
        self, profile_name: str
    ) -> Optional[Dict[str, str]]:
        """Load AWS credentials from ~/.aws/credentials file."""
        credentials_path = Path.home() / ".aws" / "credentials"
        config_path = Path.home() / ".aws" / "config"

        if not credentials_path.exists():
            print(f"AWS credentials file not found at {credentials_path}")
            return None

        try:
            # Load credentials
            config = configparser.ConfigParser()
            config.read(credentials_path)

            if profile_name not in config:
                print(f"Profile '{profile_name}' not found in AWS credentials file")
                return None

            creds = {}
            profile_section = config[profile_name]

            if "aws_access_key_id" in profile_section:
                creds["access_key_id"] = profile_section["aws_access_key_id"]
            if "aws_secret_access_key" in profile_section:
                creds["secret_access_key"] = profile_section["aws_secret_access_key"]
            if "aws_session_token" in profile_section:
                creds["session_token"] = profile_section["aws_session_token"]

            # Also try to load region from config file
            if config_path.exists():
                config_file = configparser.ConfigParser()
                config_file.read(config_path)

                # Check both [default] and [profile profile_name] formats
                config_section_names = [profile_name, f"profile {profile_name}"]
                for section_name in config_section_names:
                    if (
                        section_name in config_file
                        and "region" in config_file[section_name]
                    ):
                        creds["region"] = config_file[section_name]["region"]
                        break

            return creds if creds else None

        except Exception as e:
            print(f"Error loading AWS profile '{profile_name}': {e}")
            return None


class GCSStoreProvider(CloudStoreProvider):
    """Google Cloud Storage store provider."""

    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        """Create GCS store using from_url with GCP-specific options."""
        store_kwargs = self._prepare_store_kwargs(kwargs)
        return from_url(bucket_url, **store_kwargs)

    def get_supported_schemes(self) -> list[str]:
        return ["gs"]

    def _prepare_store_kwargs(self, cli_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare kwargs for from_url."""
        store_kwargs = {"client_options": {"timeout": "600s"}}

        # Map CLI parameters to from_url parameters
        param_mapping = {
            "gcp_service_account_path": "service_account_path",
            "gcp_project_id": "project_id",
        }

        for cli_param, store_param in param_mapping.items():
            if cli_kwargs.get(cli_param) is not None:
                store_kwargs[store_param] = cli_kwargs[cli_param]

        return store_kwargs


class StoreFactory:
    """Factory for creating AWS S3 and GCP storage providers."""

    def __init__(self):
        self._providers = {
            "s3": S3StoreProvider(),
            "gs": GCSStoreProvider(),
        }

    def create_store(self, bucket_url: str, **kwargs) -> obs.store:
        """Create appropriate store based on URL scheme."""
        parsed = urlparse(bucket_url)
        scheme = parsed.scheme

        if scheme not in self._providers:
            raise ValueError(
                f"Unsupported URL scheme: {scheme}. Supported schemes: {list(self._providers.keys())}"
            )

        provider = self._providers[scheme]
        return provider.create_store(bucket_url, **kwargs)

    def get_supported_schemes(self) -> list[str]:
        """Get all supported URL schemes."""
        return list(self._providers.keys())


# Global factory instance
store_factory = StoreFactory()
