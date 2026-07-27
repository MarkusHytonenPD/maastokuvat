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

Ajo:  python3 maastokuvat.py

Vaatimukset: pip install pillow gpxpy piexif   +   QGIS (python3-qgis)
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import exif_gpx as eg

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

        lahde_tyyppi = "exif"
        if tiedot["lat"] is None:
            # Ei GPS:ää kuvassa — yritetään GPS-loggerin lokista
            if not gpx_pisteet:
                tilastot["ei_sijaintia"].append((lahde.name, "ei EXIF-GPS:ää eikä GPX-lokia"))
                continue
            if not tiedot["aika"]:
                tilastot["ei_sijaintia"].append((lahde.name, "ei EXIF-aikaleimaa"))
                continue
            import datetime
            korjattu = tiedot["aika"] - datetime.timedelta(minutes=aikaero_min)
            koord, syy = eg.interpoloi(gpx_pisteet, korjattu, max_aukko_s)
            if not koord:
                tilastot["ei_sijaintia"].append((lahde.name, syy))
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

def raw_url_pohja(projekti: str, alikansio: str) -> str:
    """GitHubin raw-osoitteen alkuosa projektin kuva- tai esikatselukansiolle."""
    from urllib.parse import quote
    return (f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/"
            f"{GITHUB_BRANCH}/projektit/{quote(projekti)}/{alikansio}/")


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


def sailyta_kasin_tehdyt(gpkg_polku: Path, kohteet: list[dict]) -> int:
    """
    Säilyttää QGIS:ssä käsin täytetyt suunta- ja huomio-arvot, kun taso
    kirjoitetaan uudelleen. Palauttaa säilytettyjen arvojen määrän.
    """
    if not gpkg_polku.is_file():
        return 0
    from qgis.core import QgsVectorLayer
    from qgis_taso import TASON_NIMI
    vanha = QgsVectorLayer(f"{gpkg_polku}|layername={TASON_NIMI}", "vanha", "ogr")
    if not vanha.isValid():
        return 0
    aiemmat = {}
    for f in vanha.getFeatures():
        aiemmat[f["tiedosto"]] = {"suunta": f["suunta"], "huomio": f["huomio"]}
    del vanha          # taso ei saa jäädä elossa QGIS:n sammutuksen yli
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
        kirjoita_exif: bool = True, github: bool = True) -> dict:
    """Koko putki: tuonti → taso → tyyli → GitHub-vienti. Palauttaa tilastot."""
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

    tilastot = tuo_kuvat(kuvakansiot, projektikansio, gpx_pisteet,
                         aikaero_min, max_aukko_min, kirjoita_exif)

    uusitut = varmista_esikatselut(projektikansio)
    if uusitut:
        print(f"  esikatselukuvia tehty/uusittu: {uusitut}")

    print("\n--- QGIS-taso ---")
    gpkg_polku = projektikansio / "maastokuvat.gpkg"
    qml_polku = projektikansio / "maastokuvat.qml"

    with qgis_kaynnissa():
        url_kuvat = raw_url_pohja(projekti, "kuvat") if github else ""
        url_esik = raw_url_pohja(projekti, "esikatselu") if github else ""
        kohteet, ilman = kokoa_kohteet(projektikansio, gpx_pisteet, aikaero_min,
                                       max_aukko_min, url_kuvat, url_esik)
        sailytetty = sailyta_kasin_tehdyt(gpkg_polku, kohteet)
        if sailytetty:
            print(f"  {sailytetty} käsin täytettyä arvoa säilytetty")
        if not kohteet:
            print("  ⚠ Ei yhtään sijoitettavaa kuvaa — tasoa ei kirjoitettu.")
            tilastot["kohteita"] = 0
            return tilastot
        maara = kirjoita_gpkg(kohteet, gpkg_polku)
        viesti = lataa_ja_muotoile(gpkg_polku, projektikansio, qml_polku)
        print(f"  {maara} kuvapistettä → {gpkg_polku}")
        print(f"  tyyli: {viesti}")

    if github:
        print("\n--- GitHub-vienti ---")
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

    kirjoita_exif = input(
        "\nKirjoitetaanko GPX:stä saatu koordinaatti kuvakopion EXIF:iin? (K/e): "
    ).strip().lower() != "e"

    github = input(
        f"\nViedäänkö kuvat GitHubiin ({GITHUB_USER}/{GITHUB_REPO})? (K/e): "
    ).strip().lower() != "e"

    tilastot = aja(projekti, kuvakansiot, gpx_polut, aikaero_min,
                   max_aukko_min, kirjoita_exif, github)

    projektikansio = PROJEKTIT_POLKU / projekti
    print()
    print("=" * 62)
    print("  Valmis!")
    print(f"  Kuvia tuotu:        {tilastot['tuotu']}  "
          f"(EXIF {tilastot['exif']}, GPX {tilastot['gpx']})")
    if tilastot["duplikaatti"]:
        print(f"  Jo tuotu aiemmin:   {tilastot['duplikaatti']}")
    print(f"  Kuvapisteitä tasolla: {tilastot.get('kohteita', 0)}"
          f"  (kuvaussuunta {tilastot.get('suunnalla', 0)}:lla)")
    if tilastot["ei_sijaintia"]:
        print(f"  Ilman sijaintia:    {len(tilastot['ei_sijaintia'])}  "
              f"→ {tilastot.get('raportti', '')}")
    print()
    if github:
        tila = "pushattu" if tilastot.get("pushattu") else "EI PUSHATTU — katso viesti yllä"
        print(f"  GitHub:             {tila}")
    print()
    print(f"  Raahaa QGIS:iin:    {projektikansio / 'maastokuvat.gpkg'}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
