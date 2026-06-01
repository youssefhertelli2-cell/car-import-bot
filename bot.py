import os
import json
import time
import logging
import hashlib
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_TOKEN_ICI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "TON_CHAT_ID_ICI")
MARGE_MIN_CHF = int(os.getenv("MARGE_MIN_CHF", "2000"))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "3600"))
SEEN_FILE = "seen_listings.json"
EUR_TO_CHF = 0.96

FRAIS_IMPORT_CHF = {
    "tva": 0.077,
    "homologation": 300,
    "transport": 450,
    "divers": 200,
}

MARQUES_MOBILE_DE = {
    "VW": "volkswagen",
    "Audi": "audi",
    "Mercedes": "mercedes-benz",
    "BMW": "bmw",
    "Porsche": "porsche",
    "Opel": "opel",
    "Toyota": "toyota",
}

SEARCH_PARAMS = {
    "minFirstRegistrationYear": 2018,
    "maxMileage": 100000,
    "maxPrice": 20000,
    "fuel": "PETROL",
    "transmission": "AUTOMATIC",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def get_eur_chf_rate():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/EUR", timeout=10)
        data = r.json()
        rate = data["rates"]["CHF"]
        log.info("Taux EUR/CHF : %s", rate)
        return rate
    except Exception as e:
        log.warning("Impossible de recuperer le taux, fallback 0.96 : %s", e)
        return 0.96

def calculer_marge(prix_eur, prix_autoscout_chf, taux=EUR_TO_CHF):
    valeur_chf = prix_eur * taux
    frais = (
        valeur_chf * FRAIS_IMPORT_CHF["tva"]
        + FRAIS_IMPORT_CHF["homologation"]
        + FRAIS_IMPORT_CHF["transport"]
        + FRAIS_IMPORT_CHF["divers"]
    )
    cout_total = valeur_chf + frais
    marge = prix_autoscout_chf - cout_total
    return round(marge, 0), round(cout_total, 0), round(frais, 0)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,fr;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def scrape_mobile_de(marque_slug):
    url = (
        "https://suchen.mobile.de/fahrzeuge/search.html"
        "?makeModelVariant1.makeId=" + marque_slug +
        "&minFirstRegistrationYear=" + str(SEARCH_PARAMS["minFirstRegistrationYear"]) +
        "&maxMileage=" + str(SEARCH_PARAMS["maxMileage"]) +
        "&maxPrice=" + str(SEARCH_PARAMS["maxPrice"]) +
        "&fuel=" + SEARCH_PARAMS["fuel"] +
        "&transmission=" + SEARCH_PARAMS["transmission"] +
        "&isSearchRequest=true&sortOption.sortBy=price.ASCENDING"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning("Erreur scraping mobile.de (%s): %s", marque_slug, e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    annonces = []
    cards = soup.select("div.cBox-body--resultitem")

    for card in cards:
        try:
            titre_el = card.select_one("span.h3.u-text-break-word")
            prix_el = card.select_one("span.h3.u-block")
            km_el = card.select_one("div.rbt-regMilePowerLang")
            lien_el = card.select_one("a.link--muted")

            if not (titre_el and prix_el and lien_el):
                continue

            titre = titre_el.get_text(strip=True)
            prix_txt = prix_el.get_text(strip=True).replace(".", "").replace("€", "").replace(",", ".").strip()
            lien = "https://suchen.mobile.de" + lien_el.get("href", "")
            km_txt = km_el.get_text(strip=True) if km_el else ""

            try:
                prix = float(prix_txt)
            except ValueError:
                continue

            annonce_id = hashlib.md5(lien.encode()).hexdigest()
            annonces.append({
                "id": annonce_id,
                "titre": titre,
                "prix_eur": prix,
                "km": km_txt,
                "lien": lien,
                "source": "mobile.de",
            })
        except Exception as e:
            log.debug("Erreur parsing carte: %s", e)
            continue

    log.info("mobile.de [%s] : %d annonces trouvees", marque_slug, len(annonces))
    return annonces

def get_prix_marche_autoscout(titre, annee_min=2018):
    mots = titre.split()
    marque = mots[0] if mots else ""
    modele = mots[1] if len(mots) > 1 else ""
    url = (
        "https://www.autoscout24.ch/fr/voitures"
        "?make=" + marque.lower() +
        "&model=" + modele.lower() +
        "&fregfrom=" + str(annee_min) +
        "&gear=A&fuel=B&sort=price&atype=C"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning("Erreur AutoScout24.ch: %s", e)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    prix_list = []
    for el in soup.select("[data-price], .ListItem_price__TxBmj, .Price_price__VOT1I"):
        txt = el.get_text(strip=True).replace("'", "").replace("CHF", "").replace(" ", "").strip()
        try:
            prix_list.append(float(txt))
        except ValueError:
            continue

    if not prix_list:
        return None

    prix_list.sort()
    mediane = prix_list[len(prix_list) // 2]
    log.info("AutoScout24 [%s %s] : mediane CHF %d (%d annonces)", marque, modele, mediane, len(prix_list))
    return mediane

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

def format_alerte(annonce, marge, cout_total, frais, prix_marche_chf, taux):
    emoji = "SUPER AFFAIRE" if marge > 4000 else "BONNE AFFAIRE"
    return (
        emoji + " DETECTEE\n\n"
        "Voiture : " + annonce["titre"] + "\n"
        "Source : " + annonce["source"] + "\n"
        "Kilometrage : " + annonce["km"] + "\n\n"
        "Prix Allemagne : " + str(int(annonce["prix_eur"])) + " EUR\n"
        "Valeur en CHF : " + str(int(annonce["prix_eur"] * taux)) + " CHF\n"
        "Frais import estimes : " + str(int(frais)) + " CHF\n"
        "(TVA 7.7% + homologation + transport)\n"
        "Cout total : " + str(int(cout_total)) + " CHF\n\n"
        "Prix marche CH (AutoScout24) : " + str(int(prix_marche_chf)) + " CHF\n"
        "Marge nette estimee : " + str(int(marge)) + " CHF\n\n"
        "Lien : " + annonce["lien"]
    )

def scan():
    global EUR_TO_CHF
    log.info("Demarrage du scan")
    EUR_TO_CHF = get_eur_chf_rate()
    seen = load_seen()
    nouvelles = 0

    for marque_nom, marque_slug in MARQUES_MOBILE_DE.items():
        log.info("Scan %s...", marque_nom)
        annonces = scrape_mobile_de(marque_slug)

        for annonce in annonces:
            if annonce["id"] in seen:
                continue
            prix_marche = get_prix_marche_autoscout(annonce["titre"])
            if prix_marche is None:
                prix_marche = annonce["prix_eur"] * EUR_TO_CHF * 1.20

            marge, cout_total, frais = calculer_marge(annonce["prix_eur"], prix_marche, EUR_TO_CHF)

            if marge >= MARGE_MIN_CHF:
                msg = format_alerte(annonce, marge, cout_total, frais, prix_marche, EUR_TO_CHF)
                send_telegram(msg)
                nouvelles += 1
                log.info("Alerte envoyee : %s - marge %d CHF", annonce["titre"], marge)

            seen.add(annonce["id"])
            time.sleep(1.5)

        time.sleep(3)

    save_seen(seen)
    log.info("Scan termine - %d alertes envoyees", nouvelles)

def main():
    log.info("Bot Import Auto DE-CH demarre")
    send_telegram(
        "<b>Bot Import Auto demarre !</b>\n"
        "Surveille : VW, Audi, Mercedes, BMW, Porsche, Opel, Toyota\n"
        "Budget max : 20000 EUR\n"
        "Filtre : Essence - Boite auto - moins de 100k km - 2018+\n"
        "Marge min pour alerte : " + str(MARGE_MIN_CHF) + " CHF\n"
        "Scan toutes les " + str(SCAN_INTERVAL // 60) + " minutes"
    )
    while True:
        try:
            scan()
        except Exception as e:
            log.error("Erreur dans le scan principal : %s", e)
            send_telegram("Erreur bot : " + str(e))
        log.info("Prochain scan dans %d min...", SCAN_INTERVAL // 60)
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
