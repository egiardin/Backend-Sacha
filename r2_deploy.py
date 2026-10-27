import os
from pathlib import Path
import boto3
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv()

R2_ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET_NAME = os.environ["R2_BUCKET_NAME"]
R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)


def validate_batch(batch_dir: str) -> list[Path]:
    batch_path = Path(batch_dir)

    if not batch_path.exists():
        raise FileNotFoundError(f"Le dossier {batch_dir} n'existe pas.")

    hotel_dirs = sorted(
        path for path in batch_path.iterdir()
        if path.is_dir()
    )

    for hotel_dir in hotel_dirs:
        home_file = hotel_dir / "homepage.png"
        knowledge_file = hotel_dir / "connaissance.json"  # <-- Remplacement de .md par .json

        if not home_file.exists():
            raise ValueError(f"{hotel_dir.name} ne contient pas homepage.png.")

        if not knowledge_file.exists():
            raise ValueError(f"{hotel_dir.name} ne contient pas connaissance.json.")

    return hotel_dirs


def upload_file(local_path: Path, r2_key: str):
    content_type = {
        ".png": "image/png",
        ".json": "application/json; charset=utf-8",      # <-- Définition MIME pour le JSON
        ".md": "text/markdown; charset=utf-8",
    }.get(local_path.suffix, "application/octet-stream")

    s3.upload_file(
        str(local_path),
        R2_BUCKET_NAME,
        r2_key,
        ExtraArgs={
            "ContentType": content_type,
            "CacheControl": "public, max-age=31536000, immutable",
        },
    )


def deploy_batch(batch_dir: str):
    batch_path = Path(batch_dir)
    batch_name = batch_path.name

    hotel_dirs = validate_batch(batch_dir)

    for hotel_dir in hotel_dirs:
        hotel_id = hotel_dir.name

        # 1. Envoi de la capture
        upload_file(
            hotel_dir / "homepage.png",
            f"demos/{batch_name}/{hotel_id}/homepage.png",
        )

        # 2. Envoi du fichier RAG vectorisé unique
        upload_file(
            hotel_dir / "connaissance.json",
            f"demos/{batch_name}/{hotel_id}/connaissance.json",
        )

        print(f"✓ {hotel_id} envoyé (homepage.png + connaissance.json).")

    # Marqueur de fin de déploiement
    s3.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=f"demos/{batch_name}/_READY",
        Body=b"",
        ContentType="text/plain",
    )

    print(f"Batch {batch_name} publié avec succès.")


def create_demo_url(batch_name: str, hotel_id: str) -> str:
    return f"https://demo.sacha-ai.com/{batch_name}/{hotel_id}"
