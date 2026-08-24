"""
maastokuvat.py
==============
Sijoittaa maastokuvat kartalle niiden koordinaattien perusteella ja tuottaa
GeoPackage-tason, jonka voi raahata omaan QGIS-projektiin. Kuva avautuu
QGIS:ssä hiiriesikatseluna (map tip), Identify-lomakkeessa ja erillisessä
katselimessa.

Koordinaatti otetaan kuvan EXIF:istä. Jos kuvassa ei ole GPS:ää (esim.
järjestelmäkamera), se päätellään GPS-loggerin GPX-lokista kuvausajan
perusteella — pitkien aukkojen yli ei interpoloida.

Kuvien lähde on joko paikallinen kansio (kuvat kopioidaan projektiin ja
viedään haluttaessa GitHubiin) tai julkinen Google Photos -jakoalbumi
(kuvia ei kopioida lainkaan, taso viittaa Googlen osoitteisiin — ks.
google_photos.py).

Ajo:  python3 maastokuvat.py

Vaatimukset: pip install pillow gpxpy piexif   +   QGIS (python3-qgis)
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import exif_gpx as eg
import google_photos as gp

SOVELLUS_POLKU = Path(__file__).resolve().parent
PROJEKTIT_POLKU = SOVELLUS_POLKU / "projektit"

# GitHub: kuvat viedään julkiseen repoon, ja taso viittaa niihin raw-osoitteella.
# Repo on oltava JULKINEN — privaatin repon raw-URL vaatii tokenin, jota QGIS
# ei osaa antaa. Katso README, kohta "Kuvat GitHubissa".
GITHUB_USER = "MarkusHytonenPD"
GITHUB_REPO = "maastokuvat"
GITHUB_BRANCH = "main"

ESIKATSELU_PX = 1200         # pienennetyn esikatselukuvan pisin sivu (~250 kt)
ESIKATSELU_LAATU = 80
LEDGER = "kasitellyt.json"   # kirjanpito jo tuoduista lähdekuvista


# ══════════════════════════════════════════════════════════════════
#  KIRJANPITO
# ══════════════════════════════════════════════════════════════════

def _avain(kuva: Path, tiedot: dict) -> str:
    """Lähdekuvan tunniste: tiedostonimi + kuvausaika.

    EI kokoa tai tiivistettä, koska GPS:n kirjoittaminen kuvaan muuttaisi ne.
    """
    aika = tiedot.get("aika")
    return f"{kuva.name}|{aika.isoformat() if aika else '?'}"


def lue_ledger(polku: Path) -> dict:
    if not polku.is_file():
        return {"versio": 1, "kuvat": {}}
    try:
        data = json.loads(polku.read_text(encoding="utf-8"))
        data.setdefault("kuvat", {})
        return data
    except Exception as e:
        print(f"  ⚠ {polku.name} ei ole luettavissa ({e}) — aloitetaan tyhjästä")
        return {"versio": 1, "kuvat": {}}


def kirjoita_ledger(polku: Path, data: dict):
    polku.parent.mkdir(parents=True, exist_ok=True)
    polku.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════
#  KUVIEN TUONTI
# ══════════════════════════════════════════════════════════════════

def tee_esikatselu(lahde: Path, kohde: Path) -> bool:
    """Pienentää kuvan esikatselukäyttöön (map tip). Palauttaa True jos onnistui."""
    from PIL import Image, ImageOps
    try:
        kohde.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(lahde)
        img = ImageOps.exif_transpose(img)
        img.thumbnail((ESIKATSELU_PX, ESIKATSELU_PX), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(kohde, "JPEG", quality=ESIKATSELU_LAATU, optimize=True)
        return True
    except Exception as e:
        print(f"    ⚠ esikatselu epäonnistui ({lahde.name}): {e}")
        return False


def varmista_esikatselut(projektikansio: Path) -> int:
    """
    Varmistaa että jokaisella kuvalla on riittävän iso esikatselukuva.
    Tekee puuttuvat ja uusii liian pienet (esim. jos ESIKATSELU_PX on kasvanut).
    Palauttaa tehtyjen/uusittujen määrän.
    """
    from PIL import Image
    kuvat_kansio = projektikansio / "kuvat"
    esik_kansio = projektikansio / "esikatselu"
    if not kuvat_kansio.is_dir():
        return 0

    tehty = 0
    tiedostot = []
    for paate in eg.KUVAPAATTEET:
        tiedostot.extend(kuvat_kansio.glob(f"*{paate}"))

    for kuva in sorted(set(tiedostot)):
        esik = esik_kansio / kuva.name
        tarvitaan = True
        if esik.is_file():
            try:
                with Image.open(esik) as e, Image.open(kuva) as a:
                    tavoite = min(ESIKATSELU_PX, max(a.size))
                    tarvitaan = max(e.size) < tavoite - 2
            except Exception:
                tarvitaan = True
        if tarvitaan and tee_esikatselu(kuva, esik):
            tehty += 1
    return tehty


def _vapaa_nimi(kansio: Path, nimi: str) -> Path:
    """kuvat/x.jpg → kuvat/x_2.jpg jos nimi on varattu toiselle kuvalle."""
    kohde = kansio / nimi
    if not kohde.exists():
        return kohde
    runko, paate = Path(nimi).stem, Path(nimi).suffix
    n = 2
    while (kansio / f"{runko}_{n}{paate}").exists():
        n += 1
    return kansio / f"{runko}_{n}{paate}"


def tuo_kuvat(kuvakansiot: list[Path], projektikansio: Path, gpx_pisteet: list,
              aikaero_min: int, max_aukko_min: int, kirjoita_exif: bool) -> dict:
    """
    Kopioi kuvat projektikansioon, täydentää puuttuvat koordinaatit GPX:stä
    ja tekee esikatselukuvat. Palauttaa tilastot.
    """
    kuvat_kansio = projektikansio / "kuvat"
    esik_kansio = projektikansio / "esikatselu"
    kuvat_kansio.mkdir(parents=True, exist_ok=True)

    ledger_polku = projektikansio / LEDGER
    ledger = lue_ledger(ledger_polku)
    max_aukko_s = max_aukko_min * 60

    tilastot = {"tuotu": 0, "duplikaatti": 0, "ei_sijaintia": [], "gpx": 0, "exif": 0}

    lahteet = []
    for kansio in kuvakansiot:
        for paate in eg.KUVAPAATTEET:
            lahteet.extend(kansio.glob(f"*{paate}"))
    lahteet = sorted(set(p.resolve() for p in lahteet))
    print(f"\n--- Kuvien tuonti ({len(lahteet)} lähdekuvaa) ---")

    for lahde in lahteet:
        tiedot = eg.lue_kuvan_tiedot(lahde)
        avain = _avain(lahde, tiedot)

        kirjattu = ledger["kuvat"].get(avain)
        if kirjattu and (kuvat_kansio / kirjattu["tiedosto"]).exists():
            tilastot["duplikaatti"] += 1
            continue

        def _ohita(syy: str):
            """Kirjaa ja kertoo heti miksi kuvaa ei voitu sijoittaa."""
            tilastot["ei_sijaintia"].append((lahde.name, syy))
            print(f"  ⚠ {lahde.name}: {syy}")

        lahde_tyyppi = "exif"
        if tiedot["lat"] is None:
            # Ei GPS:ää kuvassa — yritetään GPS-loggerin lokista
            if not gpx_pisteet:
                _ohita("ei EXIF-GPS:ää eikä GPX-lokia")
                continue
            if not tiedot["aika"]:
                _ohita("ei EXIF-aikaleimaa")
                continue
            import datetime
            korjattu = tiedot["aika"] - datetime.timedelta(minutes=aikaero_min)
            koord, syy = eg.interpoloi(gpx_pisteet, korjattu, max_aukko_s)
            if not koord:
                _ohita(f"({korjattu:%d.%m. %H:%M}) {syy}")
                continue
            tiedot["lat"], tiedot["lon"] = koord
            lahde_tyyppi = "gpx"

        kohde = _vapaa_nimi(kuvat_kansio, lahde.name)
        shutil.copy2(lahde, kohde)

        if lahde_tyyppi == "gpx" and kirjoita_exif:
            eg.kirjoita_exif_gps(kohde, tiedot["lat"], tiedot["lon"])

        tee_esikatselu(kohde, esik_kansio / kohde.name)

        ledger["kuvat"][avain] = {
            "tiedosto": kohde.name,
            "lahde": lahde_tyyppi,
            "lisatty": _nyt(),
        }
        tilastot[lahde_tyyppi] += 1
        tilastot["tuotu"] += 1
        merkki = "✓" if lahde_tyyppi == "exif" else "⊕"
        print(f"  {merkki} {kohde.name}  ({tiedot['lat']:.6f}, {tiedot['lon']:.6f})  {lahde_tyyppi}")

    kirjoita_ledger(ledger_polku, ledger)
    return tilastot


def _nyt() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


# ══════════════════════════════════════════════════════════════════
#  GOOGLE PHOTOS -LÄHDE
# ══════════════════════════════════════════════════════════════════
#
# Kuvia EI kopioida eikä pienennetä: taso viittaa Googlen omiin osoitteisiin
# (=d täysikokoinen, =w1200 esikatselu). Siksi polku- ja esikatselu-kentät
# jäävät tyhjiksi ja GitHub-vienti ohitetaan.
#
# Hinta: taso toimii vain niin kauan kuin albumi on jaettu linkillä, eikä
# kuvia näe ilman verkkoyhteyttä. Jos kuvat halutaan pysyviksi, sama albumi
# pitää ladata levylle ja ajaa paikallisena kuvakansiona.

GOOGLE_AVAIN = "google:"     # kirjanpidon avaimen etuliite (media-id:n edessä)


def _google_ledger_arvo(tiedot: dict) -> dict:
    """Kuvan EXIF-tiedot kirjanpitoon (aika ISO-muodossa)."""
    return {
        "tiedosto": tiedot["tiedosto"],
        "lat": tiedot["lat"], "lon": tiedot["lon"],
        "aika": tiedot["aika"].isoformat() if tiedot["aika"] else None,
        "suunta": tiedot["suunta"], "korkeus": tiedot["korkeus"],
        "valmistaja": tiedot["valmistaja"], "malli": tiedot["malli"],
        "laitetyyppi": tiedot["laitetyyppi"],
        "lahde": "google",
        "lisatty": _nyt(),
    }


def _google_ledgerista(arvo: dict) -> dict | None:
    """Kirjanpidon arvo takaisin EXIF-sanakirjaksi. None jos rivi on vaillinainen."""
    import datetime
    if not isinstance(arvo, dict) or "tiedosto" not in arvo:
        return None
    tiedot = {k: arvo.get(k) for k in
              ("tiedosto", "lat", "lon", "suunta", "korkeus",
               "valmistaja", "malli", "laitetyyppi")}
    try:
        tiedot["aika"] = (datetime.datetime.fromisoformat(arvo["aika"])
                          if arvo.get("aika") else None)
    except (TypeError, ValueError):
        return None
    return tiedot


def _vapaa_nimi_joukosta(varatut: set, nimi: str) -> str:
    """Sama kuin _vapaa_nimi, mutta levyn sijaan jo käytettyjä nimiä vasten."""
    if nimi not in varatut:
        varatut.add(nimi)
        return nimi
    runko, paate = Path(nimi).stem, Path(nimi).suffix
    n = 2
    while f"{runko}_{n}{paate}" in varatut:
        n += 1
    uusi = f"{runko}_{n}{paate}"
    varatut.add(uusi)
    return uusi


def tuo_google_kuvat(albumi_linkki: str, projektikansio: Path, gpx_pisteet: list,
                     aikaero_min: int, max_aukko_min: int) -> tuple[list[dict], list, dict]:
    """
    Lukee julkisen jakoalbumin ja muodostaa tasolle kohdelistan lataamatta
    yhtään kuvaa levylle. Palauttaa (kohteet, ilman_sijaintia, tilastot).

    EXIF luetaan verkosta vain kertaalleen kuvaa kohti: tulos jää
    kasitellyt.json-kirjanpitoon media-id:n alle, joten uudelleenajo ei lataa
    mitään. GPX-interpolointi sen sijaan tehdään joka ajossa uudelleen —
    välimuistissa on vain kuvan oma EXIF, joten myöhemmin annettu GPX-loki
    sijoittaa myös aiemmin hylätyt kuvat.
    """
    import datetime

    tilastot = {"tuotu": 0, "duplikaatti": 0, "ei_sijaintia": [],
                "gpx": 0, "exif": 0, "verkosta": 0, "kirjanpidosta": 0,
                "albumissa": 0}
    max_aukko_s = max_aukko_min * 60

    print("\n--- Google Photos -albumi ---")
    mediat = gp.hae_albumi(albumi_linkki)
    tilastot["albumissa"] = len(mediat)
    print(f"  {len(mediat)} kuvaa albumissa")

    ledger_polku = projektikansio / LEDGER
    ledger = lue_ledger(ledger_polku)

    valmiit, puuttuvat = {}, []
    for media in mediat:
        tiedot = _google_ledgerista(ledger["kuvat"].get(GOOGLE_AVAIN + media["tunnus"]))
        if tiedot:
            valmiit[media["tunnus"]] = tiedot
        else:
            puuttuvat.append(media)

    tilastot["kirjanpidosta"] = len(valmiit)
    if valmiit:
        print(f"  {len(valmiit)} kuvan tiedot kirjanpidosta (ei ladata uudelleen)")

    syyt = {}
    if puuttuvat:
        print(f"  luetaan {len(puuttuvat)} kuvan EXIF verkosta "
              f"(~{gp.EXIF_TAVUJA // 1024} kt/kuva)…")

        def _edistyminen(valmis: int, yhteensa: int):
            if valmis % 25 == 0 or valmis == yhteensa:
                print(f"    {valmis}/{yhteensa}")

        for media, tiedot, syy in gp.lue_exif_rinnakkain(puuttuvat,
                                                        edistyminen=_edistyminen):
            if not tiedot:
                syyt[media["tunnus"]] = syy
                continue
            valmiit[media["tunnus"]] = tiedot
            ledger["kuvat"][GOOGLE_AVAIN + media["tunnus"]] = _google_ledger_arvo(tiedot)
            tilastot["verkosta"] += 1
        kirjoita_ledger(ledger_polku, ledger)

    kohteet, ilman, nimet = [], [], set()
    for media in mediat:
        tiedot = valmiit.get(media["tunnus"])
        if not tiedot:
            syy = syyt.get(media["tunnus"], "EXIF:iä ei voitu lukea")
            tilastot["ei_sijaintia"].append((media["tunnus"], syy))
            print(f"  ⚠ {media['tunnus'][:14]}…: {syy}")
            continue

        nimi = tiedot["tiedosto"]
        t = dict(tiedot)
        lahde, huomio = "exif", ""

        if t["lat"] is None:
            if not gpx_pisteet:
                syy = "ei EXIF-GPS:ää eikä GPX-lokia"
            elif not t["aika"]:
                syy = "ei EXIF-aikaleimaa"
            else:
                korjattu = t["aika"] - datetime.timedelta(minutes=aikaero_min)
                koord, syy = eg.interpoloi(gpx_pisteet, korjattu, max_aukko_s)
                if koord:
                    t["lat"], t["lon"] = koord
                    lahde, huomio = "gpx", "sijainti interpoloitu GPX-lokista"
                    syy = ""
                else:
                    syy = f"({korjattu:%d.%m. %H:%M}) {syy}"
            if t["lat"] is None:
                tilastot["ei_sijaintia"].append((nimi, syy))
                ilman.append((nimi, syy))
                print(f"  ⚠ {nimi}: {syy}")
                continue

        url, url_esikatselu = gp.osoitteet(media)
        kohteet.append({
            "lat": t["lat"], "lon": t["lon"],
            "tiedosto": _vapaa_nimi_joukosta(nimet, nimi),
            "aika": t["aika"],
            "polku": "",              # kuvaa ei ole levyllä
            "esikatselu": "",
            "url": url,
            "url_esikatselu": url_esikatselu,
            "suunta": t["suunta"],
            "korkeus": t["korkeus"],
            "laite": " ".join(x for x in (t["valmistaja"], t["malli"]) if x) or "tuntematon",
            "laitetyyppi": t["laitetyyppi"],
            "lahde": lahde,
            "huomio": huomio,
        })
        tilastot[lahde] += 1
        tilastot["tuotu"] += 1

    tilastot["duplikaatti"] = tilastot["kirjanpidosta"]
    return kohteet, ilman, tilastot


# ══════════════════════════════════════════════════════════════════
#  GIT-VIENTI
# ══════════════════════════════════════════════════════════════════

def _git(*argumentit, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(SOVELLUS_POLKU), *argumentit],
                          capture_output=True, text=True, **kwargs)


def git_push(viesti: str, polut: list[str]) -> bool:
    """
    Commitoi ja pushaa annetut polut. Palauttaa True jos repo on ajan tasalla
    (myös silloin kun mitään ei ollut committoitavaa).
    """
    if not (SOVELLUS_POLKU / ".git").is_dir():
        print("  ⚠ Ei git-repoa — GitHub-vienti ohitettu.")
        return False
    if not _git("remote", "get-url", "origin").stdout.strip():
        print("  ⚠ Origin-remotea ei ole — GitHub-vienti ohitettu.")
        return False

    lisays = _git("add", "--", *polut)
    if lisays.returncode:
        print(f"  ⚠ git add epäonnistui: {lisays.stderr.strip()}")
        return False

    if not _git("diff", "--cached", "--name-only").stdout.strip():
        print("  Ei muutoksia committoitavaksi.")
        return True

    maara = len(_git("diff", "--cached", "--name-only").stdout.strip().splitlines())
    commit = _git("commit", "-m", viesti)
    if commit.returncode:
        print(f"  ⚠ git commit epäonnistui: {commit.stderr.strip() or commit.stdout.strip()}")
        return False
    print(f"  Commit: {viesti}  ({maara} tiedostoa)")

    print("  Pushataan GitHubiin… (isot kuvat voivat viedä hetken)")
    push = _git("push", "origin", GITHUB_BRANCH)
    if push.returncode:
        print(f"  ⚠ git push epäonnistui:\n{push.stderr.strip()}")
        return False
    print(f"  ✓ Pushattu: {GITHUB_USER}/{GITHUB_REPO} ({GITHUB_BRANCH})")
    return True


# ══════════════════════════════════════════════════════════════════
#  TASON KOKOAMINEN
# ══════════════════════════════════════════════════════════════════

PROJEKTI_TIEDOSTO = "projekti.json"


def raw_url_pohja(projekti: str, alikansio: str, kohde: dict | None = None) -> str:
    """GitHubin raw-osoitteen alkuosa projektin kuva- tai esikatselukansiolle."""
    from urllib.parse import quote
    k = kohde or {"user": GITHUB_USER, "repo": GITHUB_REPO, "branch": GITHUB_BRANCH}
    return (f"https://raw.githubusercontent.com/{k['user']}/{k['repo']}/"
            f"{k['branch']}/projektit/{quote(projekti)}/{alikansio}/")


def git_remote_tiedot() -> dict | None:
    """{'user', 'repo', 'branch'} origin-remotesta ja nykyisestä branchista."""
    import re
    url = _git("remote", "get-url", "origin").stdout.strip()
    if not url:
        return None
    osuma = re.search(r"(?:github\.com[:/])([^/]+)/(.+?)(?:\.git)?$", url)
    if not osuma:
        return None
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return {"user": osuma.group(1), "repo": osuma.group(2),
            "branch": branch or GITHUB_BRANCH}


def _lue_projekti_json(projektikansio: Path) -> dict:
    polku = projektikansio / PROJEKTI_TIEDOSTO
    if not polku.is_file():
        return {}
    try:
        return json.loads(polku.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ {PROJEKTI_TIEDOSTO} ei ole luettavissa ({e})")
        return {}


def _kirjoita_projekti_json(projektikansio: Path, muutokset: dict):
    """Päivittää vain annetut avaimet — muut projektin asetukset säilyvät."""
    tiedot = _lue_projekti_json(projektikansio)
    if all(tiedot.get(k) == v for k, v in muutokset.items()):
        return
    tiedot.update(muutokset)
    tiedot["kirjattu"] = _nyt()
    projektikansio.mkdir(parents=True, exist_ok=True)
    (projektikansio / PROJEKTI_TIEDOSTO).write_text(
        json.dumps(tiedot, ensure_ascii=False, indent=2), encoding="utf-8")


def lue_projekticonfig(projektikansio: Path) -> dict:
    tiedot = _lue_projekti_json(projektikansio).get("github") or {}
    return tiedot if all(k in tiedot for k in ("user", "repo", "branch")) else {}


def lue_google_albumi(projektikansio: Path) -> str:
    """Projektiin kertaalleen kirjattu Google Photos -jakolinkki."""
    linkki = _lue_projekti_json(projektikansio).get("google_albumi") or ""
    return linkki if isinstance(linkki, str) else ""


def ratkaise_kohde(projektikansio: Path) -> tuple[dict, bool]:
    """
    Päättää mihin repoon TÄMÄN projektin osoitteet viittaavat.

    Repo tallennetaan projektikohtaisesti, koska kuvat jäävät ikuisesti siihen
    repoon johon ne on kertaalleen viety. Kun yksi repo täyttyy ja uudet
    projektit ohjataan uuteen, vanhan projektin uudelleenajo ei silti saa
    kirjoittaa sen osoitteita uuteen repoon — siellä ei ole näitä kuvia.

    Palauttaa (kohde, eri_repo_kuin_origin).
    """
    nykyinen = git_remote_tiedot() or {
        "user": GITHUB_USER, "repo": GITHUB_REPO, "branch": GITHUB_BRANCH}
    tallennettu = lue_projekticonfig(projektikansio)
    if not tallennettu:
        return nykyinen, False
    eri = (tallennettu["user"], tallennettu["repo"]) != (nykyinen["user"], nykyinen["repo"])
    return tallennettu, eri


def kirjoita_projekticonfig(projektikansio: Path, kohde: dict):
    _kirjoita_projekti_json(projektikansio, {"github": kohde})


def kokoa_kohteet(projektikansio: Path, gpx_pisteet: list, aikaero_min: int,
                  max_aukko_min: int, url_kuvat: str = "",
                  url_esik: str = "") -> tuple[list[dict], list]:
    """
    Lukee projektikansion kuvat/-kansion ja muodostaa tasolle kohdelistan.
    Taso rakennetaan aina koko kansiosta, joten se pysyy erissä ajettaessa ajan tasalla.
    """
    from urllib.parse import quote
    kuvat_kansio = projektikansio / "kuvat"
    esik_kansio = projektikansio / "esikatselu"
    kohteet, ilman = [], []
    max_aukko_s = max_aukko_min * 60

    tiedostot = []
    for paate in eg.KUVAPAATTEET:
        tiedostot.extend(kuvat_kansio.glob(f"*{paate}"))

    for kuva in sorted(set(tiedostot)):
        t = eg.lue_kuvan_tiedot(kuva)
        huomio = ""
        lahde = "exif"

        if t["lat"] is None and gpx_pisteet and t["aika"]:
            import datetime
            korjattu = t["aika"] - datetime.timedelta(minutes=aikaero_min)
            koord, syy = eg.interpoloi(gpx_pisteet, korjattu, max_aukko_s)
            if koord:
                t["lat"], t["lon"] = koord
                lahde = "gpx"
                huomio = "sijainti interpoloitu GPX-lokista"

        if t["lat"] is None:
            ilman.append((kuva.name, "ei koordinaattia"))
            continue

        esikatselu = f"esikatselu/{kuva.name}" if (esik_kansio / kuva.name).exists() else ""
        laite = " ".join(x for x in (t["valmistaja"], t["malli"]) if x) or "tuntematon"

        kohteet.append({
            "lat": t["lat"], "lon": t["lon"],
            "tiedosto": kuva.name,
            "aika": t["aika"],
            "polku": f"kuvat/{kuva.name}",
            "esikatselu": esikatselu,
            "url": f"{url_kuvat}{quote(kuva.name)}" if url_kuvat else "",
            "url_esikatselu": (f"{url_esik}{quote(kuva.name)}"
                               if url_esik and esikatselu else ""),
            "suunta": t["suunta"],
            "korkeus": t["korkeus"],
            "laite": laite,
            "laitetyyppi": t["laitetyyppi"],
            "lahde": lahde,
            "huomio": huomio,
        })

    return kohteet, ilman


TILA_TIEDOSTO = "tila.json"


def tason_tunniste(kohteet: list[dict], tyyli_tunniste: str) -> str:
    """
    Tiiviste tason sisällöstä + tyylistä. Jos tämä ei ole muuttunut, tasoa ei
    tarvitse kirjoittaa uudelleen.

    Miksi: GeoPackage tallentaa muokkausaikaleiman ja QGIS kirjoittaa .qml:n
    XML-attribuutit satunnaisessa järjestyksessä, joten kummankin tavusisältö
    muuttuu joka kirjoituksella. Ilman tätä tarkistusta jokainen ajo tekisi
    turhan commitin, vaikka mikään ei olisi muuttunut.
    """
    import hashlib

    def _arvo(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    kanoninen = json.dumps(
        [{k: _arvo(v) for k, v in sorted(kohde.items())}
         for kohde in sorted(kohteet, key=lambda k: k["tiedosto"])],
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"{kanoninen}|{tyyli_tunniste}".encode()).hexdigest()


def lue_tila(projektikansio: Path) -> dict:
    polku = projektikansio / TILA_TIEDOSTO
    if not polku.is_file():
        return {}
    try:
        return json.loads(polku.read_text(encoding="utf-8"))
    except Exception:
        return {}


def kirjoita_tila(projektikansio: Path, tunniste: str, kohteita: int):
    (projektikansio / TILA_TIEDOSTO).write_text(
        json.dumps({"tunniste": tunniste, "kohteita": kohteita,
                    "paivitetty": _nyt()}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def sailyta_kasin_tehdyt(gpkg_polku: Path, kohteet: list[dict]) -> int:
    """
    Säilyttää QGIS:ssä käsin täytetyt suunta- ja huomio-arvot, kun taso
    kirjoitetaan uudelleen. Palauttaa säilytettyjen arvojen määrän.

    Luetaan suoraan SQLitesta read-only-tilassa, EI QgsVectorLayerina:
    GeoPackagen avaaminen QGIS/GDAL:lla muuttaa tiedostoa (sisäiset taulut
    päivittyvät) vaikka mitään ei kirjoitettaisi, jolloin joka ajo näyttäisi
    gitissä muutokselta.
    """
    import sqlite3
    from qgis_taso import TASON_NIMI

    if not gpkg_polku.is_file():
        return 0

    aiemmat = {}
    try:
        yhteys = sqlite3.connect(f"file:{gpkg_polku}?mode=ro", uri=True)
        try:
            for nimi, suunta, huomio in yhteys.execute(
                    f'SELECT tiedosto, suunta, huomio FROM "{TASON_NIMI}"'):
                aiemmat[nimi] = {"suunta": suunta, "huomio": huomio}
        finally:
            yhteys.close()
    except sqlite3.Error as e:
        print(f"  ⚠ Vanhaa tasoa ei voitu lukea ({e}) — käsin täytetyt arvot voivat kadota")
        return 0

    sailytetty = 0
    for k in kohteet:
        v = aiemmat.get(k["tiedosto"])
        if not v:
            continue
        if k["suunta"] is None and v["suunta"] not in (None, ""):
            try:
                k["suunta"] = float(v["suunta"])
                sailytetty += 1
            except (TypeError, ValueError):
                pass
        if not k["huomio"] and v["huomio"]:
            k["huomio"] = str(v["huomio"])
    return sailytetty


# ══════════════════════════════════════════════════════════════════
#  KYSELYT
# ══════════════════════════════════════════════════════════════════

def _kysy_kansiot(kysymys: str) -> list[Path]:
    print(f"\n{kysymys}")
    print("Yksi polku per rivi. Tyhjä rivi lopettaa.")
    polut = []
    while True:
        syote = input("  > ").strip().strip('"')
        if not syote:
            break
        p = Path(syote).expanduser()
        if p.is_dir():
            print(f"    + {p}")
            polut.append(p)
        else:
            print(f"    ⚠ Ei ole kansio: {p}")
    return list(dict.fromkeys(polut))


def _kysy_gpx_polut() -> list[Path]:
    print("\nGPX-lokit — yksi polku per rivi, tai kansio (kaikki sen .gpx-tiedostot).")
    print("Tyhjä rivi lopettaa.")
    polut = []
    while True:
        syote = input("  > ").strip().strip('"')
        if not syote:
            break
        p = Path(syote).expanduser()
        if p.is_dir():
            loydetyt = sorted(set(p.glob("*.gpx")) | set(p.glob("*.GPX")))
            if not loydetyt:
                print(f"    ⚠ Kansiossa ei ole .gpx-tiedostoja: {p}")
                continue
            for g in loydetyt:
                print(f"    + {g.name}")
            polut.extend(loydetyt)
        elif p.is_file():
            print(f"    + {p.name}")
            polut.append(p)
        else:
            print(f"    ⚠ Ei löydy: {p}")
    return list(dict.fromkeys(x.resolve() for x in polut))


def _kysy_google_albumi(oletus: str = "") -> str:
    print("\nGoogle Photos -jakoalbumin linkki (albumissa: Jaa → Kopioi linkki).")
    print("Albumin on oltava jaettu kaikille joilla on linkki — muuten kuvat")
    print("eivät näy QGIS:ssä.")
    if oletus:
        print(f"Tyhjä rivi = tälle projektille kirjattu linkki:\n  {oletus}")
    while True:
        syote = input("  > ").strip().strip('"')
        if not syote:
            return oletus
        if gp.on_jakolinkki(syote):
            return syote
        print("  ⚠ Ei näytä jakolinkiltä (odotettu photos.app.goo.gl "
              "tai photos.google.com).")


def _kysy_luku(kysymys: str, oletus: int) -> int:
    while True:
        arvo = input(f"{kysymys} [{oletus}]: ").strip()
        if not arvo:
            return oletus
        try:
            return int(arvo)
        except ValueError:
            print("  ⚠ Anna kokonaisluku.")


# ══════════════════════════════════════════════════════════════════
#  AJO
# ══════════════════════════════════════════════════════════════════

def aja(projekti: str, kuvakansiot: list[Path], gpx_polut: list[Path],
        aikaero_min: int = 0, max_aukko_min: int = eg.MAX_GPX_AUKKO_MIN,
        kirjoita_exif: bool = True, github: bool = True,
        google_albumi: str = "") -> dict:
    """
    Koko putki: tuonti → taso → tyyli → GitHub-vienti. Palauttaa tilastot.

    `google_albumi`: julkinen Google Photos -jakolinkki. Kun se on annettu,
    kuvia ei kopioida eikä viedä GitHubiin, ja `kuvakansiot`/`kirjoita_exif`
    jäävät käyttämättä — taso viittaa suoraan Googlen osoitteisiin.
    """
    from qgis_taso import kirjoita_gpkg, lataa_ja_muotoile, qgis_kaynnissa

    projektikansio = PROJEKTIT_POLKU / projekti
    projektikansio.mkdir(parents=True, exist_ok=True)

    gpx_pisteet = []
    if gpx_polut:
        print("\n--- GPS-loggerin lokit ---")
        gpx_pisteet = eg.lataa_gpx_pisteet(gpx_polut)
        if gpx_pisteet:
            print(f"  {len(gpx_pisteet)} pistettä "
                  f"({gpx_pisteet[0][0]:%d.%m. %H:%M} – {gpx_pisteet[-1][0]:%d.%m. %H:%M})")
            aukot = eg.aukot(gpx_pisteet, max_aukko_min * 60)
            if aukot:
                print(f"  {len(aukot)} aukkoa yli {max_aukko_min} min — näiden yli ei interpoloida:")
                for alku, loppu, kesto in aukot[:5]:
                    print(f"    {alku:%d.%m. %H:%M} – {loppu:%d.%m. %H:%M}  ({kesto:.0f} min)")
                if len(aukot) > 5:
                    print(f"    ... ja {len(aukot) - 5} muuta")

    google_kohteet = google_ilman = None
    if google_albumi:
        github = False                      # kuvat pysyvät Googlessa
        google_kohteet, google_ilman, tilastot = tuo_google_kuvat(
            google_albumi, projektikansio, gpx_pisteet, aikaero_min, max_aukko_min)
        tilastot["google_albumi"] = google_albumi
        _kirjoita_projekti_json(projektikansio, {"google_albumi": google_albumi})
    else:
        tilastot = tuo_kuvat(kuvakansiot, projektikansio, gpx_pisteet,
                             aikaero_min, max_aukko_min, kirjoita_exif)

        uusitut = varmista_esikatselut(projektikansio)
        if uusitut:
            print(f"  esikatselukuvia tehty/uusittu: {uusitut}")

    print("\n--- QGIS-taso ---")
    gpkg_polku = projektikansio / "maastokuvat.gpkg"
    qml_polku = projektikansio / "maastokuvat.qml"

    kohde, eri_repo = ratkaise_kohde(projektikansio)

    # Verkko-osoitteet kirjoitetaan tasoon myös silloin kun tätä ajoa ei pushata,
    # jos projekti on jo kertaalleen viety GitHubiin (projekti.json on olemassa).
    # Muuten "ei viedä nyt" tyhjentäisi toimivat osoitteet ja rikkoisi tason
    # muilla koneilla.
    osoitteet = github or bool(lue_projekticonfig(projektikansio))

    if github:
        print(f"  GitHub-kohde: {kohde['user']}/{kohde['repo']} ({kohde['branch']})")
        if eri_repo:
            nyk = git_remote_tiedot()
            print(f"  ⚠ Tämän projektin kuvat ovat repossa {kohde['user']}/{kohde['repo']},")
            print(f"    mutta tämä työkopio osoittaa repoon {nyk['user']}/{nyk['repo']}.")
            print(f"    Osoitteita EI muuteta eikä pushata — aja projekti siinä")
            print(f"    työkopiossa jonka origin on {kohde['user']}/{kohde['repo']},")
            print(f"    tai poista {PROJEKTI_TIEDOSTO} jos haluat siirtää kuvat tähän repoon.")

    with qgis_kaynnissa():
        if google_kohteet is not None:
            kohteet, ilman = google_kohteet, google_ilman
        else:
            url_kuvat = raw_url_pohja(projekti, "kuvat", kohde) if osoitteet else ""
            url_esik = raw_url_pohja(projekti, "esikatselu", kohde) if osoitteet else ""
            kohteet, ilman = kokoa_kohteet(projektikansio, gpx_pisteet, aikaero_min,
                                           max_aukko_min, url_kuvat, url_esik)
        sailytetty = sailyta_kasin_tehdyt(gpkg_polku, kohteet)
        if sailytetty:
            print(f"  {sailytetty} käsin täytettyä arvoa säilytetty")
        if not kohteet:
            print("  ⚠ Ei yhtään sijoitettavaa kuvaa — tasoa ei kirjoitettu.")
            tilastot["kohteita"] = 0
            return tilastot
        import qgis_taso
        tunniste = tason_tunniste(kohteet, qgis_taso.tyylin_tunniste())
        if gpkg_polku.is_file() and lue_tila(projektikansio).get("tunniste") == tunniste:
            print(f"  {len(kohteet)} kuvapistettä — data ja tyyli ennallaan, "
                  f"tasoa ei kirjoitettu uudelleen")
            tilastot["kirjoitettu"] = False
        else:
            maara = kirjoita_gpkg(kohteet, gpkg_polku)
            viesti = lataa_ja_muotoile(gpkg_polku, projektikansio, qml_polku)
            kirjoita_tila(projektikansio, tunniste, maara)
            print(f"  {maara} kuvapistettä → {gpkg_polku}")
            print(f"  tyyli: {viesti}")
            tilastot["kirjoitettu"] = True

    if github:
        print("\n--- GitHub-vienti ---")
        if eri_repo:
            print("  Ohitettu: projekti kuuluu toiseen repoon (ks. varoitus yllä).")
            tilastot["pushattu"] = False
        else:
            kirjoita_projekticonfig(projektikansio, kohde)
            tilastot["pushattu"] = git_push(
                f"Maastokuvat: {projekti} ({len(kohteet)} kuvapistettä)",
                [f"projektit/{projekti}"])

    tilastot["kohteita"] = len(kohteet)
    tilastot["ilman_sijaintia"] = ilman
    suunnalla = sum(1 for k in kohteet if k["suunta"] is not None)
    tilastot["suunnalla"] = suunnalla

    if tilastot["ei_sijaintia"]:
        raportti = projektikansio / "ei_sijaintia.txt"
        raportti.write_text(
            "Kuvat joita ei voitu sijoittaa kartalle\n" + "=" * 40 + "\n" +
            "\n".join(f"{nimi}\t{syy}" for nimi, syy in tilastot["ei_sijaintia"]) + "\n",
            encoding="utf-8")
        tilastot["raportti"] = raportti

    return tilastot


def main():
    print("=" * 62)
    print("  Maastokuvat — kuvat kartalle QGIS:iin")
    print("=" * 62)

    projekti = input("\nProjektin nimi:\n> ").strip()
    if not projekti:
        print("VIRHE: projektin nimi ei voi olla tyhjä.")
        return 1
    if any(c in projekti for c in '/\\:*?"<>|'):
        print("VIRHE: projektin nimessä on kelvoton merkki.")
        return 1

    print("\nKuvien lähde:")
    print("  1) paikallinen kuvakansio — kuvat kopioidaan projektiin")
    print("  2) Google Photos -jakoalbumi — kuvia ei kopioida, taso viittaa Googleen")
    lahde = input("Valinta [1]: ").strip() or "1"

    kuvakansiot, google_albumi = [], ""
    if lahde == "2":
        google_albumi = _kysy_google_albumi(
            lue_google_albumi(PROJEKTIT_POLKU / projekti))
        if not google_albumi:
            print("VIRHE: albumin linkkiä ei annettu.")
            return 1
    else:
        kuvakansiot = _kysy_kansiot("Kuvakansio(t):")
        if not kuvakansiot:
            print("VIRHE: yhtään kuvakansiota ei annettu.")
            return 1

    gpx_polut, aikaero_min = [], 0
    max_aukko_min = eg.MAX_GPX_AUKKO_MIN
    if input("\nOnko mukana GPS-loggerin GPX-lokeja? (k/e): ").strip().lower() == "k":
        gpx_polut = _kysy_gpx_polut()
        if gpx_polut:
            print("\nKameran kellodrifti minuutteina (0 jos synkronoitu puhelimeen).")
            print("Aikavyöhyke hoidetaan automaattisesti.")
            aikaero_min = _kysy_luku("  Drifti", 0)
            print("\nSuurin sallittu aukko GPX-pisteiden välissä minuutteina.")
            print("Pidempien aukkojen (loggeri pois päältä) yli ei interpoloida.")
            max_aukko_min = _kysy_luku("  Aukko", eg.MAX_GPX_AUKKO_MIN)

    kirjoita_exif, github = True, False
    if not google_albumi:
        kirjoita_exif = input(
            "\nKirjoitetaanko GPX:stä saatu koordinaatti kuvakopion EXIF:iin? (K/e): "
        ).strip().lower() != "e"

        github = input(
            f"\nViedäänkö kuvat GitHubiin ({GITHUB_USER}/{GITHUB_REPO})? (K/e): "
        ).strip().lower() != "e"

    tilastot = aja(projekti, kuvakansiot, gpx_polut, aikaero_min,
                   max_aukko_min, kirjoita_exif, github, google_albumi)

    projektikansio = PROJEKTIT_POLKU / projekti
    print()
    print("=" * 62)
    print("  Valmis!")
    if google_albumi:
        print(f"  Kuvia albumissa:    {tilastot.get('albumissa', 0)}  "
              f"(EXIF verkosta {tilastot.get('verkosta', 0)}, "
              f"kirjanpidosta {tilastot.get('kirjanpidosta', 0)})")
        print(f"  Sijoitettu:         {tilastot['tuotu']}  "
              f"(EXIF {tilastot['exif']}, GPX {tilastot['gpx']})")
    else:
        print(f"  Kuvia tuotu:        {tilastot['tuotu']}  "
              f"(EXIF {tilastot['exif']}, GPX {tilastot['gpx']})")
        if tilastot["duplikaatti"]:
            print(f"  Jo tuotu aiemmin:   {tilastot['duplikaatti']}")
    print(f"  Kuvapisteitä tasolla: {tilastot.get('kohteita', 0)}"
          f"  (kuvaussuunta {tilastot.get('suunnalla', 0)}:lla)")
    if tilastot["ei_sijaintia"]:
        print(f"  Ilman sijaintia:    {len(tilastot['ei_sijaintia'])}  "
              f"→ {tilastot.get('raportti', '')}")
    if github:
        tila = "pushattu" if tilastot.get("pushattu") else "EI PUSHATTU — katso viesti yllä"
        print(f"  GitHub:             {tila}")
    print(f"\n  Raahaa QGIS:iin:    {projektikansio / 'maastokuvat.gpkg'}")
    if google_albumi:
        print("  Kuvat luetaan Google Photosista: taso vaatii verkkoyhteyden ja")
        print("  toimii niin kauan kuin albumi on jaettu linkillä.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
