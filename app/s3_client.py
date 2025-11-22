import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from .config import settings

# Initialize S3 client
s3 = boto3.client(
    "s3",
    endpoint_url=settings.S3_ENDPOINT,
    aws_access_key_id=settings.S3_ACCESS_KEY,
    aws_secret_access_key=settings.S3_SECRET_KEY,
    config=Config(signature_version="s3v4"),
)


def ensure_bucket_exists(bucket_name: str) -> None:
    """Ensure that the S3 bucket exists; create it if it does not."""
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            try:
                s3.create_bucket(Bucket=bucket_name)
            except ClientError as create_error:
                # Handle race condition where another process created the bucket
                if create_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                    raise


def upload_fileobj(fileobj, bucket: str, key: str) -> None:
    """Upload a file object to a specific S3 bucket and key."""
    ensure_bucket_exists(bucket)
    s3.upload_fileobj(fileobj, bucket, key)


def get_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for accessing a file in S3."""
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )
