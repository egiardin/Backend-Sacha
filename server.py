import asyncio
import json
import os
import time
import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from google import genai
from google.genai import types
from pydantic import BaseModel

from workflow import start as workflow_start


# ==================================================
# INITIALISATION
# ==================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CHATBOT_HTML = BASE_DIR / "chatbot.html"
CHATBOT_JS = BASE_DIR / "chatbot.js"

R2_PUBLIC_BASE_URL = (
    "https://pub-5cb1307152fc40ca8ffdf3b67c981c00.r2.dev"
)

GOOGLE_SHEETS_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbxW-LYRzZncE3qmnKhYDk9e6D_cIXqJZGdY46mbVh2noXNcacCiRSAhzu3YIw3fPwE0iA/exec"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY introuvable.")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "gemini-3.5-flash-lite"
EMBEDDING_MODEL = "gemini-embedding-001"


# ==================================================
# FASTAPI
# ==================================================

app = FastAPI(title="Sacha API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


SESSION_COUNTERS = defaultdict(int)
SESSION_HISTORIES = defaultdict(list)
MAX_MESSAGES_PER_DEMO = 20


class ChatRequest(BaseModel):
    site_id: str
    batch: str = "batch_7"
    session_id: str = "default_session"
    message: str


# ==================================================
# OUTILS DE MESURE
# ==================================================

def now():
    return time.perf_counter()


def duration(start):
    return time.perf_counter() - start


def log_metric(request_id, name, start):
    print(
        f"[METRIC][{request_id}] "
        f"{name}: {duration(start):.3f}s"
    )


# ==================================================
# WORKFLOW
# ==================================================

def send_contacts_to_google_sheets(contacts):
    start = now()

    response = requests.post(
        GOOGLE_SHEETS_URL,
        json={"contacts": contacts},
        timeout=120,
    )

    print(
        f"[WORKFLOW] Google Sheets : "
        f"{response.status_code} en {duration(start):.3f}s"
    )

    response.raise_for_status()
    return response.text


async def run_workflow(items):
    try:
        start = now()

        contacts = await workflow_start(items)

        print(
            f"[WORKFLOW] Extraction terminée en "
            f"{duration(start):.3f}s"
        )

        send_contacts_to_google_sheets(contacts)

    except Exception as error:
        print(f"[WORKFLOW] Erreur : {repr(error)}")


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    items = data.get("items", [])

    asyncio.create_task(run_workflow(items))

    return {
        "status": "accepted",
        "message": f"{len(items)} établissements placés dans le workflow",
    }


# ==================================================
# CHARGEMENT DU RAG
# ==================================================

@lru_cache(maxsize=150)
def load_hotel_rag(batch: str, site_id: str):
    start = now()

    url = (
        f"{R2_PUBLIC_BASE_URL}/demos/"
        f"{batch}/{site_id}/connaissance.json"
    )

    print(f"[RAG] Chargement : {url}")

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"connaissance.json introuvable : {url}",
            )

        response.raise_for_status()

        rag_data = response.json()

        print(
            f"[RAG] Fichier chargé en "
            f"{duration(start):.3f}s | "
            f"{len(rag_data)} chunks"
        )

        return rag_data

    except requests.RequestException as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur R2 : {str(error)}",
        )


# ==================================================
# RECHERCHE VECTORIELLE
# ==================================================

def search_relevant_chunks(
    query: str,
    rag_data: list[dict],
    request_id: str,
    top_k: int = 5,
):
    total_start = now()

    embedding_start = now()

    embedding_response = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
    )

    query_vector = np.array(
        embedding_response.embeddings[0].values,
        dtype=np.float32,
    )

    print(
        f"[METRIC][{request_id}] "
        f"Embedding: {duration(embedding_start):.3f}s"
    )

    search_start = now()

    query_norm = np.linalg.norm(query_vector)
    scores = []

    for item in rag_data:
        document_vector = np.array(
            item["vector"],
            dtype=np.float32,
        )

        document_norm = np.linalg.norm(document_vector)

        if query_norm > 0 and document_norm > 0:
            similarity = np.dot(
                query_vector,
                document_vector,
            ) / (query_norm * document_norm)
        else:
            similarity = 0.0

        scores.append((similarity, item["text"]))

    scores.sort(key=lambda item: item[0], reverse=True)

    selected_chunks = scores[:top_k]
    context = "\n\n---\n\n".join(
        text for _, text in selected_chunks
    )

    print(
        f"[METRIC][{request_id}] "
        f"Recherche vectorielle: {duration(search_start):.3f}s"
    )

    print(
        f"[METRIC][{request_id}] "
        f"RAG total: {duration(total_start):.3f}s"
    )

    if selected_chunks:
        print(
            f"[RAG][{request_id}] "
            f"Meilleur score: {selected_chunks[0][0]:.4f}"
        )

    return context


# ==================================================
# GEMINI AVEC RETRIES
# ==================================================

def create_gemini_stream(
    contents,
    system_instruction,
    request_id,
):
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        attempt_start = now()

        try:
            print(
                f"[GEMINI][{request_id}] "
                f"Tentative {attempt}/{max_attempts}"
            )

            stream = gemini_client.models.generate_content_stream(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=400,
                ),
            )

            print(
                f"[GEMINI][{request_id}] "
                f"Flux créé en {duration(attempt_start):.3f}s"
            )

            return stream

        except Exception as error:
            error_text = str(error)

            print(
                f"[GEMINI][{request_id}] "
                f"Erreur tentative {attempt}: {repr(error)}"
            )

            is_temporary_error = (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
            )

            if not is_temporary_error:
                raise

            if attempt == max_attempts:
                raise

            wait_seconds = 2 ** attempt

            print(
                f"[GEMINI][{request_id}] "
                f"Nouvelle tentative dans {wait_seconds}s"
            )

            time.sleep(wait_seconds)


# ==================================================
# FICHIERS STATIQUES
# ==================================================

@app.get("/")
def home():
    return {
        "status": "Sacha API opérationnelle"
    }


@app.get("/chatbot.html")
def chatbot_html():
    return FileResponse(
        CHATBOT_HTML,
        media_type="text/html",
    )


@app.get("/chatbot.js")
def chatbot_js():
    return FileResponse(
        CHATBOT_JS,
        media_type="application/javascript",
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok"
    }


@app.options("/api/chat")
def options_chat():
    return {}


# ==================================================
# CHAT
# ==================================================

@app.post("/api/chat")
def chat(request: ChatRequest):
    request_id = uuid.uuid4().hex[:8]
    request_start = now()

    print("")
    print("=" * 80)
    print(f"[REQUEST][{request_id}] Nouvelle requête")
    print(f"[REQUEST][{request_id}] site_id : {request.site_id}")
    print(f"[REQUEST][{request_id}] batch   : {request.batch}")
    print(f"[REQUEST][{request_id}] session : {request.session_id}")
    print(f"[REQUEST][{request_id}] message : {request.message}")
    print("=" * 80)

    current_count = SESSION_COUNTERS[request.session_id]

    if current_count >= MAX_MESSAGES_PER_DEMO:

        def quota_stream():
            data = {
                "text": (
                    "Vous avez atteint la limite de 20 questions "
                    "pour cette démo."
                ),
                "quota_exceeded": True,
                "remaining_questions": 0,
                "done": True,
            }

            yield f"data: {json.dumps(data)}\n\n"

        return StreamingResponse(
            quota_stream(),
            media_type="text/event-stream",
        )

    # ------------------------------------------------
    # RAG
    # ------------------------------------------------

    rag_start = now()

    rag_data = load_hotel_rag(
        request.batch,
        request.site_id,
    )

    log_metric(
        request_id,
        "Chargement RAG",
        rag_start,
    )

    relevant_context = search_relevant_chunks(
        query=request.message,
        rag_data=rag_data,
        request_id=request_id,
        top_k=5,
    )

    # ------------------------------------------------
    # Prompt et historique
    # ------------------------------------------------

    prompt_start = now()

    system_instruction = f"""
Tu es Sacha, un assistant chargé de répondre aux questions des clients d’un établissement hôtelier.

Réponds uniquement à partir des informations présentes dans le contexte.

Règles :
- Réponds en français, avec un ton naturel, chaleureux et professionnel.
- Réponds directement à la question du client.
- Sois concis : 2 à 5 phrases maximum, sauf si plusieurs détails sont réellement nécessaires.
- Sélectionne uniquement les informations utiles à la question.
- Ne récite jamais tout le contexte et ne transforme pas automatiquement la réponse en longue liste.
- Si plusieurs éléments sont nécessaires, utilise de courts paragraphes ou quelques puces simples.
- Pour une question sur les activités, privilégie d’abord les lieux proches, puis mentionne brièvement les sorties plus éloignées.
- N’invente aucune information : ni distance, ni durée, ni prix, ni horaires, ni moyen de transport.
- Si une information manque, indique-le clairement et propose une action concrète, par exemple contacter la réception.
- Ne répète pas inutilement la question du client.
- Ne commence pas systématiquement par « Bonjour ».
- N’utilise pas de titre inutile.
- N’utilise pas de texte en gras, sauf si cela est indispensable.
- Ne parle jamais de « contexte », de « chunks », de « documents » ou de ton fonctionnement.

<CONTEXTE>
{relevant_context}
</CONTEXTE>
"""

    history = SESSION_HISTORIES[
        request.session_id
    ][-6:]

    contents = []

    for item in history:
        contents.append(
            types.Content(
                role=item["role"],
                parts=[
                    types.Part.from_text(
                        text=item["text"]
                    )
                ],
            )
        )

    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=request.message
                )
            ],
        )
    )

    log_metric(
        request_id,
        "Préparation prompt",
        prompt_start,
    )

    print(
        f"[METRIC][{request_id}] "
        f"Temps avant Gemini: {duration(request_start):.3f}s"
    )

    # ------------------------------------------------
    # Générateur SSE
    # ------------------------------------------------

    def event_generator():
        SESSION_COUNTERS[request.session_id] += 1

        remaining = (
            MAX_MESSAGES_PER_DEMO
            - SESSION_COUNTERS[request.session_id]
        )

        gemini_start = now()
        first_token_at = None
        full_text = ""

        try:
            response_stream = create_gemini_stream(
                contents=contents,
                system_instruction=system_instruction,
                request_id=request_id,
            )

            for chunk in response_stream:
                if not chunk.text:
                    continue

                if first_token_at is None:
                    first_token_at = now()

                    print(
                        f"[METRIC][{request_id}] "
                        f"TTFT / premier token: "
                        f"{first_token_at - gemini_start:.3f}s"
                    )

                    print(
                        f"[METRIC][{request_id}] "
                        f"Premier token depuis requête: "
                        f"{first_token_at - request_start:.3f}s"
                    )

                full_text += chunk.text

                data = {
                    "text": chunk.text,
                    "quota_exceeded": False,
                    "remaining_questions": remaining,
                    "done": False,
                }

                yield f"data: {json.dumps(data)}\n\n"

            generation_time = duration(gemini_start)
            total_time = duration(request_start)

            print(
                f"[METRIC][{request_id}] "
                f"Génération totale: {generation_time:.3f}s"
            )

            print(
                f"[METRIC][{request_id}] "
                f"Requête totale: {total_time:.3f}s"
            )

            print(
                f"[METRIC][{request_id}] "
                f"Réponse: {len(full_text)} caractères"
            )

            SESSION_HISTORIES[
                request.session_id
            ].append(
                {
                    "role": "user",
                    "text": request.message,
                }
            )

            SESSION_HISTORIES[
                request.session_id
            ].append(
                {
                    "role": "model",
                    "text": full_text,
                }
            )

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as error:
            print(
                f"[ERROR][{request_id}] "
                f"Erreur finale Gemini : {repr(error)}"
            )

            user_message = (
                "Le service est momentanément très sollicité. "
                "Veuillez réessayer dans quelques secondes."
            )

            error_data = {
                "error": user_message,
                "done": True,
            }

            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ==================================================
# DÉMARRAGE
# ==================================================

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )