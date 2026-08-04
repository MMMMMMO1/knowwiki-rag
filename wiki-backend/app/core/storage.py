"""
S3 Storage adapter.
Provides async operations to object storage using aioboto3.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, List
import io

import aioboto3
from botocore.exceptions import ClientError
from aiobotocore.session import AioSession

from app.core.config import settings

# Global session
_session = None

def get_session() -> AioSession:
    global _session
    if _session is None:
        _session = aioboto3.Session()
    return _session


@asynccontextmanager
async def get_s3_client():
    """Context manager for S3 client."""
    session = get_session()
    async with session.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
    ) as client:
        yield client


async def ensure_bucket_exists() -> None:
    """Ensure that the required S3 bucket exists, creates it if it doesn't."""
    async with get_s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "404" or error_code == "NoSuchBucket":
                try:
                    await s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)
                    print(f"Created bucket {settings.S3_BUCKET_NAME}")
                except Exception as ex:
                    print(f"Failed to create bucket: {ex}")
            else:
                print(f"Error checking bucket: {e}")


async def get_file_content(key: str) -> bytes | None:
    """Read a file from S3 given its object key."""
    async with get_s3_client() as s3:
        try:
            response = await s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            async with response['Body'] as stream:
                content = await stream.read()
            return content
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "NoSuchKey":
                return None
            print(f"Error reading file {key} from S3: {e}")
            return None


async def save_file_content(key: str, content: bytes | str) -> bool:
    """Write a file to S3."""
    if isinstance(content, str):
        content = content.encode("utf-8")
        
    async with get_s3_client() as s3:
        try:
            await s3.put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=key,
                Body=content,
            )
            return True
        except Exception as e:
            print(f"Error uploading file {key} to S3: {e}")
            return False


async def delete_file(key: str) -> bool:
    """Delete a file from S3."""
    async with get_s3_client() as s3:
        try:
            await s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            return True
        except Exception as e:
            print(f"Error deleting file {key} from S3: {e}")
            return False


async def list_files(prefix: str = "") -> List[dict]:
    """
    List files in S3. 
    Returns list of dicts with 'Key', 'Size', 'LastModified'.
    """
    files = []
    async with get_s3_client() as s3:
        try:
            paginator = s3.get_paginator('list_objects_v2')
            async for result in paginator.paginate(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix):
                for item in result.get('Contents', []):
                    # We might have directory markers (keys ending with '/')
                    if not item['Key'].endswith('/'):
                        files.append(item)
            return files
        except Exception as e:
            print(f"Error listing files in S3: {e}")
            return []


async def delete_directory(prefix: str) -> bool:
    """Delete all objects matching a prefix (simulates directory deletion)."""
    # Ensure prefix ends with / so we don't accidentally delete docs-abc when asking for docs
    if not prefix.endswith("/"):
        prefix += "/"
        
    async with get_s3_client() as s3:
        try:
            paginator = s3.get_paginator('list_objects_v2')
            async for result in paginator.paginate(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix):
                objects = [{"Key": obj["Key"]} for obj in result.get("Contents", [])]
                if objects:
                    await s3.delete_objects(
                        Bucket=settings.S3_BUCKET_NAME,
                        Delete={"Objects": objects, "Quiet": True}
                    )
            return True
        except Exception as e:
            print(f"Error deleting directory {prefix} from S3: {e}")
            return False
