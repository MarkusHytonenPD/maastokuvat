"""
qgis_taso.py
============
Kirjoittaa maastokuvat GeoPackage-pistetasoksi ja tallentaa tyylin tason
sisään, jotta .gpkg:n voi raahata omaan QGIS-projektiin ja mukana tulevat:

  • symboli   — nuoli joka kääntyy kuvaussuunnan mukaan, muuten pyöreä piste
  • map tip   — hiiriesikatselu (HTML <img>)
  • lomake    — Liite-widget (Attachment), kuva näkyy Identify-lomakkeessa
  • toiminnot — "Avaa kuva" ja "Avaa kansio"

Tyyli tallennetaan sekä GeoPackagen layer_styles-tauluun (tulee automaattisesti
raahauksessa) että erilliseksi .qml-tiedostoksi (varalle / muihin tasoihin).
"""

import contextlib
import datetime
import os
from pathlib import Path

TASON_NIMI = "maastokuvat"

# Map tipin kuvan leveys pikseleinä. QGIS mitoittaa vihjeikkunan sisällön mukaan,
# joten tämä säätää suoraan sitä miten iso esikatselu kartalla näkyy.
MAP_TIP_LEVEYS = 620

# Identify-lomakkeen kuvanäytön korkeus pikseleinä (leveys = 0 → sovita lomakkeeseen).
LOMAKE_KUVA_KORKEUS = 480

# Tason kentät: (nimi, tyyppi, kommentti)
KENTAT = [
    ("tiedosto",    "String",   "Kuvatiedoston nimi"),
    ("aika",        "DateTime", "Kuvausaika (EXIF DateTimeOriginal)"),
    ("polku",       "String",   "Kuvan polku, suhteessa projektikansioon"),
    ("esikatselu",  "String",   "Pienennetyn esikatselukuvan polku"),
    ("url",         "String",   "Täysikokoisen kuvan verkko-osoite (GitHub raw)"),
    ("url_esikatselu", "String", "Esikatselukuvan verkko-osoite (GitHub raw)"),
    ("suunta",      "Double",   "Kuvaussuunta asteina (EXIF GPSImgDirection); tyhjä = ei tiedossa"),
    ("korkeus",     "Double",   "Korkeus metreinä (EXIF GPSAltitude)"),
    ("laite",       "String",   "Kamera (EXIF Make + Model)"),
    ("laitetyyppi", "String",   "puhelin / drone / jarjestelmakamera"),
    ("lahde",       "String",   "Mistä koordinaatti tuli: exif tai gpx"),
    ("huomio",      "String",   "Vapaa huomautus (esim. GPX-interpolointi)"),
]


@contextlib.contextmanager
def qgis_kaynnissa():
    """
    Käynnistää QGIS:n headless-tilassa ja sammuttaa lopussa.

    HUOM: yksikään QgsVectorLayer ei saa jäädä elossa exitQgis():n yli —
    muuten prosessi kaatuu segfaultiin sammutuksessa. Siksi gc.collect()
    ennen sammutusta, eikä tämän lohkon sisältä palauteta taso-objekteja.
    """
    import gc
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    # Jos QGIS on jo käynnissä (testit, QGIS:n oma Python-konsoli),
    # käytetään sitä eikä kosketa elinkaareen.
    if QgsApplication.instance() is not None:
        yield QgsApplication.instance()
        return

    app = QgsApplication([], False)
    QgsApplication.initQgis()
    try:
        yield app
    finally:
        gc.collect()
        QgsApplication.exitQgis()


# ══════════════════════════════════════════════════════════════════
#  TASON KIRJOITUS
# ══════════════════════════════════════════════════════════════════

def _qdatetime(aika: datetime.datetime | None):
    from qgis.PyQt.QtCore import QDate, QDateTime, QTime
    if aika is None:
        return None
    return QDateTime(QDate(aika.year, aika.month, aika.day),
                     QTime(aika.hour, aika.minute, aika.second))


def kirjoita_gpkg(kohteet: list[dict], gpkg_polku: Path, crs_epsg: str = "EPSG:3067") -> int:
    """
    Kirjoittaa kohteet GeoPackageen (korvaa vanhan tiedoston).
    Jokainen kohde: dict jossa lat, lon ja KENTAT-nimiset avaimet.
    Palauttaa kirjoitettujen kohteiden määrän.
    """
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsCoordinateTransformContext, QgsFeature, QgsField,
                           QgsGeometry, QgsPointXY, QgsVectorFileWriter, QgsVectorLayer)
    from qgis.PyQt.QtCore import QVariant

    tyypit = {"String": QVariant.String, "Double": QVariant.Double,
              "DateTime": QVariant.DateTime, "Int": QVariant.Int}

    taso = QgsVectorLayer(f"Point?crs={crs_epsg}", TASON_NIMI, "memory")
    dp = taso.dataProvider()
    dp.addAttributes([QgsField(nimi, tyypit[tyyppi]) for nimi, tyyppi, _ in KENTAT])
    taso.updateFields()

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    kohde_crs = QgsCoordinateReferenceSystem(crs_epsg)
    ctx = QgsCoordinateTransformContext()
    muunnos = QgsCoordinateTransform(wgs84, kohde_crs, ctx)

    piirteet = []
    for k in kohteet:
        f = QgsFeature(taso.fields())
        piste = muunnos.transform(QgsPointXY(k["lon"], k["lat"]))
        f.setGeometry(QgsGeometry.fromPointXY(piste))
        for nimi, tyyppi, _ in KENTAT:
            arvo = k.get(nimi)
            if tyyppi == "DateTime":
                arvo = _qdatetime(arvo)
            f.setAttribute(nimi, arvo if arvo is not None else None)
        piirteet.append(f)
    dp.addFeatures(piirteet)
    taso.updateExtents()

    gpkg_polku.parent.mkdir(parents=True, exist_ok=True)
    if gpkg_polku.exists():
        gpkg_polku.unlink()

    asetukset = QgsVectorFileWriter.SaveVectorOptions()
    asetukset.driverName = "GPKG"
    asetukset.layerName = TASON_NIMI
    asetukset.fileEncoding = "UTF-8"
    asetukset.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    virhe = QgsVectorFileWriter.writeAsVectorFormatV3(
        taso, str(gpkg_polku), ctx, asetukset)
    if virhe[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"GeoPackagen kirjoitus epäonnistui: {virhe}")
    return len(piirteet)


# ══════════════════════════════════════════════════════════════════
#  TYYLI
# ══════════════════════════════════════════════════════════════════

def _projektikansio_lauseke() -> str:
    """Lauseke joka palauttaa .gpkg-tiedoston kansion (päättyy kenoviivaan)."""
    return "regexp_replace(layer_property(@layer, 'path'), '[^/\\\\\\\\]+$', '')"


def _kuvalauseke(kentta: str = "esikatselu", url_kentta: str = "url_esikatselu") -> str:
    """
    QGIS-lauseke kuvan osoitteelle. Järjestys:

      1. paikallinen tiedosto, jos se on olemassa  → file://... (nopea, toimii offline)
      2. muuten verkko-osoite (GitHub raw), jos kenttä on täytetty
      3. muuten paikallinen polku joka tapauksessa (näyttää puuttuvan kuvan)

    Paikallinen polku johdetaan .gpkg-tiedoston omasta sijainnista, joten
    projektikansion voi siirtää. Näin sama taso toimii sekä koneella jolla
    kuvat ovat levyllä että koneella jolle on kopioitu pelkkä .gpkg.
    """
    paikallinen = (f"{_projektikansio_lauseke()}"
                   f" || coalesce(nullif(\"{kentta}\", ''), \"polku\")")
    return (f"CASE WHEN file_exists({paikallinen}) THEN 'file://' || {paikallinen}"
            f" WHEN coalesce(\"{url_kentta}\", '') <> '' THEN \"{url_kentta}\""
            f" ELSE 'file://' || {paikallinen} END")


def map_tip_html() -> str:
    """Hiiriesikatselu: kuva + perustiedot."""
    return f"""<div style="font-family:sans-serif; font-size:11pt; max-width:{MAP_TIP_LEVEYS + 20}px">
  <img src="[% {_kuvalauseke('esikatselu')} %]" width="{MAP_TIP_LEVEYS}"><br>
  <b>[% "tiedosto" %]</b><br>
  [% coalesce(format_date("aika", 'd.M.yyyy HH:mm'), 'aika tuntematon') %]
  [% CASE WHEN "suunta" IS NOT NULL THEN ' · suunta ' || round("suunta") || '°' ELSE '' END %]
  [% CASE WHEN "korkeus" IS NOT NULL THEN ' · ' || round("korkeus") || ' m' ELSE '' END %]<br>
  <span style="color:#666">[% "laite" %] · [% "lahde" %]</span>
</div>"""


def _symbolit():
    """(nuolisymboli, pistesymboli) — nuoli kääntyy suunta-kentän mukaan."""
    from qgis.core import (QgsMarkerSymbol, QgsProperty, QgsSimpleMarkerSymbolLayer,
                           QgsSimpleMarkerSymbolLayerBase, QgsSymbolLayer)
    from qgis.PyQt.QtGui import QColor

    # Nuoli: kolmio joka osoittaa kuvaussuuntaan
    nuoli = QgsMarkerSymbol()
    kerros = QgsSimpleMarkerSymbolLayer(QgsSimpleMarkerSymbolLayerBase.Triangle)
    kerros.setSize(5.0)
    kerros.setColor(QColor("#e8622a"))
    kerros.setStrokeColor(QColor("#ffffff"))
    kerros.setStrokeWidth(0.4)
    kerros.setDataDefinedProperty(
        QgsSymbolLayer.PropertyAngle, QgsProperty.fromExpression('"suunta"'))
    nuoli.changeSymbolLayer(0, kerros)

    # Ei suuntaa: pyöreä piste
    piste = QgsMarkerSymbol()
    ympyra = QgsSimpleMarkerSymbolLayer(QgsSimpleMarkerSymbolLayerBase.Circle)
    ympyra.setSize(3.4)
    ympyra.setColor(QColor("#e8622a"))
    ympyra.setStrokeColor(QColor("#ffffff"))
    ympyra.setStrokeWidth(0.4)
    piste.changeSymbolLayer(0, ympyra)

    return nuoli, piste


def _aseta_renderer(taso):
    from qgis.core import QgsRuleBasedRenderer
    nuoli, piste = _symbolit()

    juuri = QgsRuleBasedRenderer.Rule(None)

    r1 = QgsRuleBasedRenderer.Rule(nuoli)
    r1.setLabel("Kuvaussuunta tiedossa")
    r1.setFilterExpression('"suunta" IS NOT NULL')
    juuri.appendChild(r1)

    r2 = QgsRuleBasedRenderer.Rule(piste)
    r2.setLabel("Suunta ei tiedossa")
    r2.setFilterExpression('"suunta" IS NULL')
    juuri.appendChild(r2)

    taso.setRenderer(QgsRuleBasedRenderer(juuri))


ALIAKSET = {
    "tiedosto": "Kuva",
    "aika": "Kuvausaika",
    "polku": "Kuva",
    "esikatselu": "Esikatselu",
    "url": "Verkko-osoite (kuva)",
    "url_esikatselu": "Verkko-osoite (esikatselu)",
    "suunta": "Kuvaussuunta (°)",
    "korkeus": "Korkeus (m)",
    "laite": "Kamera",
    "laitetyyppi": "Laitetyyppi",
    "lahde": "Koordinaatin lähde",
    "huomio": "Huomio",
}


def _aseta_lomake(taso, projektikansio: Path):
    """Liite-widget polku-kentälle: kuva näkyy Identify-lomakkeessa."""
    from qgis.core import QgsEditorWidgetSetup
    from qgis.gui import QgsExternalResourceWidget, QgsFileWidget

    asetukset = {
        "FileWidget": True,
        "FileWidgetButton": True,
        "FileWidgetFilter": "Kuvat (*.jpg *.jpeg *.png)",
        "DocumentViewer": int(QgsExternalResourceWidget.Image),
        "DocumentViewerHeight": LOMAKE_KUVA_KORKEUS,
        "DocumentViewerWidth": 0,       # 0 = sovita lomakkeen leveyteen
        "RelativeStorage": int(QgsFileWidget.RelativeDefaultPath),
        "DefaultRoot": str(projektikansio),
        "StorageMode": int(QgsFileWidget.GetFile),
        "StorageType": "",
        "PropertyCollection": {"name": None, "properties": {}, "type": "collection"},
    }
    idx = taso.fields().indexOf("polku")
    taso.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ExternalResource", asetukset))

    # Suunta on tarkoitettu täytettäväksi käsin, kun EXIF:issä ei ole sitä
    suunta_idx = taso.fields().indexOf("suunta")
    taso.setEditorWidgetSetup(suunta_idx, QgsEditorWidgetSetup("Range", {
        "Min": 0.0, "Max": 360.0, "Step": 1.0, "Style": "SpinBox",
        "AllowNull": True, "Precision": 0,
    }))

    # Sovellus kirjoittaa nämä joka ajolla → lukittu lomakkeessa,
    # jotta käsin tehty muutos ei katoa huomaamatta seuraavassa ajossa.
    lomake = taso.editFormConfig()
    for kentta in ("tiedosto", "esikatselu", "url", "url_esikatselu", "lahde",
                   "laite", "laitetyyppi", "aika"):
        i = taso.fields().indexOf(kentta)
        if i >= 0:
            lomake.setReadOnly(i, True)
    taso.setEditFormConfig(lomake)

    for nimi, alias in ALIAKSET.items():
        i = taso.fields().indexOf(nimi)
        if i >= 0:
            taso.setFieldAlias(i, alias)

    taso.setDisplayExpression('"tiedosto"')


def _aseta_toiminnot(taso):
    """Actionit: avaa kuva katselimessa, avaa kansio."""
    from qgis.core import QgsAction, Qgis
    from qgis.PyQt.QtCore import QUuid

    hallinta = taso.actions()
    for olemassa in list(hallinta.actions()):
        hallinta.removeAction(olemassa.id())

    tyyppi = Qgis.AttributeActionType.OpenUrl
    kuva = QgsAction(QUuid.createUuid(), tyyppi, "Avaa kuva",
                     f"[% {_kuvalauseke('polku', 'url')} %]", "", False,
                     "Avaa täysikokoinen kuva järjestelmän katselimessa",
                     {"Field", "Feature", "Canvas"})
    hallinta.addAction(kuva)
    # Oletustoiminto: "Suorita kohteen toiminto" -työkalu avaa täysikokoisen
    # kuvan suoraan kartalta klikkaamalla, ilman valikoita.
    for laajuus in ("Feature", "Canvas"):
        hallinta.setDefaultAction(laajuus, kuva.id())

    kansio = QgsAction(
        QUuid.createUuid(), tyyppi, "Avaa kuvakansio",
        f"[% 'file://' || {_projektikansio_lauseke()} || 'kuvat' %]",
        "", False, "Avaa projektin kuvakansio tiedostoselaimessa", {"Feature", "Canvas"})
    hallinta.addAction(kansio)


def muotoile_taso(taso, projektikansio: Path):
    """Asettaa symbolit, map tipin, lomakkeen ja toiminnot."""
    _aseta_renderer(taso)
    taso.setMapTipTemplate(map_tip_html())
    _aseta_lomake(taso, projektikansio)
    _aseta_toiminnot(taso)


def tallenna_tyyli(taso, gpkg_polku: Path, qml_polku: Path) -> tuple[bool, str]:
    """
    Tallentaa tyylin GeoPackagen sisään (oletustyyliksi) ja .qml-tiedostoksi.
    Palauttaa (onnistui, viesti).
    """
    viesti = taso.saveStyleToDatabase(TASON_NIMI, "Maastokuvat: symboli, map tip, liite-widget",
                                      True, "")
    qml_tulos = taso.saveNamedStyle(str(qml_polku))
    ok = qml_polku.exists()
    return ok, f"{viesti or 'gpkg-tyyli ok'} / qml: {qml_tulos[0] if qml_tulos else ''}"


def lataa_ja_muotoile(gpkg_polku: Path, projektikansio: Path,
                      qml_polku: Path | None = None) -> str:
    """
    Lataa juuri kirjoitetun GeoPackagen, muotoilee sen ja tallentaa tyylin.
    Palauttaa tilaviestin. Taso-objektia EI palauteta (ks. qgis_kaynnissa).
    """
    from qgis.core import QgsVectorLayer
    taso = QgsVectorLayer(f"{gpkg_polku}|layername={TASON_NIMI}", TASON_NIMI, "ogr")
    if not taso.isValid():
        raise RuntimeError(f"Tasoa ei voitu ladata: {gpkg_polku}")
    muotoile_taso(taso, projektikansio)
    if qml_polku is None:
        qml_polku = gpkg_polku.with_suffix(".qml")
    _ok, viesti = tallenna_tyyli(taso, gpkg_polku, qml_polku)
    del taso
    return viesti
