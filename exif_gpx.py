"""
exif_gpx.py
===========
Maastokuvien EXIF-luku/kirjoitus ja GPS-loggerin GPX-lokien tulkinta.

Logiikka on peräisin rak_kult_kuvakarttajulkaisu/pipeline.py:stä ja säilyttää
sen tärkeimmän ominaisuuden: pitkien GPX-aukkojen yli EI interpoloida, koska
silloin loggeri on ollut pois päältä eikä kuvan sijaintia voi päätellä.
"""

import datetime
import zoneinfo
from pathlib import Path

import gpxpy
import piexif
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

_HELSINKI = zoneinfo.ZoneInfo("Europe/Helsinki")

# Suurin GPX-pisteväli jonka yli interpoloidaan (minuuttia).
MAX_GPX_AUKKO_MIN = 10

_DRONE_MAKE = {"dji", "autel", "parrot", "skydio", "yuneec"}
_PHONE_MAKE = {"apple", "samsung", "google", "huawei", "xiaomi", "oneplus",
               "motorola", "lg", "nothing", "fairphone"}

KUVAPAATTEET = (".jpg", ".jpeg", ".JPG", ".JPEG")


# ══════════════════════════════════════════════════════════════════
#  EXIF-LUKU
# ══════════════════════════════════════════════════════════════════

def _exif_sanakirjat(kuva: Path) -> tuple[dict, dict]:
    """Palauttaa (exif_nimillä, gps_nimillä). Tyhjät jos EXIF puuttuu."""
    try:
        raaka = Image.open(kuva)._getexif() or {}
    except Exception:
        return {}, {}
    exif = {TAGS.get(t, t): v for t, v in raaka.items()}
    gps = {GPSTAGS.get(t, t): v for t, v in (exif.get("GPSInfo") or {}).items()}
    return exif, gps


def _asteiksi(arvo, ref) -> float:
    d = float(arvo[0]) + float(arvo[1]) / 60 + float(arvo[2]) / 3600
    return -d if ref in ("S", "W") else d


def tunnista_laite(valmistaja: str | None) -> str:
    """'puhelin', 'drone' tai 'jarjestelmakamera' EXIF Make -kentän perusteella."""
    make = (valmistaja or "").strip().lower()
    if not make:
        return "tuntematon"
    if any(d in make for d in _DRONE_MAKE):
        return "drone"
    if any(p in make for p in _PHONE_MAKE):
        return "puhelin"
    return "jarjestelmakamera"


def lue_kuvan_tiedot(kuva: Path) -> dict:
    """
    Lukee kuvasta kaiken tarvittavan yhdellä avauksella.

    Palauttaa dictin: lat, lon, aika, suunta, suunta_ref, korkeus,
    valmistaja, malli, laitetyyppi. Puuttuvat kentät ovat None.
    """
    exif, gps = _exif_sanakirjat(kuva)

    lat = lon = None
    if "GPSLatitude" in gps and "GPSLongitude" in gps:
        try:
            lat = _asteiksi(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
            lon = _asteiksi(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
        except Exception:
            lat = lon = None

    aika = None
    for kentta in ("DateTimeOriginal", "DateTime"):
        arvo = exif.get(kentta)
        if arvo:
            try:
                aika = datetime.datetime.strptime(str(arvo), "%Y:%m:%d %H:%M:%S")
                break
            except ValueError:
                continue

    suunta = None
    if gps.get("GPSImgDirection") is not None:
        try:
            suunta = float(gps["GPSImgDirection"]) % 360
        except Exception:
            suunta = None

    korkeus = None
    if gps.get("GPSAltitude") is not None:
        try:
            korkeus = float(gps["GPSAltitude"])
            if gps.get("GPSAltitudeRef") in (1, b"\x01"):   # merenpinnan alapuolella
                korkeus = -korkeus
        except Exception:
            korkeus = None

    valmistaja = str(exif["Make"]).strip() if exif.get("Make") else None
    malli = str(exif["Model"]).strip() if exif.get("Model") else None

    return {
        "lat": lat,
        "lon": lon,
        "aika": aika,
        "suunta": suunta,
        "suunta_ref": str(gps.get("GPSImgDirectionRef") or "") or None,
        "korkeus": korkeus,
        "valmistaja": valmistaja,
        "malli": malli,
        "laitetyyppi": tunnista_laite(valmistaja),
    }


# ══════════════════════════════════════════════════════════════════
#  EXIF-KIRJOITUS
# ══════════════════════════════════════════════════════════════════

def kirjoita_exif_gps(kuva: Path, lat: float, lon: float) -> bool:
    """
    Kirjoittaa GPS-koordinaatin kuvan EXIF:iin in-place.
    Säilyttää muut GPS-kentät (esim. korkeuden ja suunnan).
    """
    def _rationaali(arvo):
        arvo = abs(arvo)
        d = int(arvo)
        m = int((arvo - d) * 60)
        s = round((arvo - d - m / 60) * 3600 * 10000)
        return ((d, 1), (m, 1), (s, 10000))

    try:
        exif_dict = piexif.load(str(kuva))
        gps = dict(exif_dict.get("GPS") or {})
        gps[piexif.GPSIFD.GPSLatitudeRef] = b"N" if lat >= 0 else b"S"
        gps[piexif.GPSIFD.GPSLatitude] = _rationaali(lat)
        gps[piexif.GPSIFD.GPSLongitudeRef] = b"E" if lon >= 0 else b"W"
        gps[piexif.GPSIFD.GPSLongitude] = _rationaali(lon)
        exif_dict["GPS"] = gps
        piexif.insert(piexif.dump(exif_dict), str(kuva))
        return True
    except Exception as e:
        print(f"    ⚠ EXIF-kirjoitus epäonnistui ({kuva.name}): {e}")
        return False


# ══════════════════════════════════════════════════════════════════
#  GPX-LOKIT
# ══════════════════════════════════════════════════════════════════

def lataa_gpx_pisteet(gpx_polut, hiljaa: bool = False) -> list[tuple]:
    """
    Lukee yhden tai useamman GPX:n → [(naive_datetime_helsinki, lat, lon), ...]
    aikajärjestyksessä. Päällekkäiset aikaleimat karsitaan.

    GPX-ajat muunnetaan Helsingin paikalliseksi ajaksi, jotta vertailu kameran
    EXIF-aikaan (paikallinen, ilman aikavyöhykettä) toimii kesä- ja talviaikana.
    """
    if isinstance(gpx_polut, (str, Path)):
        gpx_polut = [Path(gpx_polut)]

    pisteet: list[tuple] = []
    for gpx_polku in gpx_polut:
        try:
            with open(gpx_polku, encoding="utf-8") as f:
                gpx = gpxpy.parse(f)
        except Exception as e:
            print(f"  ⚠ {Path(gpx_polku).name}: ei voitu lukea ({e}) — ohitetaan")
            continue
        ennen = len(pisteet)
        for track in gpx.tracks:
            for segment in track.segments:
                for p in segment.points:
                    if p.time:
                        if p.time.tzinfo is not None:
                            t = p.time.astimezone(_HELSINKI).replace(tzinfo=None)
                        else:
                            t = p.time.replace(tzinfo=None)
                        pisteet.append((t, p.latitude, p.longitude))
        if not hiljaa:
            print(f"    {Path(gpx_polku).name}: {len(pisteet) - ennen} pistettä")

    pisteet.sort(key=lambda x: x[0])

    uniikit: list[tuple] = []
    for p in pisteet:
        if not uniikit or p[0] != uniikit[-1][0]:
            uniikit.append(p)
    if len(uniikit) < len(pisteet) and not hiljaa:
        print(f"    ({len(pisteet) - len(uniikit)} päällekkäistä aikaleimaa karsittu)")
    return uniikit


def aukot(pisteet: list[tuple], max_aukko_s: float) -> list[tuple]:
    """[(alku, loppu, kesto_min), ...] väleistä jotka ylittävät rajan."""
    tulos = []
    for i in range(len(pisteet) - 1):
        dt = (pisteet[i + 1][0] - pisteet[i][0]).total_seconds()
        if dt > max_aukko_s:
            tulos.append((pisteet[i][0], pisteet[i + 1][0], dt / 60))
    return tulos


def interpoloi(pisteet: list[tuple], aikaleima: datetime.datetime, max_aukko_s: float):
    """
    Lineaarinen interpolointi. Palauttaa ((lat, lon), None) tai (None, syy).
    Yli max_aukko_s pituisen pistevälin yli ei interpoloida.
    """
    if not pisteet:
        return None, "ei GPX-pisteitä"
    if aikaleima < pisteet[0][0] or aikaleima > pisteet[-1][0]:
        return None, "aikaleima GPX-lokien ulkopuolella"
    for i in range(len(pisteet) - 1):
        t0, lat0, lon0 = pisteet[i]
        t1, lat1, lon1 = pisteet[i + 1]
        if t0 <= aikaleima <= t1:
            dt = (t1 - t0).total_seconds()
            if dt > max_aukko_s:
                return None, (f"GPX-aukko {dt / 60:.0f} min "
                              f"({t0:%d.%m. %H:%M}–{t1:%d.%m. %H:%M}) — loggeri pois päältä?")
            f = (aikaleima - t0).total_seconds() / dt if dt else 0
            return (lat0 + f * (lat1 - lat0), lon0 + f * (lon1 - lon0)), None
    return None, "ei sopivaa GPX-väliä"


def kulkusuunta(pisteet: list[tuple], aikaleima: datetime.datetime,
                max_aukko_s: float) -> float | None:
    """
    Kulkusuunta asteina GPX-radalta kuvanottohetkellä.
    HUOM: tämä on liikkumissuunta, EI katselusuunta — käytetään vain jos
    käyttäjä sen erikseen pyytää, ja merkitään lähdekenttään.
    """
    import math
    if len(pisteet) < 2:
        return None
    for i in range(len(pisteet) - 1):
        t0, lat0, lon0 = pisteet[i]
        t1, lat1, lon1 = pisteet[i + 1]
        if t0 <= aikaleima <= t1:
            if (t1 - t0).total_seconds() > max_aukko_s:
                return None
            fi0, fi1 = math.radians(lat0), math.radians(lat1)
            dl = math.radians(lon1 - lon0)
            y = math.sin(dl) * math.cos(fi1)
            x = math.cos(fi0) * math.sin(fi1) - math.sin(fi0) * math.cos(fi1) * math.cos(dl)
            if abs(y) < 1e-12 and abs(x) < 1e-12:
                return None
            return math.degrees(math.atan2(y, x)) % 360
    return None
