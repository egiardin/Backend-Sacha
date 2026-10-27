"""
Module : Gestionnaire de Stockage et Déploiement Statique (Multi-Tenant)
========================================================================

Ce script organise et prépare automatiquement l'arborescence des dossiers 
nécessaires au déploiement de démos interactives sur Cloudflare Pages.

Architecture de Stockage :
--------------------------
Les démos sont regroupées par lots ("batchs") incrémentaux sous `public/` :

    <PROJECT_DIR>/
    ├── public/
    │   ├── index.html                           # Routeur dynamique universel
    │   └── demos/
    │       ├── batch_1/                         # Lot précédent (ex: 30 hôtels)
    │       └── batch_2/                         # Lot courant auto-incrémenté
    │           └── <nom>-<cp>-<capacite>/       # Espace isolé par hôtel
    │               ├── home.png                 # Capture d'écran du site cible
    │               └── data.json                # Données de connaissances scrapées

Flux d'Exécution et Logique Métier :
------------------------------------
1. Initialisation des Répertoires :
   - Crée `public/demos/` à la racine si inexistant.
   
2. Détection Dynamique du Batch (`get_next_batch_number`) :
   - Scanne `public/demos/` pour lister les dossiers correspondant au motif `batch_<N>`.
   - Extrait le numéro le plus élevé et incrémente de +1.
   - Si aucun batch n'existe, démarre automatiquement à 1.
   - Instancie le dossier cible `BATCH_DIR` (ex: `public/demos/batch_2/`).

3. Normalisation URL-Safe (`slugify`) :
   - Nettoie les entrées (accents convertis en ASCII via normalisation NFKD).
   - Convertit en minuscules et remplace tous les caractères non alphanumériques par `-`.
   - Évite les erreurs de chemin sur les systèmes d'exploitation (espaces, slashes, etc.).

4. Résolution de l'Hôtel (`create_hotel_dir`) :
   - Construit le slug unique à partir du triplet : [nom, code_postal, capacite_accueil].
   - Crée le sous-dossier final de manière idempotente (`parents=True, exist_ok=True`).
   - Associe automatiquement l'hôtel au batch actif en cours d'exécution.

Routage Web Frontend (Cloudflare Pages) :
-----------------------------------------
Le fichier `index.html` unique intercepte l'URL et charge les assets correspondants :
    URL : https://<domaine>.pages.dev/?batch=batch_<N>&hotel=<hotel_slug>
    - Image de fond : demos/batch_<N>/<hotel_slug>/home.png
    - Données JSON  : demos/batch_<N>/<hotel_slug>/data.json
"""

from pathlib import Path
from urllib.parse import urlparse
import re
import unicodedata

# 1. Chemins de base
PROJECT_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = PROJECT_DIR / "public"
DEMOS_DIR = PUBLIC_DIR / "demos"
DEMOS_DIR.mkdir(parents=True, exist_ok=True)


def get_next_batch_number():
    """Détecte les dossiers batch_X existants et renvoie X + 1 (ou 1 si vide)."""
    existing_batches = []
    for path in DEMOS_DIR.glob("batch_*"):
        if path.is_dir():
            match = re.search(r"^batch_(\d+)$", path.name)
            if match:
                existing_batches.append(int(match.group(1)))
    return max(existing_batches, default=0) + 1


# 2. Définition et création du batch courant
batch_number = get_next_batch_number()
batch_name = f"batch_{batch_number}"

# BATCH_DIR = DEMOS_DIR / batch_name
# BATCH_DIR.mkdir(parents=True, exist_ok=True)


def slugify(value):
    """Transforme une chaîne en version compatible URL et nom de dossier."""
    value = str(value).strip().lower()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def create_hotel_dir(name, code_postal, capacite_accueil, batch_name=batch_name):
    """
    Crée et retourne le chemin :
        public/demos/{batch_name}/{nom-hotel}-{cp}-{capacite}/
    """
    hotel_slug = "-".join([slugify(str(name)), slugify(str(code_postal)), slugify(str(capacite_accueil))])
    hotel_dir = DEMOS_DIR / batch_name / hotel_slug
    hotel_dir.mkdir(parents=True, exist_ok=True)
    return hotel_dir

from pathlib import Path
from urllib.parse import urlparse
import re
import unicodedata

# 1. Chemins de base
PROJECT_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = PROJECT_DIR / "public"
DEMOS_DIR = PUBLIC_DIR / "demos"
DEMOS_DIR.mkdir(parents=True, exist_ok=True)

# 2. Détection automatique du prochain batch
def get_next_batch_number():
    """Détecte les dossiers batch_X existants et renvoie X + 1 (ou 1 si vide)."""
    existing_batches = []
    for path in DEMOS_DIR.glob("batch_*"):
        if path.is_dir():
            match = re.search(r"^batch_(\d+)$", path.name)
            if match:
                existing_batches.append(int(match.group(1)))
    return max(existing_batches, default=0) + 1

# 3. Création du dossier du batch actuel
batch_number = get_next_batch_number()
batch_name = f"batch_{batch_number}"

BATCH_DIR = DEMOS_DIR / batch_name
BATCH_DIR.mkdir(parents=True, exist_ok=True)

# 4. Utilitaires de slugification et création des hôtels
def slugify(value):
    value = str(value).strip().lower()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value

def create_hotel_dir(name, code_postal, capacite_accueil, batch_name=batch_name):
    """
    Crée :
        public/demos/{batch_name}/{nom-hotel}/
    Retourne le chemin du dossier hôtel.
    """
    hotel_slug = "-".join([slugify(str(name)), slugify(str(code_postal)), slugify(str(capacite_accueil))])
    hotel_dir = DEMOS_DIR / batch_name / hotel_slug
    hotel_dir.mkdir(parents=True, exist_ok=True)
    return hotel_dir