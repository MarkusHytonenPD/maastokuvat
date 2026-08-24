"""
google_photos.py
================
Lukee julkisen Google Photos -jakoalbumin suoraan Googlelta: koordinaatit
kuvien EXIF:istä ja kuvaosoitteet QGIS-tasoon. Kuvia EI kopioida mihinkään
eikä viedä GitHubiin — taso viittaa Googlen omiin osoitteisiin.

Miksi ei Googlen virallista APIa:
  • Library API rajattiin 31.3.2025 vain sovelluksen itse lataamaan sisältöön;
    jaettujen albumien funktiot palauttavat 403 PERMISSION_DENIED.
  • API ei anna EXIF-GPS:ää lainkaan (Google jätti sijainnin pois tietosuojasyistä)
    — eli juuri sitä mitä tämä sovellus tarvitsee.
  • API:n baseUrl vanhenee 60 minuutissa, joten sitä ei voi tallentaa
    GeoPackageen pysyväksi osoitteeksi.

Siksi luetaan jakolinkin julkinen sivu, jonka HTML sisältää kuvien
lh3.googleusercontent.com-osoitteet. Nämä toimivat ilman kirjautumista, myös
QGIS:n map tipissä. HUOM: tämä ei ole dokumentoitu rajapinta. Jos Google
muuttaa sivun rakennetta, korjattava kohta on _MEDIA-lauseke.

Osoitteen perässä oleva pääte valitsee koon (verifioitu 24.8.2026):
  =d      alkuperäinen tiedosto, EXIF + GPS mukana   → täysikokoinen kuva
  =w1200  pienennetty JPEG, EXIF riisuttu            → map tip

EXIF luetaan Range-pyynnöllä: JPEG:n alusta riittää EXIF_TAVUJA tavua, joten
300 kuvan albumin koordinaatit saa ~40 MB:llä eikä 600 MB:llä.
"""

import concurrent.futures
import io
import re
import urllib.error
import urllib.parse
import urllib.request

import exif_gpx as eg

ALKUPERAINEN = "=d"          # pääte täysikokoiselle (EXIF mukana)
ESIKATSELU = "=w1200"        # pääte esikatselulle (vastaa ESIKATSELU_PX:ää)

EXIF_TAVUJA = 131072         # kuinka paljon kuvan alusta ladataan EXIF-lukuun
AIKAKATKAISU = 30            # s
SAMANAIKAISET = 8            # rinnakkaiset EXIF-latausket
YRITYKSET = 3                # uudelleenyritykset: Google palauttaa satunnaisia 5xx-virheitä
ODOTUS = 1.5                 # s ensimmäisen uusinnan edessä (kasvaa yrityksittäin)
JAKOHOSTIT = ("photos.app.goo.gl", "photos.google.com")

# Google tarjoilee albumisivun vain selaimeksi tunnistautuvalle pyynnölle.
_SELAIN = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Albumisivun datalohkossa: ["<media-id>",["<kuvan url>",leveys,korkeus,...]
_MEDIA = re.compile(
    r'\["(AF1Qip[A-Za-z0-9_-]{16,})",'
    r'\["(https://lh3\.googleusercontent\.com/[A-Za-z0-9_/-]+)",(\d+),(\d+),')


def on_jakolinkki(teksti: str) -> bool:
    """True jos teksti näyttää Google Photos -jakolinkiltä."""
    try:
        osat = urllib.parse.urlparse(teksti.strip())
    except ValueError:
        return False
    return osat.scheme in ("http", "https") and osat.netloc in JAKOHOSTIT


def _pyynto(url: str, otsikot: dict | None = None) -> urllib.request.Request:
    kaikki = {"User-Agent": _SELAIN, "Accept-Language": "fi,en;q=0.8"}
    kaikki.update(otsikot or {})
    return urllib.request.Request(url, headers=kaikki)


def hae_sivu(linkki: str) -> str:
    """Lataa jakoalbumin HTML:n (seuraa goo.gl-uudelleenohjauksen)."""
    with urllib.request.urlopen(_pyynto(linkki), timeout=AIKAKATKAISU) as vastaus:
        return vastaus.read().decode("utf-8", errors="replace")


def _jasenna_media(html: str) -> list[dict]:
    """Poimii albumin kuvat sivun datalohkosta, albumin järjestyksessä."""
    mediat, nahdyt = [], set()
    for tunnus, url, leveys, korkeus in _MEDIA.findall(html):
        if tunnus in nahdyt:
            continue
        nahdyt.add(tunnus)
        mediat.append({"tunnus": tunnus, "url": url,
                       "leveys": int(leveys), "korkeus": int(korkeus)})
    return mediat


def hae_albumi(linkki: str) -> list[dict]:
    """
    Jakolinkki → [{tunnus, url, leveys, korkeus}, ...].

    Nostaa RuntimeErrorin jos sivua ei saa tai siitä ei löydy kuvia (albumin
    jakaminen lopetettu, väärä linkki, tai Google muutti sivun rakenteen).
    """
    if not on_jakolinkki(linkki):
        raise RuntimeError(f"Ei ole Google Photos -jakolinkki: {linkki}")
    try:
        html = hae_sivu(linkki)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        raise RuntimeError(f"Albumisivua ei saatu ladattua: {e}") from e

    mediat = _jasenna_media(html)
    if not mediat:
        raise RuntimeError(
            "Albumista ei löytynyt kuvia. Tarkista että linkki on voimassa ja "
            "albumi on jaettu 'kaikille joilla on linkki'. Jos linkki toimii "
            "selaimessa, Google on voinut muuttaa sivun rakennetta "
            "(korjattava: google_photos._MEDIA).")
    return mediat


def _tiedostonimi(otsikko: str | None, tunnus: str) -> str:
    """Alkuperäinen tiedostonimi Content-Dispositionista, muuten media-id."""
    if otsikko:
        osuma = re.search(r'filename\*?="?([^";]+)"?', otsikko)
        if osuma:
            nimi = urllib.parse.unquote(osuma.group(1)).strip()
            nimi = nimi.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if nimi:
                return nimi
    return f"{tunnus[:24]}.jpg"


def _lataa_alku(url: str, tavuja: int) -> tuple[bytes, str, str]:
    """
    (data, tiedostonimi-otsikko, virhe). Yrittää uudelleen ohimenevän virheen
    jälkeen: 300 kuvan albumissa Google palautti yhdelle kuvalle 500:n, joka
    meni ohi heti uusinnalla.
    """
    import time
    virhe = ""
    for yritys in range(1, YRITYKSET + 1):
        try:
            pyynto = _pyynto(url, {"Range": f"bytes=0-{tavuja - 1}"})
            with urllib.request.urlopen(pyynto, timeout=AIKAKATKAISU) as vastaus:
                tyyppi = (vastaus.headers.get("Content-Type") or "").lower()
                if not tyyppi.startswith("image/"):
                    return b"", "", f"ei ole kuva ({tyyppi or 'tyyppi tuntematon'})"
                return (vastaus.read(tavuja),
                        vastaus.headers.get("Content-Disposition") or "", "")
        except urllib.error.HTTPError as e:
            virhe = f"HTTP {e.code}"
            if e.code < 500 and e.code != 429:      # 403/404 ei parane odottamalla
                break
        except (urllib.error.URLError, OSError) as e:
            virhe = str(e)
        if yritys < YRITYKSET:
            time.sleep(ODOTUS * yritys)
    return b"", "", f"lataus epäonnistui ({virhe})"


def lue_exif(media: dict, tavuja: int = EXIF_TAVUJA) -> tuple[dict | None, str]:
    """
    Lataa kuvan alusta `tavuja` tavua ja lukee siitä EXIF:in.

    Palauttaa (tiedot, "") tai (None, syy). Tiedot on eg.lue_kuvan_tiedot()in
    sanakirja + "tiedosto" (alkuperäinen tiedostonimi).
    """
    data, otsikko, virhe = _lataa_alku(media["url"] + ALKUPERAINEN, tavuja)
    if virhe:
        return None, virhe
    nimi = _tiedostonimi(otsikko, media["tunnus"])

    if not data:
        return None, "tyhjä vastaus"

    # PIL lukee EXIF:in tiedoston alusta eikä tarvitse kokonaista kuvaa.
    tiedot = eg.lue_kuvan_tiedot(io.BytesIO(data))
    tiedot["tiedosto"] = nimi
    return tiedot, ""


def lue_exif_rinnakkain(mediat: list[dict], samanaikaiset: int = SAMANAIKAISET,
                        edistyminen=None) -> list[tuple[dict, dict | None, str]]:
    """
    Lukee usean kuvan EXIF:in rinnakkain. Palauttaa listan
    [(media, tiedot | None, syy), ...] samassa järjestyksessä kuin `mediat`.

    `edistyminen(valmiit, yhteensa)` kutsutaan jokaisen valmistuneen jälkeen.
    """
    tulokset: list[tuple[dict, dict | None, str] | None] = [None] * len(mediat)
    if not mediat:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=samanaikaiset) as pool:
        tyot = {pool.submit(lue_exif, m): i for i, m in enumerate(mediat)}
        for valmis, tyo in enumerate(concurrent.futures.as_completed(tyot), 1):
            i = tyot[tyo]
            try:
                tiedot, syy = tyo.result()
            except Exception as e:                      # ei kaadeta koko ajoa
                tiedot, syy = None, f"virhe EXIF-luvussa ({e})"
            tulokset[i] = (mediat[i], tiedot, syy)
            if edistyminen:
                edistyminen(valmis, len(mediat))
    return [t for t in tulokset if t is not None]


def osoitteet(media: dict) -> tuple[str, str]:
    """(täysikokoisen url, esikatselun url) tasolle."""
    return media["url"] + ALKUPERAINEN, media["url"] + ESIKATSELU
