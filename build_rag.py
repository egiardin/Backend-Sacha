import json
import os
from pathlib import Path
import time
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def chunk_text(
    text: str, chunk_size: int = 1200, overlap: int = 200
) -> list[str]:
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def generate_rag_file(markdown_path: Path, output_json_path: Path) -> Path:
    if not markdown_path.exists():
        raise FileNotFoundError(f"{markdown_path} introuvable.")

    with open(markdown_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    chunks = chunk_text(raw_text)
    print(f"   ↳ {len(chunks)} blocs à vectoriser...")

    rag_data = []
    batch_size = 15  # Réduit de 50 à 15 pour rester sous les limites TPM

    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]

        # Retry loop avec backoff en cas de quota 429
        success = False
        delay = 2
        while not success:
            try:
                response = client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=batch_chunks,
                )
                for chunk, emb in zip(batch_chunks, response.embeddings):
                    rag_data.append({"text": chunk, "vector": emb.values})
                success = True
                # Petite temporisation de précaution entre chaque paquet
                time.sleep(0.8)

            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(
                        f"   ⏳ Limite API atteinte (429). Pause de {delay}s avant nouvel essai..."
                    )
                    time.sleep(delay)
                    delay *= 2  # Double le temps d'attente si ça bloque encore
                else:
                    raise e

        print(
            f"   ↳ Progression vectorisation : {min(i + batch_size, len(chunks))}/{len(chunks)}"
        )

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(rag_data, f, ensure_ascii=False)

    print(f"   ↳ ✓ {output_json_path.name} généré ({len(rag_data)} vecteurs)")
    return output_json_path