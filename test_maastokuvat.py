"""
test_maastokuvat.py
===================
Regressiotesti. Käyttää oikeita JPEG- ja GPX-tiedostoja väliaikaishakemistossa,
ei mockeja. Ajo:  python3 test_maastokuvat.py

Testaa erityisesti GPX-haaran, jota kuvissa joissa on jo EXIF-GPS ei koskaan aja:
kuvan sijainti loggerin lokista, aukkosuoja ja lokien ulkopuolelle jäävä kuva.
"""

import datetime
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import piexif
from PIL import Image

import exif_gpx as eg
import maastokuvat as mk
import qgis_taso as qt

_vaittamia = 0
_virheita = 0


def vaita(ehto, kuvaus):
    global _vaittamia, _virheita
    _vaittamia += 1
    if ehto:
        print(f"  ✓ {kuvaus}")
    else:
        _virheita += 1
        print(f"  ✗ {kuvaus}")


# ══════════════════════════════════════════════════════════════════
#  TESTIAINEISTON LUONTI
# ══════════════════════════════════════════════════════════════════

def _rationaali(arvo):
    arvo = abs(arvo)
    d = int(arvo)
    m = int((arvo - d) * 60)
    s = round((arvo - d - m / 60) * 3600 * 10000)
    return ((d, 1), (m, 1), (s, 10000))


def tee_jpeg(polku: Path, aika: datetime.datetime, lat=None, lon=None,
             suunta=None, korkeus=None, make="Canon", model="EOS R"):
    """Kirjoittaa pienen oikean JPEG:n halutuilla EXIF-kentillä."""
    polku.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 60), (90, 120, 90)).save(polku, "JPEG", quality=70)

    nolla = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    nolla["0th"][piexif.ImageIFD.Make] = make.encode()
    nolla["0th"][piexif.ImageIFD.Model] = model.encode()
    nolla["Exif"][piexif.ExifIFD.DateTimeOriginal] = aika.strftime("%Y:%m:%d %H:%M:%S").encode()
    if lat is not None:
        nolla["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N" if lat >= 0 else b"S"
        nolla["GPS"][piexif.GPSIFD.GPSLatitude] = _rationaali(lat)
        nolla["GPS"][piexif.GPSIFD.GPSLongitudeRef] = b"E" if lon >= 0 else b"W"
        nolla["GPS"][piexif.GPSIFD.GPSLongitude] = _rationaali(lon)
    if suunta is not None:
        nolla["GPS"][piexif.GPSIFD.GPSImgDirection] = (int(suunta * 100), 100)
        nolla["GPS"][piexif.GPSIFD.GPSImgDirectionRef] = b"T"
    if korkeus is not None:
        nolla["GPS"][piexif.GPSIFD.GPSAltitude] = (int(korkeus * 10), 10)
        nolla["GPS"][piexif.GPSIFD.GPSAltitudeRef] = 0
    piexif.insert(piexif.dump(nolla), str(polku))


def tee_gpx(polku: Path, jaksot: list[tuple[datetime.datetime, int, float, float]]):
    """
    Kirjoittaa GPX:n. Jokainen jakso: (alkuaika, pisteita, alku_lat, alku_lon);
    pisteet 60 s välein, 0,0002° askel pohjoiseen.

    Ajat ANNETAAN Suomen paikallisena aikana (kuten kameran kello näyttää),
    mutta kirjoitetaan tiedostoon UTC:nä 'Z'-päätteellä, koska oikeat
    GPS-loggerit tekevät niin. Näin testi kattaa myös aikavyöhykemuunnoksen.
    """
    rivit = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="test"><trk><trkseg>']
    for alku, maara, lat0, lon0 in jaksot:
        for i in range(maara):
            paikallinen = alku + datetime.timedelta(seconds=60 * i)
            utc = (paikallinen.replace(tzinfo=eg._HELSINKI)
                   .astimezone(datetime.timezone.utc))
            rivit.append(f'<trkpt lat="{lat0 + 0.0002 * i:.6f}" lon="{lon0:.6f}">'
                         f'<time>{utc.strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>')
    rivit.append("</trkseg></trk></gpx>")
    polku.parent.mkdir(parents=True, exist_ok=True)
    polku.write_text("\n".join(rivit), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════
#  TESTIT
# ══════════════════════════════════════════════════════════════════

def testaa_exif_luku(tmp: Path):
    print("\n[1] EXIF-luku")
    kuva = tmp / "exif" / "a.jpg"
    tee_jpeg(kuva, datetime.datetime(2026, 7, 20, 12, 30, 0),
             lat=62.5, lon=28.5, suunta=137.5, korkeus=118.4,
             make="samsung", model="SM-G991B")
    t = eg.lue_kuvan_tiedot(kuva)
    vaita(abs(t["lat"] - 62.5) < 1e-4, f"latitudi luetaan ({t['lat']})")
    vaita(abs(t["lon"] - 28.5) < 1e-4, f"longitudi luetaan ({t['lon']})")
    vaita(t["aika"] == datetime.datetime(2026, 7, 20, 12, 30), "kuvausaika luetaan")
    vaita(abs(t["suunta"] - 137.5) < 0.01, f"kuvaussuunta luetaan ({t['suunta']})")
    vaita(abs(t["korkeus"] - 118.4) < 0.05, f"korkeus luetaan ({t['korkeus']})")
    vaita(t["laitetyyppi"] == "puhelin", f"Samsung → puhelin ({t['laitetyyppi']})")

    tyhja = tmp / "exif" / "b.jpg"
    tee_jpeg(tyhja, datetime.datetime(2026, 7, 20, 13, 0, 0))
    t2 = eg.lue_kuvan_tiedot(tyhja)
    vaita(t2["lat"] is None, "GPS:n puuttuminen tunnistetaan")
    vaita(t2["suunta"] is None, "suunnan puuttuminen tunnistetaan")
    vaita(t2["laitetyyppi"] == "jarjestelmakamera", "Canon → järjestelmäkamera")


def testaa_gpx_ja_aukot(tmp: Path):
    print("\n[2] GPX-interpolointi ja aukkosuoja")
    gpx = tmp / "gpx" / "loki.gpx"
    # Kaksi jaksoa: 10:00–10:09 ja 14:00–14:09 → välissä ~4 h aukko
    tee_gpx(gpx, [(datetime.datetime(2026, 7, 20, 10, 0), 10, 62.40, 28.40),
                  (datetime.datetime(2026, 7, 20, 14, 0), 10, 62.60, 28.60)])
    pisteet = eg.lataa_gpx_pisteet([gpx], hiljaa=True)
    vaita(len(pisteet) == 20, f"20 pistettä luettu ({len(pisteet)})")

    aukot = eg.aukot(pisteet, 10 * 60)
    vaita(len(aukot) == 1 and 230 < aukot[0][2] < 240, f"yksi ~231 min aukko havaittu ({aukot})")

    koord, syy = eg.interpoloi(pisteet, datetime.datetime(2026, 7, 20, 10, 4, 30), 600)
    vaita(koord is not None and abs(koord[0] - 62.4009) < 0.0002,
          f"jakson sisällä interpoloidaan ({koord})")

    koord2, syy2 = eg.interpoloi(pisteet, datetime.datetime(2026, 7, 20, 12, 0), 600)
    vaita(koord2 is None and "aukko" in (syy2 or ""), f"aukon yli EI interpoloida ({syy2})")

    koord3, syy3 = eg.interpoloi(pisteet, datetime.datetime(2026, 7, 20, 8, 0), 600)
    vaita(koord3 is None and "ulkopuolella" in (syy3 or ""),
          f"lokien ulkopuolelta ei arvata ({syy3})")

    suunta = eg.kulkusuunta(pisteet, datetime.datetime(2026, 7, 20, 10, 4, 30), 600)
    vaita(suunta is not None and abs(suunta) < 1, f"kulkusuunta pohjoiseen ≈ 0° ({suunta})")


def testaa_paallekkaiset_lokit(tmp: Path):
    print("\n[3] Monta GPX-lokia, päällekkäiset aikaleimat")
    a = tmp / "gpx2" / "a.gpx"
    b = tmp / "gpx2" / "b.gpx"
    tee_gpx(a, [(datetime.datetime(2026, 7, 20, 10, 0), 5, 62.40, 28.40)])
    tee_gpx(b, [(datetime.datetime(2026, 7, 20, 10, 3), 5, 62.40, 28.40)])
    pisteet = eg.lataa_gpx_pisteet([a, b], hiljaa=True)
    vaita(len(pisteet) == 8, f"5+5 pistettä, 2 päällekkäistä karsittu → 8 ({len(pisteet)})")
    vaita(all(pisteet[i][0] < pisteet[i + 1][0] for i in range(len(pisteet) - 1)),
          "pisteet aikajärjestyksessä")


def testaa_ajo_gpx_haaralla(tmp: Path):
    print("\n[4] Koko ajo: kuvat ilman GPS:ää + GPX-loki")
    mk.PROJEKTIT_POLKU = tmp / "projektit"
    kuvakansio = tmp / "kenttakuvat"
    gpx = tmp / "ajo" / "loki.gpx"
    tee_gpx(gpx, [(datetime.datetime(2026, 7, 20, 10, 0), 20, 62.40, 28.40),
                  (datetime.datetime(2026, 7, 20, 16, 0), 20, 62.60, 28.60)])

    # 1) lokin sisällä, ei GPS:ää → GPX
    tee_jpeg(kuvakansio / "kentta1.jpg", datetime.datetime(2026, 7, 20, 10, 5))
    # 2) lokin sisällä, oma GPS → EXIF voittaa
    tee_jpeg(kuvakansio / "kentta2.jpg", datetime.datetime(2026, 7, 20, 10, 6),
             lat=61.0, lon=25.0, make="samsung")
    # 3) aukossa (klo 13) → ei sijoiteta
    tee_jpeg(kuvakansio / "aukko.jpg", datetime.datetime(2026, 7, 20, 13, 0))
    # 4) lokien ulkopuolella → ei sijoiteta
    tee_jpeg(kuvakansio / "ulkopuolella.jpg", datetime.datetime(2026, 7, 19, 9, 0))
    # 5) suunta EXIF:issä → nuolisymbolin sääntö osuu
    tee_jpeg(kuvakansio / "suunnalla.jpg", datetime.datetime(2026, 7, 20, 10, 7),
             lat=62.45, lon=28.45, suunta=270.0)

    t = mk.aja("testi", [kuvakansio], [gpx], aikaero_min=0, max_aukko_min=10,
               kirjoita_exif=True)

    vaita(t["tuotu"] == 3, f"3 kuvaa tuotu ({t['tuotu']})")
    vaita(t["gpx"] == 1, f"1 kuva sijoitettu GPX:stä ({t['gpx']})")
    vaita(t["exif"] == 2, f"2 kuvaa sijoitettu EXIF:stä ({t['exif']})")
    syyt = dict(t["ei_sijaintia"])
    vaita(len(syyt) == 2, f"2 kuvaa jäi ilman sijaintia ({list(syyt)})")
    vaita("aukko" in syyt.get("aukko.jpg", ""), f"aukkokuva hylätty oikeasta syystä ({syyt.get('aukko.jpg')})")
    vaita("ulkopuolella" in syyt.get("ulkopuolella.jpg", ""),
          f"lokin ulkopuolinen hylätty ({syyt.get('ulkopuolella.jpg')})")

    projektikansio = mk.PROJEKTIT_POLKU / "testi"
    vaita((projektikansio / "ei_sijaintia.txt").is_file(), "ei_sijaintia.txt kirjoitettu")
    vaita((projektikansio / "esikatselu" / "kentta1.jpg").is_file(), "esikatselukuva tehty")

    # GPX:stä saatu koordinaatti kirjoitettiin kopion EXIF:iin
    kopio = eg.lue_kuvan_tiedot(projektikansio / "kuvat" / "kentta1.jpg")
    vaita(kopio["lat"] is not None and abs(kopio["lat"] - 62.401) < 0.001,
          f"GPX-koordinaatti kirjoitettu kopion EXIF:iin ({kopio['lat']})")
    alkuperainen = eg.lue_kuvan_tiedot(kuvakansio / "kentta1.jpg")
    vaita(alkuperainen["lat"] is None, "lähdekuvaan EI kirjoitettu (vain kopioon)")

    # EXIF voittaa GPX:n kun molemmat ovat tarjolla
    k2 = eg.lue_kuvan_tiedot(projektikansio / "kuvat" / "kentta2.jpg")
    vaita(abs(k2["lat"] - 61.0) < 0.01, f"oma EXIF-GPS säilyi ({k2['lat']})")

    return projektikansio


def testaa_gpkg_ja_tyyli(projektikansio: Path):
    print("\n[5] GeoPackage ja tyyli — kuten raahattaisiin QGIS:iin")
    from qgis.core import QgsVectorLayer
    gpkg = projektikansio / "maastokuvat.gpkg"
    vaita(gpkg.is_file(), "maastokuvat.gpkg kirjoitettu")
    vaita((projektikansio / "maastokuvat.qml").is_file(), "maastokuvat.qml kirjoitettu")

    taso = QgsVectorLayer(f"{gpkg}|layername={qt.TASON_NIMI}", "t", "ogr")
    vaita(taso.isValid(), "taso latautuu")
    vaita(taso.featureCount() == 3, f"3 kuvapistettä ({taso.featureCount()})")
    vaita(taso.crs().authid() == "EPSG:3067", f"CRS on EPSG:3067 ({taso.crs().authid()})")

    vaita(len(taso.mapTipTemplate() or "") > 100, "map tip tulee tason mukana")
    vaita("<img" in (taso.mapTipTemplate() or ""), "map tipissä on kuva")

    r = taso.renderer()
    saannot = [s.filterExpression() for s in r.rootRule().children()] if hasattr(r, "rootRule") else []
    vaita('"suunta" IS NOT NULL' in saannot, f"nuolisääntö suunnalle löytyy ({saannot})")

    i = taso.fields().indexOf("polku")
    ws = taso.editorWidgetSetup(i)
    vaita(ws.type() == "ExternalResource", f"polku-kentässä liite-widget ({ws.type()})")
    vaita(int(ws.config().get("DocumentViewer", 0)) == 1, "liite näytetään kuvana")

    nimet = [a.name() for a in taso.actions().actions()]
    vaita("Avaa kuva" in nimet, f"toiminto 'Avaa kuva' löytyy ({nimet})")

    oletus = taso.actions().defaultAction("Feature")
    vaita(oletus.isValid() and oletus.name() == "Avaa kuva",
          f"'Avaa kuva' on oletustoiminto ({oletus.name() if oletus.isValid() else 'ei asetettu'})")
    vaita(f'width="{qt.MAP_TIP_LEVEYS}"' in (taso.mapTipTemplate() or ""),
          f"map tipin kuvaleveys on {qt.MAP_TIP_LEVEYS} px")
    vaita(int(ws.config().get("DocumentViewerHeight", 0)) == qt.LOMAKE_KUVA_KORKEUS,
          f"lomakkeen kuvakorkeus on {qt.LOMAKE_KUVA_KORKEUS} px")

    suunnat = sorted(f["suunta"] for f in taso.getFeatures()
                     if f["suunta"] not in (None, ""))
    vaita(len(suunnat) == 1 and abs(float(suunnat[0]) - 270) < 0.01,
          f"yhdellä kuvalla suunta 270° ({suunnat})")
    del taso


def testaa_duplikaatit_ja_kasin_muokkaus(tmp: Path, projektikansio: Path):
    print("\n[6] Duplikaattisuoja ja käsin täytetyn arvon säilyminen")
    from qgis.core import QgsVectorLayer
    gpkg = projektikansio / "maastokuvat.gpkg"

    # Simuloi käyttäjän käsin täyttämää suuntaa QGIS:ssä
    taso = QgsVectorLayer(f"{gpkg}|layername={qt.TASON_NIMI}", "t", "ogr")
    taso.startEditing()
    for f in taso.getFeatures():
        if f["tiedosto"] == "kentta1.jpg":
            taso.changeAttributeValue(f.id(), taso.fields().indexOf("suunta"), 42.0)
            taso.changeAttributeValue(f.id(), taso.fields().indexOf("huomio"), "käsin lisätty")
    taso.commitChanges()
    del taso

    kuvakansio = tmp / "kenttakuvat"
    gpx = tmp / "ajo" / "loki.gpx"
    t2 = mk.aja("testi", [kuvakansio], [gpx], kirjoita_exif=True)
    vaita(t2["tuotu"] == 0, f"toinen ajo ei tuo mitään uudelleen ({t2['tuotu']})")
    vaita(t2["duplikaatti"] == 3, f"3 kuvaa ohitettu duplikaattina ({t2['duplikaatti']})")
    vaita(t2["kohteita"] == 3, f"taso rakennettiin silti uudelleen, 3 pistettä ({t2['kohteita']})")

    taso2 = QgsVectorLayer(f"{gpkg}|layername={qt.TASON_NIMI}", "t", "ogr")
    arvot = {f["tiedosto"]: (f["suunta"], f["huomio"]) for f in taso2.getFeatures()}
    suunta, huomio = arvot.get("kentta1.jpg", (None, None))
    vaita(suunta is not None and abs(float(suunta) - 42.0) < 0.01,
          f"käsin täytetty suunta säilyi uudelleenkirjoituksessa ({suunta})")
    vaita(huomio == "käsin lisätty", f"käsin täytetty huomio säilyi ({huomio})")
    del taso2

    # Kohdetiedoston poisto käsin → kuva tuodaan uudelleen
    (projektikansio / "kuvat" / "kentta1.jpg").unlink()
    t3 = mk.aja("testi", [kuvakansio], [gpx], kirjoita_exif=True)
    vaita(t3["tuotu"] == 1, f"poistettu kuva tuodaan uudelleen ({t3['tuotu']})")


def testaa_esikatselun_uusiminen(projektikansio: Path):
    print("\n[7] Esikatselukuvan uusiminen kun tavoitekoko kasvaa")
    from PIL import Image
    esik = projektikansio / "esikatselu" / "kentta1.jpg"
    vaita(esik.is_file(), "esikatselu on olemassa")

    # Testikuvat ovat 80x60, joten tavoite rajautuu lähdekuvan kokoon
    vanha = mk.ESIKATSELU_PX
    try:
        Image.new("RGB", (40, 30), (10, 10, 10)).save(esik, "JPEG")   # liian pieni
        tehty = mk.varmista_esikatselut(projektikansio)
        vaita(tehty >= 1, f"liian pieni esikatselu uusittiin ({tehty})")
        with Image.open(esik) as e:
            vaita(max(e.size) == 80, f"uusittu esikatselu lähdekuvan kokoinen ({e.size})")

        tehty2 = mk.varmista_esikatselut(projektikansio)
        vaita(tehty2 == 0, f"riittävän isoja ei uusita turhaan ({tehty2})")
    finally:
        mk.ESIKATSELU_PX = vanha


def main():
    print("=" * 62)
    print("  maastokuvat — regressiotesti")
    print("=" * 62)
    tmp = Path(tempfile.mkdtemp(prefix="maastokuvat_testi_"))
    vanha_polku = mk.PROJEKTIT_POLKU
    try:
        with qt.qgis_kaynnissa():
            from qgis.gui import QgsGui
            QgsGui.editorWidgetRegistry().initEditors()
            testaa_exif_luku(tmp)
            testaa_gpx_ja_aukot(tmp)
            testaa_paallekkaiset_lokit(tmp)
            projektikansio = testaa_ajo_gpx_haaralla(tmp)
            testaa_gpkg_ja_tyyli(projektikansio)
            testaa_duplikaatit_ja_kasin_muokkaus(tmp, projektikansio)
            testaa_esikatselun_uusiminen(projektikansio)
    finally:
        mk.PROJEKTIT_POLKU = vanha_polku
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 62)
    print(f"  {_vaittamia - _virheita}/{_vaittamia} väittämää läpi")
    print("=" * 62)
    return 1 if _virheita else 0


if __name__ == "__main__":
    sys.exit(main())
