import re
import hashlib
from pathlib import Path
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
    urldefrag
)

from crawl4ai import AsyncWebCrawler


# ============================================================
# CONFIGURATION
# ============================================================

MAX_PAGES = 40
MIN_CONTENT_LENGTH = 180

# Préfixes de langues étrangères à bloquer impérativement
BLOCKED_LANGUAGES = (
    "/en", "/en-us", "/en-gb",
    "/de", "/de-de",
    "/nl", "/nl-nl",
    "/es", "/es-es",
    "/it", "/it-it",
    "/pt", "/pt-pt",
    "/pl",
    "/ru",
    "/zh",
    "/ja",
    "/ko",
    "/ar",
    "/da", "/da-dk",  # Ajout du danois
    "/sv",
    "/no",
)

IGNORED_KEYWORDS = (
    "mentions-legales",
    "mentions_legales",
    "legal-notice",
    "privacy",
    "confidentialite",
    "politique-de-confidentialite",
    "cookie",
    "cookies",
    "rgpd",
    "terms",
    "conditions-generales",
    "cgv",
    "plan-du-site",
    "sitemap",
    "wp-json",
    "feed",
    "login",
    "connexion",
    "onetrust",
)

IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".avif",
    ".zip", ".mp4", ".mp3", ".css", ".js", ".xml", ".pdf"
)

IMPORTANT_KEYWORDS = (
    "chambre", "room",
    "restaurant", "bar",
    "petit-dejeuner", "breakfast",
    "spa", "wellness", "sauna", "piscine", "pool",
    "service", "contact",
    "parking", "acces", "access",
    "tarifs", "offre", "offer"
)


# ============================================================
# GESTION DES URL & SCOPE
# ============================================================

def canonical_url(url):
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if path != "/":
        path = path.rstrip("/")

    return urlunparse(("https", host, path, "", parsed.query, ""))


def normalized_domain(url):
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def same_domain(url, base_url):
    return normalized_domain(url) == normalized_domain(base_url)


def get_hotel_scope_prefix(url):
    """
    Si l'URL cible un hôtel particulier d'une chaîne (ex: /fr/paris/terminus-nord),
    on limite le crawl à ce dossier pour ne pas scraper les autres hôtels du groupe.
    """
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Ex: ["fr", "paris", "terminus-nord"] ou ["cologne", "the-circle"]
    if len(parts) >= 2:
        if parts[0] in ("fr", "en", "de") and len(parts) >= 3:
            return "/" + "/".join(parts[:3])
        return "/" + "/".join(parts[:2])
    return ""


def is_foreign_language(url):
    path = urlparse(url).path.lower()
    for prefix in BLOCKED_LANGUAGES:
        if (
            path == prefix
            or path.startswith(prefix + "/")
            or path.startswith(prefix + "-")
            or path.startswith(prefix + "_")
        ):
            return True
    return False


def should_ignore_url(url, base_scope_prefix=""):
    lower = url.lower()
    path = urlparse(lower).path

    if is_foreign_language(url):
        return True

    # Si un préfixe d'hôtel spécifique est défini, ne pas sortir de cet hôtel
    if base_scope_prefix and not path.startswith(base_scope_prefix):
        return True

    if any(keyword in lower for keyword in IGNORED_KEYWORDS):
        return True

    if path.endswith(IGNORED_EXTENSIONS):
        return True

    return False


# ============================================================
# NETTOYAGE DU TEXTE & DES COOKIES
# ============================================================

def clean_markdown(text):
    if not text:
        return ""

    text = str(text)

    # 1. Supprimer le gros bloc de bannière cookies OneTrust
    text = re.sub(
        r"##\s*We use cookies![\s\S]*?(?:Confirm my choices|Reject All|\[!\[.*?\]\(.*?\)\]\(https://www\.onetrust\.com.*?\))",
        "",
        text,
        flags=re.I
    )
    text = re.sub(r"##\s*We use cookies![\s\S]*$", "", text, flags=re.I)

    # 2. Nettoyer les listes vides de checkboxes
    text = re.sub(r"-\s*checkbox label label", "", text)

    # 3. Supprimer les images Markdown ![]()
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

    # 4. Remplacer les liens Markdown par leur texte brut : [Texte](url) -> Texte
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # 5. Supprimer les balises vides ou liens résiduels - []()
    text = re.sub(r"-\s*\[\s*\]\([^)]*\)", "", text)

    # 6. HTML résiduel
    text = re.sub(r"<script.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.I | re.S)

    # 7. Espaces et retours à la ligne
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Déduplication des lignes identiques consécutives
    lines = []
    previous = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == previous:
            continue
        previous = line
        lines.append(line)

    return "\n".join(lines).strip()


def normalize_content(text):
    text = text.lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-zà-ÿ0-9]+", " ", text)
    return " ".join(text.split())


def content_signature(text):
    normalized = normalize_content(text)
    sample = normalized[:5000]
    return hashlib.sha256(sample.encode("utf-8")).hexdigest()


def deduplicate_pages(pages):
    seen = set()
    result = []
    removed = 0
    for page in pages:
        signature = content_signature(page["content"])
        if signature in seen:
            removed += 1
            continue
        seen.add(signature)
        result.append(page)
    return result, removed


def page_score(page):
    path = urlparse(page["url"].lower()).path
    score = 0
    if path in ("", "/", "/fr"):
        score += 100
    for kw in IMPORTANT_KEYWORDS:
        if kw in path:
            score += 15
    return score


# ============================================================
# CRAWL
# ============================================================

async def crawl_site(start_url):
    start_url = canonical_url(start_url)
    scope_prefix = get_hotel_scope_prefix(start_url)

    queue = [start_url]
    visited = set()
    pages = []
    ignored = 0

    print(f"\n[CRAWL] Début sur : {start_url}")
    if scope_prefix:
        print(f"[CRAWL] Périmètre restreint à l'hôtel : {scope_prefix}")

    async with AsyncWebCrawler() as crawler:
        while queue and len(visited) < MAX_PAGES:
            url = canonical_url(queue.pop(0))

            if url in visited:
                continue

            if not same_domain(url, start_url):
                continue

            if should_ignore_url(url, scope_prefix):
                ignored += 1
                continue

            visited.add(url)
            print(f"[{len(visited)}/{MAX_PAGES}] {url}")

            try:
                result = await crawler.arun(url=url)
            except Exception as exc:
                print(f"  ✗ erreur requête : {exc}")
                continue

            if not result.success:
                print("  ✗ échec de chargement")
                continue

            content = clean_markdown(result.markdown)

            if len(content) >= MIN_CONTENT_LENGTH:
                pages.append({"url": url, "content": content})
                print(f"  ✓ {len(content):,} caractères utiles")
            else:
                print("  → contenu trop court ou ignoré")

            # Récupération des liens internes
            internal_links = (result.links or {}).get("internal", [])
            for link in internal_links:
                href = link.get("href")
                if not href:
                    continue

                absolute = canonical_url(urljoin(url, href))

                if not same_domain(absolute, start_url):
                    continue

                if should_ignore_url(absolute, scope_prefix):
                    ignored += 1
                    continue

                if absolute not in visited and absolute not in queue:
                    queue.append(absolute)

    return pages, ignored


# ============================================================
# CONSTRUCTION DU FICHIER CONNAISSANCE
# ============================================================

def build_knowledge(site_url, pages):
    pages = sorted(pages, key=page_score, reverse=True)
    output = [
        "# BASE DE CONNAISSANCES — SACHA",
        "",
        f"Site source : {site_url}",
        "Langue : français",
        "",
        "> Contenu factuel extrait du site officiel de l'établissement.",
        "",
        "---",
        ""
    ]

    for page in pages:
        path = urlparse(page["url"]).path
        page_name = path.strip("/").replace("-", " ").replace("_", " ").upper() or "ACCUEIL"

        output.append(f"# {page_name}")
        output.append("")
        output.append(f"Source : {page['url']}")
        output.append("")
        output.append(page["content"])
        output.append("")
        output.append("---")
        output.append("")

    return "\n".join(output).strip() + "\n"


def save_results(site_url, hotel_dir, pages):
    knowledge = build_knowledge(site_url, pages)
    
    # Prise en charge si hotel_dir est un str ou un Path
    dir_path = Path(hotel_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    knowledge_file = dir_path / "connaissance.md"
    knowledge_file.write_text(knowledge, encoding="utf-8")
    return knowledge_file


# ============================================================
# POINT D'ENTRÉE DU MODULE
# ============================================================

async def scrape_site(url, hotel_dir):
    print("\n==============================")
    print(" SCRAPING DU SITE")
    print("==============================")
    print(f"Cible : {url}")

    pages, ignored = await crawl_site(url)
    pages, duplicates = deduplicate_pages(pages)

    if not pages:
        raise RuntimeError(f"Aucun contenu exploitable trouvé pour {url}.")

    knowledge_file = save_results(url, hotel_dir, pages)

    print("\nScraping achevé avec succès.")
    print(f"→ Fichier généré : {knowledge_file} ({len(pages)} pages conservées)")

    return {
        "knowledge_file": str(knowledge_file),
        "pages": len(pages)
    }