import asyncio

from folders import create_hotel_dir
from copie_site import copie_site
from scrap_site import scrape_site
from extract_contacts import extract_contacts
from r2_deploy import deploy_batch
from r2_deploy import create_demo_url
from build_rag import generate_rag_file
from pathlib import Path

# ============================================================
# UN HÔTEL
# ============================================================

async def process_hotel(hotel):

    nom = hotel["nom"]
    url = hotel["url"]
    code_postal = hotel["code_postal"]
    capacite_accueil = hotel["capacite_accueil"]


    print()
    print("========================================")
    print(f"HÔTEL : {nom}")
    print(f"URL   : {url}")
    print(f"CP    : {code_postal}")
    print(f"Capacité accueil : {capacite_accueil}")
    print("========================================")

    # --------------------------------------------------------
    # 1. DOSSIER
    # --------------------------------------------------------

    hotel_dir = create_hotel_dir(nom, code_postal, capacite_accueil)
    print(f"Dossier : {hotel_dir}")

    site_id = hotel_dir.name

    # --------------------------------------------------------
    # 2. SCREENSHOT ACCUEIL
    # --------------------------------------------------------

    print()
    print("1/3 - Capture de l'accueil")

    fichier_html = await copie_site(url, hotel_dir)


    # # --------------------------------------------------------
    # # 3. CONNAISSANCES
    # # --------------------------------------------------------

    # print()
    # print("2/3 - Création de connaissance.md")


    # scraping = await scrape_site(url, hotel_dir)

    # --------------------------------------------------------
    # 3. CONNAISSANCES & VECTORISATION
    # --------------------------------------------------------
    print()
    print("2/4 - Création des connaissances & vectorisation RAG")

    scraping = await scrape_site(url, hotel_dir)
    markdown_file = Path(scraping["knowledge_file"])

    # On transforme le .md en connaissance.json
    json_rag_file = hotel_dir / "connaissance.json"
    generate_rag_file(
        markdown_path=markdown_file, output_json_path=json_rag_file
    )

    # Optionnel : si tu ne veux même pas déployer le .md sur R2, tu peux le supprimer :
    # markdown_file.unlink()


    # --------------------------------------------------------
    # 4. CONTACTS
    # --------------------------------------------------------

    print()
    print("3/3 - Extraction des contacts")


    contacts = extract_contacts(hotel_dir, url)

    # --------------------------------------------------------
    # 4. CREATION URL DE LA DEMO
    # --------------------------------------------------------

    demo_url = create_demo_url(hotel_dir.parent.name, hotel_dir.name)

    # --------------------------------------------------------
    # 5. DEPLOYMENT
    # --------------------------------------------------------

    deploy_batch(hotel_dir.parent)


    # --------------------------------------------------------
    # TERMINÉ
    # --------------------------------------------------------

    print()
    print("========================================")
    print(f"✓ TERMINÉ : {nom}")
    print("========================================")


    print(
        f"Démo : {fichier_html}"
    )


    print(
        "Connaissance : "
        f"{scraping['knowledge_file']}"
    )


    print(
        f"Emails : {contacts['emails']}"
    )


    print(
        f"Téléphones : {contacts['phones']}"
    )


    print()


    return { "nom": nom, "url": url, "hotel_dir": hotel_dir, "html": fichier_html, "knowledge_file": scraping["knowledge_file"], "contacts": contacts , "demo_url": demo_url, "site_id": site_id }

def normalize_url(url):

    url = str(url).strip()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return url

# ============================================================
# WORKFLOW
# ============================================================

async def start(hotels):


    list_contacts = []

    for hotel in hotels:

        hotel["url"] = normalize_url(hotel["url"])

        try:


            resultat = await process_hotel(hotel)

            list_contacts.append(
                {
                    "url": resultat["url"],
                    "emails": resultat["contacts"]["emails"],
                    "phones": resultat["contacts"]["phones"],
                    "site_id": resultat["site_id"], 
                    "demo_url": resultat["demo_url"]
                }
            )
        except Exception as error:


            print()
            print(
                "========================================"
            )
            print(
                f"✗ ERREUR : {hotel['nom']}"
            )
            print(
                "========================================"
            )

            print(
                error
            )

            print()


            # Passe à l'hôtel suivant
            continue

    return list_contacts