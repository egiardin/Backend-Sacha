import json
import re
from pathlib import Path


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


def split_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 200
) -> list[str]:

    text = clean_text(text)

    paragraphs = re.split(
        r"\n\s*\n",
        text
    )

    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        if len(current_chunk) + len(paragraph) <= chunk_size:
            if current_chunk:
                current_chunk += "\n\n"

            current_chunk += paragraph

        else:
            if current_chunk:
                chunks.append(current_chunk)

            if len(paragraph) <= chunk_size:
                current_chunk = paragraph

            else:
                start = 0

                while start < len(paragraph):
                    end = start + chunk_size

                    chunk = paragraph[start:end]

                    chunks.append(chunk.strip())

                    start += chunk_size - overlap

                current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def create_chunks(
    markdown_path: Path,
    chunks_path: Path
) -> Path:

    if not markdown_path.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {markdown_path}"
        )

    text = markdown_path.read_text(
        encoding="utf-8"
    )

    chunks_text = split_text(text)

    chunks = []

    for index, chunk in enumerate(chunks_text):

        chunks.append(
            {
                "id": index,
                "text": chunk,
                "position": index
            }
        )

    chunks_path.write_text(
        json.dumps(
            chunks,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"{len(chunks)} chunks créés dans {chunks_path}"
    )

    return chunks_path


if __name__ == "__main__":

    hotel_dir = Path(
        "demo/nom-de-ton-hotel"
    )

    create_chunks(
        hotel_dir / "connaissance.md",
        hotel_dir / "chunks.json"
    )