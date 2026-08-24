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

def osuvat_saannot(taso, piirre) -> list:
    """
    Ne renderöijän säännöt joiden suodatin osuu tähän kohteeseen.

    Sääntöpohjainen renderöijä jättää kohteen piirtämättä jos yksikään sääntö ei
    osu, joten oikea vastaus on aina täsmälleen yksi.
    """
    from qgis.core import (QgsExpression, QgsExpressionContext,
                           QgsExpressionContextUtils)
    ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(taso))
    ctx.setFeature(piirre)
    osuvat = []
    for saanto in taso.renderer().rootRule().children():
        lauseke = QgsExpression(saanto.filterExpression())
        lauseke.prepare(ctx)
        if lauseke.evaluate(ctx):
            osuvat.append(saanto)
    return osuvat


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

    # github=False: testi ei koske oikeaan git-repoon
    t = mk.aja("testi", [kuvakansio], [gpx], aikaero_min=0, max_aukko_min=10,
               kirjoita_exif=True, github=False)

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
    vaita(len(saannot) == 4, f"neljä symbolisääntöä (laite × suunta) ({len(saannot)})")
    vaita(any('"suunta" IS NOT NULL' in s for s in saannot),
          f"nuolisääntö suunnalle löytyy ({saannot})")
    vaita(sum("= 'drone'" in s for s in saannot) == 2,
          f"dronelle omat säännöt suunnalla ja ilman ({saannot})")
    vaita(all(len(osuvat_saannot(taso, f)) == 1 for f in taso.getFeatures()),
          "jokainen kohde osuu täsmälleen yhteen sääntöön (ei piirtämättä jääviä)")

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
    t2 = mk.aja("testi", [kuvakansio], [gpx], kirjoita_exif=True, github=False)
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
    t3 = mk.aja("testi", [kuvakansio], [gpx], kirjoita_exif=True, github=False)
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


def testaa_github_osoitteet(tmp: Path):
    print("\n[8] GitHub-osoitteet ja paikallinen/verkko-varajärjestys")
    pohja = mk.raw_url_pohja("hein ita", "kuvat")
    vaita(pohja.startswith(f"https://raw.githubusercontent.com/{mk.GITHUB_USER}/"
                           f"{mk.GITHUB_REPO}/{mk.GITHUB_BRANCH}/"),
          f"raw-osoitteen runko oikein ({pohja})")
    vaita("hein%20ita" in pohja, f"projektinimen väli koodataan ({pohja})")

    projektikansio = mk.PROJEKTIT_POLKU / "testi"
    kohteet, _ = mk.kokoa_kohteet(projektikansio, [], 0, 10,
                                  mk.raw_url_pohja("testi", "kuvat"),
                                  mk.raw_url_pohja("testi", "esikatselu"))
    vaita(kohteet and all(k["url"].endswith(k["tiedosto"]) for k in kohteet),
          "jokaiselle kuvalle täysikokoisen url")
    vaita(all(k["url_esikatselu"].endswith(k["tiedosto"]) for k in kohteet),
          "jokaiselle kuvalle esikatselun url")

    # Ilman github-lippua kentät jäävät tyhjiksi
    ilman, _ = mk.kokoa_kohteet(projektikansio, [], 0, 10, "", "")
    vaita(all(k["url"] == "" and k["url_esikatselu"] == "" for k in ilman),
          "ilman GitHub-vientiä url-kentät ovat tyhjiä")

    # Lauseke: paikallinen ensin, verkko vasta jos tiedostoa ei ole
    lauseke = qt._kuvalauseke("esikatselu", "url_esikatselu")
    vaita("file_exists(" in lauseke, "lauseke tarkistaa paikallisen tiedoston olemassaolon")
    vaita(lauseke.index("file_exists(") < lauseke.index('"url_esikatselu"'),
          "paikallinen tiedosto on ennen verkko-osoitetta")

    from qgis.core import (QgsVectorLayer, QgsExpression, QgsExpressionContext,
                           QgsExpressionContextUtils)
    import re as _re
    gpkg = projektikansio / "maastokuvat.gpkg"
    taso = QgsVectorLayer(f"{gpkg}|layername={qt.TASON_NIMI}", "t", "ogr")
    ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(taso))
    ctx.setFeature(next(taso.getFeatures()))
    e = QgsExpression(_re.search(r'src="\[%(.*?)%\]"', taso.mapTipTemplate(), _re.S).group(1))
    e.prepare(ctx)
    tulos = str(e.evaluate(ctx))
    vaita(tulos.startswith("file://") and not e.hasEvalError(),
          f"kun kuva on levyllä, käytetään paikallista ({tulos[:40]}…)")
    del taso


def testaa_projektikohtainen_repo(tmp: Path):
    print("\n[9] Projektikohtainen repo (kun yksi repo täyttyy)")
    import json as _json
    projektikansio = mk.PROJEKTIT_POLKU / "testi"
    conf = projektikansio / mk.PROJEKTI_TIEDOSTO

    # 1) Ilman projekti.json → työkopion origin (tai vakiot), ei ristiriitaa
    conf.unlink(missing_ok=True)
    kohde, eri = mk.ratkaise_kohde(projektikansio)
    odotettu = mk.git_remote_tiedot() or {"user": mk.GITHUB_USER, "repo": mk.GITHUB_REPO,
                                          "branch": mk.GITHUB_BRANCH}
    vaita(kohde == odotettu, f"uusi projekti käyttää työkopion remotea ({kohde})")
    vaita(eri is False, "uudella projektilla ei ristiriitaa")

    # 2) Projekti naulattu VANHAAN repoon → osoitteet pysyvät siinä
    conf.write_text(_json.dumps({"github": {"user": "MarkusHytonenPD",
                                            "repo": "maastokuvat-vanha",
                                            "branch": "main"}}), encoding="utf-8")
    kohde2, eri2 = mk.ratkaise_kohde(projektikansio)
    vaita(kohde2["repo"] == "maastokuvat-vanha", f"naulattu repo säilyy ({kohde2['repo']})")
    vaita(eri2 is True, "ristiriita työkopion repoon havaitaan")
    vaita("maastokuvat-vanha" in mk.raw_url_pohja("testi", "kuvat", kohde2),
          "osoite osoittaa naulattuun repoon")

    # 3) Koko ajo naulatulla repolla: osoitteet vanhaan repoon, EI pushia
    t = mk.aja("testi", [tmp / "kenttakuvat"], [], github=True)
    vaita(t.get("pushattu") is False, "vieraaseen repoon kuuluvaa projektia ei pushata")

    from qgis.core import QgsVectorLayer
    taso = QgsVectorLayer(
        f"{projektikansio / 'maastokuvat.gpkg'}|layername={qt.TASON_NIMI}", "t", "ogr")
    urlit = [f["url"] for f in taso.getFeatures()]
    vaita(urlit and all("maastokuvat-vanha" in u for u in urlit),
          "tason osoitteet jäivät vanhaan repoon")
    del taso

    # 4) Naulaus poistettu → uusi kohde otetaan käyttöön
    conf.unlink()
    kohde4, eri4 = mk.ratkaise_kohde(projektikansio)
    vaita(kohde4 == odotettu and eri4 is False,
          "naulauksen poisto vapauttaa projektin nykyiseen repoon")

    # 5) "Ei viedä nyt" (github=False) ei saa tyhjentää jo vietyjä osoitteita
    mk.kirjoita_projekticonfig(projektikansio, odotettu)
    mk.aja("testi", [tmp / "kenttakuvat"], [], github=False)
    taso5 = QgsVectorLayer(
        f"{projektikansio / 'maastokuvat.gpkg'}|layername={qt.TASON_NIMI}", "t", "ogr")
    urlit5 = [f["url"] for f in taso5.getFeatures()]
    vaita(urlit5 and all(u for u in urlit5),
          f"github=False säilyttää jo vietyjen kuvien osoitteet ({len(urlit5)} kpl)")
    del taso5

    # 6) Projekti jota ei ole koskaan viety → osoitteet pysyvät tyhjinä
    conf.unlink()
    mk.aja("testi", [tmp / "kenttakuvat"], [], github=False)
    taso6 = QgsVectorLayer(
        f"{projektikansio / 'maastokuvat.gpkg'}|layername={qt.TASON_NIMI}", "t", "ogr")
    vaita(all(not f["url"] for f in taso6.getFeatures()),
          "viemättömällä projektilla ei turhia osoitteita")
    del taso6


def testaa_google_lahde(tmp: Path):
    """
    Google Photos -lähde ilman verkkoyhteyttä: albumin haku ja EXIF-luku
    korvataan paikallisilla testikuvilla. Verkkoa vasten ajettava tarkistus on
    erikseen (ks. README, kohta "Google Photos -albumi lähteenä").
    """
    print("\n[10] Google Photos -lähde (verkko korvattu paikallisilla kuvilla)")
    import google_photos as gp

    vaita(gp.on_jakolinkki("https://photos.app.goo.gl/abc123"),
          "photos.app.goo.gl tunnistetaan jakolinkiksi")
    vaita(gp.on_jakolinkki("https://photos.google.com/share/AF1Qip?key=x"),
          "photos.google.com/share tunnistetaan")
    vaita(not gp.on_jakolinkki("/home/markus/kuvat"),
          "paikallista polkua ei tunnisteta jakolinkiksi")
    vaita(not gp.on_jakolinkki("https://drive.google.com/kansio"),
          "muu Google-osoite ei kelpaa jakolinkiksi")

    # Sivun datalohkon jäsennys: järjestys säilyy, duplikaatit karsitaan
    html = ('roskaa ["AF1QipEnsimmainenTunnus01",'
            '["https://lh3.googleusercontent.com/pw/AAA111",4032,1816,null] roskaa'
            ' ["AF1QipEnsimmainenTunnus01",'
            '["https://lh3.googleusercontent.com/pw/AAA111",4032,1816,null]'
            ' ["AF1QipToinenTunnus000002",'
            '["https://lh3.googleusercontent.com/pw/BBB222",1080,1920,null]')
    mediat = gp._jasenna_media(html)
    vaita(len(mediat) == 2, f"kaksi kuvaa jäsennetty, duplikaatti karsittu ({len(mediat)})")
    vaita(mediat[0]["url"].endswith("AAA111") and mediat[1]["leveys"] == 1080,
          "url ja mitat luetaan oikein, järjestys säilyy")
    vaita(gp._jasenna_media("ei mitään") == [], "tyhjä sivu → ei kuvia")

    nimi = gp._tiedostonimi('attachment;filename="20260814_162728.jpg"', "AF1QipX")
    vaita(nimi == "20260814_162728.jpg", f"tiedostonimi Content-Dispositionista ({nimi})")
    vaita(gp._tiedostonimi(None, "AF1QipTunnus").endswith(".jpg"),
          "ilman otsikkoa nimi johdetaan media-id:stä")

    # Ohimenevä 5xx yritetään uudelleen (Google palautti 500:n 1/300 kuvasta),
    # 404 ei parane odottamalla → ei turhia uusintoja.
    import io as _io
    import urllib.error
    import urllib.request

    class _Vastaus(_io.BytesIO):
        headers = {"Content-Type": "image/jpeg",
                   "Content-Disposition": 'attachment;filename="x.jpg"'}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    kutsut = []

    def _urlopen(pyynto, timeout=None):
        kutsut.append(pyynto.full_url)
        if len(kutsut) < 3:
            raise urllib.error.HTTPError(pyynto.full_url, 500, "Server Error", None, None)
        return _Vastaus(b"\xff\xd8\xff\xd9")

    oikea_urlopen, oikea_odotus = urllib.request.urlopen, gp.ODOTUS
    urllib.request.urlopen, gp.ODOTUS = _urlopen, 0
    try:
        data, _otsikko, virhe = gp._lataa_alku("https://lh3.example/x=d", 1024)
        vaita(not virhe and data and len(kutsut) == 3,
              f"kaksi 500:aa ja kolmas onnistuu ({len(kutsut)} yritystä, virhe={virhe!r})")

        kutsut.clear()

        def _urlopen_404(pyynto, timeout=None):
            kutsut.append(pyynto.full_url)
            raise urllib.error.HTTPError(pyynto.full_url, 404, "Not Found", None, None)

        urllib.request.urlopen = _urlopen_404
        _d, _o, virhe404 = gp._lataa_alku("https://lh3.example/y=d", 1024)
        vaita("404" in virhe404 and len(kutsut) == 1,
              f"404 ei aiheuta uusintoja ({len(kutsut)} yritys, {virhe404})")
    finally:
        urllib.request.urlopen, gp.ODOTUS = oikea_urlopen, oikea_odotus

    varatut = set()
    a = mk._vapaa_nimi_joukosta(varatut, "kuva.jpg")
    b = mk._vapaa_nimi_joukosta(varatut, "kuva.jpg")
    vaita((a, b) == ("kuva.jpg", "kuva_2.jpg"), f"samanniminen kuva saa uuden nimen ({a}, {b})")

    # ── Testialbumi: puhelin, puhelin+suunta, järjestelmäkamera ilman
    #    GPS:ää ja drone — laitetyypin pitää selvitä myös verkon kautta ──
    kansio = tmp / "google_kuvat"
    tee_jpeg(kansio / "g1.jpg", datetime.datetime(2026, 7, 20, 10, 5),
             lat=62.41, lon=28.41, make="samsung", model="SM-G991B")
    tee_jpeg(kansio / "g2.jpg", datetime.datetime(2026, 7, 20, 10, 6),
             lat=62.42, lon=28.42, suunta=180.0, make="samsung")
    tee_jpeg(kansio / "g3.jpg", datetime.datetime(2026, 7, 20, 10, 7),
             make="Canon", model="EOS R")                       # ei GPS:ää
    tee_jpeg(kansio / "g4.jpg", datetime.datetime(2026, 7, 20, 10, 8),
             lat=62.43, lon=28.43, suunta=95.0, korkeus=87.5,
             make="DJI", model="FC3411")                        # drone

    albumi = [{"tunnus": f"AF1QipTestiTunnus{i:06d}",
               "url": f"https://lh3.googleusercontent.com/pw/TESTI{i}",
               "leveys": 80, "korkeus": 60} for i in range(1, 5)]
    tiedostot = {albumi[i]["tunnus"]: kansio / f"g{i + 1}.jpg" for i in range(4)}
    lataukset = []

    def _mock_exif(media, tavuja=gp.EXIF_TAVUJA):
        lataukset.append(media["tunnus"])
        polku = tiedostot[media["tunnus"]]
        tiedot = eg.lue_kuvan_tiedot(polku)
        tiedot["tiedosto"] = polku.name
        return tiedot, ""

    oikea_haku, oikea_exif = gp.hae_albumi, gp.lue_exif
    gp.hae_albumi, gp.lue_exif = (lambda linkki: list(albumi)), _mock_exif
    LINKKI = "https://photos.app.goo.gl/testialbumi"
    try:
        t = mk.aja("google", [], [], google_albumi=LINKKI)

        vaita(t["albumissa"] == 4, f"albumin kuvamäärä raportoidaan ({t.get('albumissa')})")
        vaita(t["verkosta"] == 4, f"neljän kuvan EXIF luettu 'verkosta' ({t['verkosta']})")
        vaita(t["tuotu"] == 3 and t["exif"] == 3,
              f"kolme GPS-kuvaa sijoitettu ({t['tuotu']})")
        vaita(t["ei_sijaintia"] and t["ei_sijaintia"][0][0] == "g3.jpg",
              f"GPS:tön kuva jäi sijoittamatta ({t['ei_sijaintia']})")
        vaita("pushattu" not in t, "Google-lähteellä ei yritetä GitHub-vientiä")

        projektikansio = mk.PROJEKTIT_POLKU / "google"
        vaita(not (projektikansio / "kuvat").exists(),
              "kuvia EI kopioitu levylle (kuvat-kansiota ei synny)")
        vaita(not (projektikansio / "esikatselu").exists(),
              "esikatselukuvia ei tehty")
        vaita(mk.lue_google_albumi(projektikansio) == LINKKI,
              "albumin linkki kirjattiin projekti.jsoniin")

        # Toinen ajo: kirjanpito estää uudet EXIF-latauket
        lataukset.clear()
        t2 = mk.aja("google", [], [], google_albumi=LINKKI)
        vaita(not lataukset, f"uudelleenajo ei lataa EXIF:iä uudelleen ({lataukset})")
        vaita(t2["kirjanpidosta"] == 4 and t2["verkosta"] == 0,
              f"kaikki neljä kirjanpidosta ({t2['kirjanpidosta']})")
        vaita(t2["kirjoitettu"] is False, "muuttumatonta tasoa ei kirjoiteta uudelleen")

        # Taso: osoitteet Googleen, ei paikallisia polkuja
        from qgis.core import (QgsExpression, QgsExpressionContext,
                               QgsExpressionContextUtils, QgsVectorLayer)
        gpkg = projektikansio / "maastokuvat.gpkg"
        taso = QgsVectorLayer(f"{gpkg}|layername={qt.TASON_NIMI}", "t", "ogr")
        piirteet = list(taso.getFeatures())
        vaita(len(piirteet) == 3, f"tasolla kolme kuvapistettä ({len(piirteet)})")

        # Laitetyyppi erottelee dronen ja järjestelmäkameran myös verkon kautta:
        # EXIF Make luetaan samasta 128 kt:n alusta kuin koordinaatti.
        tyypit = {f["tiedosto"]: (f["laitetyyppi"], f["laite"], f["korkeus"])
                  for f in piirteet}
        vaita(tyypit.get("g1.jpg", (None,))[0] == "puhelin",
              f"Samsung → puhelin ({tyypit.get('g1.jpg')})")
        vaita(tyypit.get("g4.jpg", (None,))[0] == "drone",
              f"DJI → drone ({tyypit.get('g4.jpg')})")
        vaita(tyypit.get("g4.jpg", (None, None, None))[1] == "DJI FC3411",
              f"dronen kamera tallentuu ({tyypit.get('g4.jpg')})")
        korkeus = tyypit.get("g4.jpg", (None, None, None))[2]
        vaita(korkeus is not None and abs(float(korkeus) - 87.5) < 0.1,
              f"dronen lentokorkeus luetaan EXIF:istä ({korkeus})")

        # Dronelle piirtyy oma symboli: sininen, ja puhelinkuvalle oranssi
        for tiedosto, odotettu_vari in (("g4.jpg", qt.VARI_DRONE),
                                        ("g1.jpg", qt.VARI_MAASTA)):
            piirre = next(f for f in piirteet if f["tiedosto"] == tiedosto)
            osuvat = osuvat_saannot(taso, piirre)
            vari = osuvat[0].symbol().color().name() if len(osuvat) == 1 else "?"
            vaita(len(osuvat) == 1 and vari.lower() == odotettu_vari.lower(),
                  f"{tiedosto} → {osuvat[0].label() if osuvat else 'ei sääntöä'} ({vari})")

        vaita(all(f["url"].endswith(gp.ALKUPERAINEN) for f in piirteet),
              "täysikokoisen osoite päättyy =d (EXIF mukana)")
        vaita(all(f["url_esikatselu"].endswith(gp.ESIKATSELU) for f in piirteet),
              "esikatselun osoite päättyy =w1200")
        vaita(all(not f["polku"] and not f["esikatselu"] for f in piirteet),
              "polku- ja esikatselu-kentät ovat tyhjiä")
        vaita(all(f["laite"] and f["lahde"] == "exif" for f in piirteet),
              "laite ja koordinaatin lähde tallentuvat")

        ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(taso))
        ctx.setFeature(piirteet[0])
        import re as _re
        for nimi_, lauseke in (("map tip", _re.search(r'src="\[%(.*?)%\]"',
                                                      taso.mapTipTemplate(), _re.S).group(1)),
                               ("Avaa kuva", qt._kuvalauseke("polku", "url"))):
            e = QgsExpression(lauseke)
            e.prepare(ctx)
            tulos = str(e.evaluate(ctx))
            vaita(tulos.startswith("https://lh3.googleusercontent.com/") and not e.hasEvalError(),
                  f"{nimi_} osoittaa Googleen kun kuvaa ei ole levyllä ({tulos[:46]}…)")
        del taso

        # GPX-haara toimii myös Google-lähteellä: g3 saa sijainnin lokista
        gpx = tmp / "google_gpx" / "loki.gpx"
        tee_gpx(gpx, [(datetime.datetime(2026, 7, 20, 10, 0), 20, 62.40, 28.40)])
        t3 = mk.aja("google", [], [gpx], google_albumi=LINKKI)
        vaita(t3["tuotu"] == 4 and t3["gpx"] == 1,
              f"GPS:tön kuva sijoitettiin GPX-lokista ({t3['tuotu']}, gpx {t3['gpx']})")
        vaita(t3["verkosta"] == 0,
              "GPX-interpolointi tehtiin ilman uutta EXIF-latausta")

        taso3 = QgsVectorLayer(f"{gpkg}|layername={qt.TASON_NIMI}", "t", "ogr")
        tyypit3 = {f["tiedosto"]: (f["laitetyyppi"], f["lahde"]) for f in taso3.getFeatures()}
        vaita(tyypit3.get("g3.jpg") == ("jarjestelmakamera", "gpx"),
              f"Canon → järjestelmäkamera, sijainti GPX:stä ({tyypit3.get('g3.jpg')})")
        vaita(sorted({t[0] for t in tyypit3.values()}) ==
              ["drone", "jarjestelmakamera", "puhelin"],
              f"kaikki kolme laitetyyppiä erottuvat tasolla ({sorted({t[0] for t in tyypit3.values()})})")
        del taso3
    finally:
        gp.hae_albumi, gp.lue_exif = oikea_haku, oikea_exif


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
            testaa_github_osoitteet(tmp)
            testaa_projektikohtainen_repo(tmp)
            testaa_google_lahde(tmp)
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
