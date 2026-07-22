"""
Cloudflare R2 storage for evidence images/videos (S3-compatible API).

Decided architecture: media goes to R2, the database only stores the
object key (`evidence_key`). Uploads are asynchronous — the pipeline
spools JPEGs to disk first (evidence_spool/) and an upload worker pushes
them to R2 with retry, so a network outage never loses evidence.

Required environment variables (put them in .env, never commit):
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
"""
import os


class R2Storage:
    def __init__(self):
        try:
            import boto3
        except ImportError:
            raise RuntimeError("boto3 is not installed. Please run 'pip install boto3' to use Cloudflare R2 storage.")
            
        account_id = os.environ.get("R2_ACCOUNT_ID", "")
        self.bucket = os.environ.get("R2_BUCKET", "industrial-safety-evidence")
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
            region_name="auto",
        )

    def upload(self, local_path, key):
        """Upload one evidence file; caller deletes the spool file on success."""
        self.client.upload_file(local_path, self.bucket, key)

    def presigned_url(self, key, expires_seconds=3600):
        """Short-lived URL the dashboard uses to display evidence images."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
