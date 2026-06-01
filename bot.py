import os
import json
import time
import logging
import hashlib
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_TOKEN_ICI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "TON_CHAT_ID_ICI")
MARGE_MIN_CHF = int(os.getenv("MARGE_MIN_CHF", "500"))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "3600"))
SEEN_FILE = "seen_listings.json"

# Criteres de recherche
ANNEE_MIN = 2014
KM_MAX = 100000
PRIX_MAX = 20000

MARQUES = ["vw", "audi", "mercedes", "bmw", "porsche", "opel", "toyota"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CH,fr;q=0.9,de;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.autoscout24.ch/",
}

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def send_telegram(message):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Message Telegram envoye")
    except Exception as e:
        log.error("Erreur Telegram: %s", e)

def calculer_score(prix_chf, prix_median_chf):
    if prix_median_chf is None or prix_median_chf == 0:
        return 0
    return round((1 - prix_chf / prix_median_chf) * 100, 1)

def scrape_autoscout(marque):
    url = (
        "https://www.autoscout24.ch/fr/voitures"
        "?make=" + marque +
        "&fregfrom=" + str(ANNEE_MIN) +
        "&kmto=" + str(KM_MAX) +
        "&priceto=" + str(PRIX_MAX) +
        "&gear=A" +
        "&fuel=B" +
        "&sort=price" +
        "&atype=C" +
        "&ustate=N%2CU"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning("Erreur AutoScout24 (%s): %s", marque, e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    annonces = []

    # Chercher les listings
    cards = soup.select("article[data-itype='listing']")
    if not cards:
        cards = soup.select("div[data-source='listPage']")
    if not cards:
        # Essai avec selecteur generique
        cards = soup.select("article")

    log.info("AutoScout24 [%s] : %d cards trouvees", marque, len(cards))

    for card in cards:
        try:
            # Titre
            titre_el = card.select_one("h2, h3, [data-testid='listing-title']")
            titre = titre_el.get_text(strip=True) if titre_el else marque.upper()

            # Prix
            prix_el = card.select_one("[data-testid='price'], .price, [class*='Price']")
            if not prix_el:
                prix_el = card.select_one("strong, b")
            if not prix_el:
                continue

            prix_txt = prix_el.get_text(strip=True)
            prix_txt = prix_txt.replace("'", "").replace("CHF", "").replace(" ", "").replace(".-", "").strip()
            try:
                prix = int(float(prix_txt))
            except ValueError:
                continue

            if prix < 1000 or prix > PRIX_MAX:
                continue

            # Lien
            lien_el = card.select_one("a[href]")
            lien = ""
            if lien_el:
                href = lien_el.get("href", "")
                if href.startswith("http"):
                    lien = href
                else:
                    lien = "https://www.autoscout24.ch" + href

            # Kilometrage
            km_el = card.select_one("[data-testid='mileage'], [class*='mileage'], [class*='Mileage']")
            km_txt = km_el.get_text(strip=True) if km_el else "N/A"

            # Annee
            annee_el = card.select_one("[data-testid='first-registration'], [class*='registration']")
            annee_txt = annee_el.get_text(strip=True) if annee_el else ""

            annonce_id = hashlib.md5(lien.encode()).hexdigest() if lien else hashlib.md5((titre + str(prix)).encode()).hexdigest()

            annonces.append({
                "id": annonce_id,
                "titre": titre,
                "prix_chf": prix,
                "km": km_txt,
                "annee": annee_txt,
                "lien": lien,
                "marque": marque.upper(),
            })

        except Exception as e:
            log.debug("Erreur parsing card: %s", e)
            continue

    return annonces

def calculer_prix_median(annonces):
    prix = sorted([a["prix_chf"] for a in annonces if a["prix_chf"] > 0])
    if not prix:
        return None
    return prix[len(prix) // 2]

def format_alerte(annonce, economie_chf, prix_median, pct):
    niveau = "SUPER AFFAIRE" if pct > 20 else "BONNE AFFAIRE"
    return (
        niveau + " sur AutoScout24.ch\n\n"
        "Voiture : " + annonce["titre"] + "\n"
        "Marque : " + annonce["marque"] + "\n"
        "Annee : " + annonce["annee"] + "\n"
        "Kilometrage : " + annonce["km"] + "\n\n"
        "Prix annonce : <b>" + str(annonce["prix_chf"]) + " CHF</b>\n"
        "Prix median du marche : " + str(prix_median) + " CHF\n"
        "Economie estimee : <b>" + str(int(economie_chf)) + " CHF (" + str(pct) + "% sous le marche)</b>\n\n"
        "Lien : " + annonce["lien"]
    )

def scan():
    log.info("Demarrage du scan AutoScout24.ch")
    seen = load_seen()
    nouvelles = 0

    for marque in MARQUES:
        log.info("Scan %s...", marque.upper())
        annonces = scrape_autoscout(marque)

        if not annonces:
            log.info("Aucune annonce trouvee pour %s", marque)
            time.sleep(3)
            continue

        prix_median = calculer_prix_median(annonces)
        log.info("%s : %d annonces, prix median %s CHF", marque.upper(), len(annonces), prix_median)

        for annonce in annonces:
            if annonce["id"] in seen:
                continue

            if prix_median and prix_median > 0:
                economie = prix_median - annonce["prix_chf"]
                pct = calculer_score(annonce["prix_chf"], prix_median)

                if economie >= MARGE_MIN_CHF and pct > 5:
                    msg = format_alerte(annonce, economie, prix_median, pct)
                    send_telegram(msg)
                    nouvelles += 1
                    log.info("Alerte : %s - %d CHF sous median", annonce["titre"], economie)

            seen.add(annonce["id"])
            time.sleep(0.5)

        time.sleep(4)

    save_seen(seen)
    log.info("Scan termine - %d alertes envoyees", nouvelles)

def main():
    log.info("Bot AutoScout24.ch demarre")
    send_telegram(
        "<b>Bot Import Auto demarre !</b>\n"
        "Source : AutoScout24.ch\n"
        "Surveille : VW, Audi, Mercedes, BMW, Porsche, Opel, Toyota\n"
        "Budget max : " + str(PRIX_MAX) + " CHF\n"
        "Filtre : Essence - Boite auto - moins de " + str(KM_MAX) + " km - " + str(ANNEE_MIN) + "+\n"
        "Economie min pour alerte : " + str(MARGE_MIN_CHF) + " CHF sous le marche\n"
        "Scan toutes les " + str(SCAN_INTERVAL // 60) + " minutes"
    )
    while True:
        try:
            scan()
        except Exception as e:
            log.error("Erreur scan principal : %s", e)
            send_telegram("Erreur bot : " + str(e))
        log.info("Prochain scan dans %d min...", SCAN_INTERVAL // 60)
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
