"""
Module : Capture Intégrale Haute Fidélité de Page d'Accueil (Playwright & Pillow)
==================================================================================

Ce module gère la capture d'écran pleine page (Full-Page Screenshot) de sites 
hôteliers complexes via Google Chrome headless piloté par Playwright, avec 
reconstitution sans perte par découpage et assemblage d'images (Pillow).

Pourquoi un assemblage par viewports plutôt que `full_page=True` ?
-------------------------------------------------------------------
1. Contournement des éléments collants (`position: fixed` / `sticky`) :
   L'option native `full_page=True` de Playwright duplique fréquemment les 
   en-têtes et bannières collantes sur toute la hauteur de l'image.
2. Déclenchement garanti du Lazy-Loading :
   Le défilement progressif force les déclencheurs `IntersectionObserver` et 
   charge l'intégralité des images différées (`data-src`, `data-lazy-src`).
3. Animations au défilement (AOS, GSAP, CSS transitions) :
   Un délai d'attente configurable (`ANIMATION_WAIT_MS`) garantit que chaque 
   section a fini son animation d'entrée avant la prise de vue.
4. Élimination agressive des bannières de cookies :
   Injection JS nettoyant à la fois les CMP standards (OneTrust, Didomi, Axeptio,
   Tarteaucitron, Cookiebot) et les popups génériques par analyse lexicale.

Architecture du Pipeline :
--------------------------

    [URL Cible]
        │
        ├──► 1. Résolution de Route (`ouvrir_page_accueil`)
        │       Essai sur `/accueil`, repli sur `/` en cas d'échec
        │
        ├──► 2. Stabilisation DOM & Médias
        │       - `document.fonts.ready` (anti-FOUT)
        │       - `supprimer_cookies` (suppression visuelle + reset overflow)
        │       - `forcer_images_lazy` (mutation src / srcset)
        │       - `precharger_page` (descente progressive 400px puis remontée)
        │
        ├──► 3. Découpage Vertical (`capturer_morceaux`)
        │       - Scroll échelonné : step = VIEWPORT_HEIGHT - OVERLAP
        │       - Attente réseau, polices et fin d'animations
        │       - Écriture des tranches temporaires : `temp_dir/part-NNN.png`
        │
        ├──► 4. Assemblage Matriciel (`assembler_captures`)
        │       - Détection et rognage automatique des zones de recouvrement (`OVERLAP`)
        │       - Concaténation verticale PIL sur canvas RGB blanc
        │       - Export optimisé : `<hotel_dir>/home.png`
        │
        └──► 5. Nettoyage Système
                Suppression automatique et garantie (`try/finally`) du dossier temp

Configuration Globale :
-----------------------
- `TIMEOUT`            : 60 000 ms (tolérance réseau accrue pour sites lourds).
- `VIEWPORT_WIDTH`     : 1 440 px (résolution desktop standard).
- `VIEWPORT_HEIGHT`    : 1 000 px.
- `OVERLAP`            : 100 px (marge de sécurité entre deux captures contiguës).
- `ANIMATION_WAIT_MS`  : 2 200 ms (latence d'achèvement des transitions CSS/JS).
- `CHEMIN_CHROME`      : Chemin absolu vers le binaire Google Chrome macOS.

Dépendances Requises :
----------------------
- `playwright` (async_api)
- `PIL` (Pillow)
- `pathlib`, `tempfile`, `shutil`, `urllib.parse`
"""

from pathlib import Path
import shutil
import tempfile
from PIL import Image
from playwright.async_api import async_playwright
from urllib.parse import urljoin
from playwright.async_api import Error as PlaywrightError

# ============================================================
# CONFIGURATION
# ============================================================

TIMEOUT = 60_000

VIEWPORT_WIDTH = 1440
VIEWPORT_HEIGHT = 1000

# On garde un léger chevauchement entre deux captures.
OVERLAP = 100

# Temps laissé aux animations après chaque scroll.
ANIMATION_WAIT_MS = 2200

#CHEMIN_CHROME = ("/Applications/Google Chrome.app/" "Contents/MacOS/Google Chrome")

async def ouvrir_page_accueil(page, url):
    url = url.strip()

    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    url_accueil = urljoin(url, "/accueil")

    # Essaie /accueil, puis l'URL initiale.
    # Évite les doublons si l'URL fournie est déjà /accueil.
    adresses = list(dict.fromkeys([url_accueil, url]))

    for numero, adresse in enumerate(adresses):
        print(f"Essai : {adresse}")

        try:
            response = await page.goto(adresse, wait_until="domcontentloaded", timeout=15_000 if numero == 0 else TIMEOUT)

            if response is not None and response.ok:
                print(f"✓ Page retenue : {page.url}")
                return page.url

            statut = response.status if response else "sans réponse"
            print(f"✗ Page indisponible : HTTP {statut}")

        except PlaywrightError as erreur:
            print("✗ Échec du chargement : "f"{str(erreur).splitlines()[0]}")

    raise RuntimeError(
        f"Impossible de charger une page pour : {url}")

# ============================================================
# SUPPRESSION COOKIES
# ============================================================

async def supprimer_cookies(page):
    """
    Supprime visuellement les bannières de cookies.
    """

    await page.evaluate(
        """
        () => {

            const selectors = [

                '#onetrust-banner-sdk',
                '#onetrust-consent-sdk',
                '.onetrust-pc-dark-filter',

                '#CybotCookiebotDialog',
                '#CybotCookiebotDialogBodyUnderlay',

                '#didomi-host',
                '.didomi-popup-container',

                '#usercentrics-root',

                '#tarteaucitronAlertBig',
                '#tarteaucitronAlertSmall',
                '#tarteaucitronRoot',
                '#tarteaucitron',
                '#tarteaucitronBack',

                '.cky-consent-container',
                '.cky-modal',
                '.cky-overlay',

                '.cmplz-cookiebanner',
                '.cmplz-soft-cookiewall',

                '#cookie-law-info-bar',
                '#cookie-law-info-again',

                '.cli-modal',
                '.cli-popupbar-overlay',

                '.cc-window',
                '.cookie-banner',
                '.cookie-popup',
                '.cookie-modal',
                '.cookie-consent',
                '.cookies-banner',
                '.cookies-popup',
                '.consent-banner',
                '.consent-popup'
            ];


            for (const selector of selectors) {

                try {

                    document
                        .querySelectorAll(selector)
                        .forEach(element => element.remove());

                } catch (_) {}
            }


            const normalize = text =>

                (text || '')
                    .toLowerCase()
                    .normalize('NFD')
                    .replace(/[\\u0300-\\u036f]/g, '')
                    .replace(/\\s+/g, ' ')
                    .trim();


            const cookieWords =
                /cookie|cookies|consentement|consent|traceur|tracking/;


            const choiceWords =
                /accepter|refuser|tout accepter|tout refuser|accept all|reject all|accept|reject/;


            const candidates =
                document.querySelectorAll(

                    '[role="dialog"], '
                    + '[aria-modal="true"], '
                    + '[class*="cookie" i], '
                    + '[id*="cookie" i], '
                    + '[class*="consent" i], '
                    + '[id*="consent" i]'

                );


            for (const element of candidates) {

                const text =
                    normalize(element.innerText);


                if (
                    cookieWords.test(text)
                    &&
                    (
                        choiceWords.test(text)
                        ||
                        element.getAttribute('role') === 'dialog'
                    )
                ) {

                    element.remove();
                }
            }


            document.documentElement.style.setProperty(
                'overflow-y',
                'auto',
                'important'
            );

            document.body.style.setProperty(
                'overflow-y',
                'auto',
                'important'
            );
        }
        """
    )


async def supprimer_popup_brunch(page):
    await page.evaluate("""
    () => {
        const mots = [
            'le dimanche',
            'temps ralentit',
            'réservez votre table',
            'découvrez notre menu'
        ];

        document.querySelectorAll('body *').forEach(element => {
            const texte = (element.innerText || '').toLowerCase();

            if (
                mots.some(mot => texte.includes(mot)) &&
                element.getBoundingClientRect().width > 200 &&
                element.getBoundingClientRect().height > 100
            ) {
                element.remove();
            }
        });

        document.documentElement.style.overflow = 'auto';
        document.body.style.overflow = 'auto';
    }
    """)

async def forcer_images_lazy(page):
    """Déclenche le chargement des images sans écraser les images déjà correctes."""
    await page.evaluate("""
        () => {
            document.querySelectorAll('img[data-src], img[data-lazy-src]').forEach(img => {
                const src = img.getAttribute('data-src') || img.getAttribute('data-lazy-src');
                if (src && !img.src.includes(src)) {
                    img.src = src;
                }
            });
        }
    """)

# ============================================================
# ATTENTE POLICES
# ============================================================

async def attendre_polices(page):

    try:

        await page.evaluate(
            """
            async () => {

                if (
                    document.fonts
                    &&
                    document.fonts.ready
                ) {

                    await document.fonts.ready;
                }
            }
            """
        )

    except Exception:

        pass


# ============================================================
# ATTENTE DES IMAGES VISIBLES
# ============================================================

async def attendre_images_visibles(page):
    """
    Attend surtout les images présentes dans le viewport.
    """

    try:

        await page.wait_for_function(
            """
            () => {

                const images =
                    Array.from(document.images);


                const visibles =
                    images.filter(image => {

                        const rect =
                            image.getBoundingClientRect();

                        return (
                            rect.bottom > 0
                            &&
                            rect.top < window.innerHeight
                        );
                    });


                return visibles.every(
                    image =>
                        image.complete
                        &&
                        image.naturalWidth > 0
                );
            }
            """,

            timeout=8000

        )

    except Exception:

        pass


# ============================================================
# HAUTEUR DE PAGE
# ============================================================

async def hauteur_page(page):

    return await page.evaluate(
        """
        Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight
        )
        """
    )


# ============================================================
# PRÉCHARGEMENT
# ============================================================

async def precharger_page(page):
    """
    Premier passage lent sur la page.

    Cela permet de déclencher un maximum :
    - images lazy
    - IntersectionObserver
    - sections chargées dynamiquement
    - animations
    """
    
    print("Préchargement de la page...")
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1500)

    position = 0

    step = 400


    for _ in range(150):

        height = await hauteur_page(
            page
        )


        viewport = await page.evaluate(
            "window.innerHeight"
        )


        if (
            position + viewport
            >= height
        ):

            break


        position += step


        await page.evaluate(
            """
            y => window.scrollTo({
                top: y,
                behavior: 'smooth'
            })
            """,
            position
        )


        await page.wait_for_timeout(
            900
        )


        await forcer_images_lazy(
            page
        )


    await page.evaluate(
        """
        window.scrollTo(
            0,
            document.documentElement.scrollHeight
        )
        """
    )


    await page.wait_for_timeout(
        2500
    )


    await forcer_images_lazy(
        page
    )


    await page.evaluate(
        "window.scrollTo(0, 0)"
    )


    await page.wait_for_timeout(
        2500
    )


    print(
        "✓ Préchargement terminé"
    )


# ============================================================
# CAPTURE PAR VIEWPORTS
# ============================================================

async def capturer_morceaux(
    page,
    temp_dir
):
    """
    Descend réellement dans la page et prend une capture
    à chaque position.

    Retourne :
        [
            {
                "file": Path(...),
                "y": 0,
                "height": 1000
            },
            ...
        ]
    """

    captures = []

    position = 0

    numero = 0

    step = (
        VIEWPORT_HEIGHT
        - OVERLAP
    )


    print()
    print(
        "Capture viewport par viewport..."
    )


    while True:

        # ----------------------------------------------------
        # Hauteur actuelle
        # ----------------------------------------------------

        total_height = await hauteur_page(
            page
        )


        max_scroll = max(
            0,
            total_height - VIEWPORT_HEIGHT
        )


        position = min(
            position,
            max_scroll
        )


        # ----------------------------------------------------
        # SCROLL RÉEL
        # ----------------------------------------------------

        await page.evaluate(
            """
            y => window.scrollTo({
                top: y,
                behavior: 'smooth'
            })
            """,
            position
        )


        # Attend que le scroll soit arrivé.
        await page.wait_for_timeout(
            700
        )


        # ----------------------------------------------------
        # ANIMATIONS
        # ----------------------------------------------------

        await forcer_images_lazy(
            page
        )


        await attendre_images_visibles(
            page
        )


        # Laisse les animations d'apparition finir.
        await page.wait_for_timeout(
            ANIMATION_WAIT_MS
        )


        # Certaines bannières peuvent revenir.
        await supprimer_cookies(
            page
        )

        await supprimer_popup_brunch(page)


        # ----------------------------------------------------
        # POSITION RÉELLE
        # ----------------------------------------------------

        actual_y = await page.evaluate(
            "window.scrollY"
        )


        # ----------------------------------------------------
        # SCREENSHOT
        # ----------------------------------------------------

        fichier = (
            temp_dir
            / f"part-{numero:03d}.png"
        )


        await page.screenshot(

            path=str(
                fichier
            ),

            full_page=False

        )


        captures.append(
            {
                "file": fichier,
                "y": int(actual_y)
            }
        )


        print(
            f"  ✓ morceau {numero + 1}"
            f" — y={int(actual_y)}"
        )


        # ----------------------------------------------------
        # FIN ?
        # ----------------------------------------------------

        total_height = await hauteur_page(
            page
        )


        max_scroll = max(
            0,
            total_height - VIEWPORT_HEIGHT
        )


        if (
            actual_y >= max_scroll - 2
        ):

            break


        next_position = (
            int(actual_y)
            + step
        )


        # Protection boucle infinie
        if (
            next_position
            <= position
        ):

            break


        position = next_position

        numero += 1


        if numero > 100:

            raise RuntimeError(
                "La page semble anormalement longue."
            )


    print(
        f"✓ {len(captures)} morceaux capturés"
    )


    return captures


# ============================================================
# ASSEMBLAGE
# ============================================================

def assembler_captures(
    captures,
    output_file
):
    """
    Assemble les screenshots en tenant compte de leur position Y.

    Le chevauchement entre deux screenshots est automatiquement
    retiré.
    """

    if not captures:

        raise RuntimeError(
            "Aucune capture à assembler."
        )


    opened = []


    try:

        for capture in captures:

            image = Image.open(
                capture["file"]
            ).convert(
                "RGB"
            )

            opened.append(
                {
                    "image": image,
                    "y": capture["y"]
                }
            )


        width = opened[0][
            "image"
        ].width


        # ----------------------------------------------------
        # HAUTEUR FINALE
        # ----------------------------------------------------

        final_height = 0


        for item in opened:

            final_height = max(

                final_height,

                item["y"]
                +
                item["image"].height

            )


        # ----------------------------------------------------
        # IMAGE FINALE
        # ----------------------------------------------------

        final_image = Image.new(

            "RGB",

            (
                width,
                final_height
            ),

            "white"

        )


        # ----------------------------------------------------
        # PREMIÈRE CAPTURE
        # ----------------------------------------------------

        first = opened[0]


        final_image.paste(

            first["image"],

            (
                0,
                first["y"]
            )

        )


        previous_bottom = (
            first["y"]
            +
            first["image"].height
        )


        # ----------------------------------------------------
        # CAPTURES SUIVANTES
        # ----------------------------------------------------

        for item in opened[1:]:

            image = item["image"]

            y = item["y"]


            overlap = max(
                0,
                previous_bottom - y
            )


            # Si une partie a déjà été capturée,
            # on coupe le haut de la nouvelle capture.

            if overlap >= image.height:

                continue


            if overlap > 0:

                cropped = image.crop(
                    (
                        0,
                        overlap,
                        image.width,
                        image.height
                    )
                )

            else:

                cropped = image


            destination_y = (
                y
                +
                overlap
            )


            final_image.paste(

                cropped,

                (
                    0,
                    destination_y
                )

            )


            previous_bottom = max(

                previous_bottom,

                y + image.height

            )


        # ----------------------------------------------------
        # SAUVEGARDE
        # ----------------------------------------------------

        final_image.save(

            output_file,

            format="PNG",

            optimize=True

        )


        final_image.close()


    finally:

        for item in opened:

            item["image"].close()


async def copie_site(url, hotel_dir):
    """
    Capture uniquement la page d'accueil d'un hôtel et assemble
    l'image finale sous hotel_dir/home.png.
    """
    hotel_dir = Path(hotel_dir)

    if not hotel_dir.is_dir():
        raise RuntimeError(f"Dossier hôtel introuvable : {hotel_dir}")

    # ========================================================
    # FICHIER IMAGE DIRECTEMENT DANS LE DOSSIER HÔTEL
    # ========================================================
    screenshot_file = hotel_dir / "homepage.png"

    # ========================================================
    # CHROME
    # ========================================================
    #chrome_path = Path(CHEMIN_CHROME)

    #if not chrome_path.is_file():
    #    raise RuntimeError(f"Google Chrome est introuvable : {chrome_path}")

    print()
    print("========================================")
    print(" CAPTURE PAGE D'ACCUEIL")
    print("========================================")
    print()
    print(f"URL : {url}")

    # ========================================================
    # DOSSIER TEMPORAIRE
    # ========================================================
    temp_root = Path(tempfile.mkdtemp(prefix="sacha-capture-"))

    try:
        # ====================================================
        # PLAYWRIGHT
        # ====================================================
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                channel="chromium",
         #       executable_path=str(chrome_path),
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )

            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                screen={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                locale="fr-FR",
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
                device_scale_factor=1,
                color_scheme="light",
                reduced_motion="no-preference",
            )

            page = await context.new_page()

            try:
                print()
                print("Ouverture de la page...")
                await ouvrir_page_accueil(page, url)
                print(f"✓ Page ouverte : {page.url}")

                # 1. Attente initiale de stabilisation
                await page.wait_for_timeout(4000)

                try:
                    await page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass

                await attendre_polices(page)

                # 2. Suppression précoce des bannières cookies
                print("Suppression des cookies...")
                await supprimer_cookies(page)
                await page.wait_for_timeout(1000)

                # 3. Micro-mouvement initial pour déclencher les sliders d'en-tête
                await page.evaluate("window.scrollTo(0, 50)")
                await page.wait_for_timeout(500)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(1500)

                # 4. Chargement forcé des images lazy et déroulement complet
                await forcer_images_lazy(page)
                await precharger_page(page)

                # 5. Remontée au sommet et stabilisation finale
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(2500)

                # Nettoyage des éventuelles bannières réapparues
                await supprimer_cookies(page)

                # 6. Découpage et capture par tranches
                captures = await capturer_morceaux(page, temp_root)

            finally:
                await context.close()
                await browser.close()

        # ====================================================
        # ASSEMBLAGE DIRECT
        # ====================================================
        print()
        print("Assemblage du screenshot...")

        assembler_captures(captures, screenshot_file)

        print(f"✓ Screenshot final : {screenshot_file}")

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    return screenshot_file
