# maastokuvat

Sijoittaa maastokuvat kartalle niiden koordinaattien perusteella ja tuottaa
GeoPackage-tason, jonka voi raahata omaan QGIS-projektiin. Kuva avautuu QGIS:ssä
hiiriesikatseluna, Identify-lomakkeessa ja erillisessä katselimessa.

Koordinaatti otetaan kuvan EXIF:istä. Jos kuvassa ei ole GPS:ää (esim.
järjestelmäkamera), se päätellään GPS-loggerin GPX-lokista kuvausajan
perusteella — samalla logiikalla kuin `rak_kult_kuvakarttajulkaisu/pipeline.py`.

## Ajo

```bash
cd /home/markus/omat-apit/maastokuvat
python3 maastokuvat.py
```

Sovellus kysyy:

1. **Projektin nimi** → `projektit/[nimi]/`
2. **Kuvakansio(t)** — yksi polku per rivi, tyhjä rivi lopettaa
3. **GPX-lokit** (valinnainen) — tiedostoja tai kansio; monta lokia sallittu
4. **Kameran kellodrifti** minuutteina — vain kellon heitto, aikavyöhyke hoidetaan itse
5. **Suurin sallittu GPX-aukko** minuutteina (oletus 10)
6. **Kirjoitetaanko GPX-koordinaatti kuvakopion EXIF:iin** (oletus kyllä)

## Mitä syntyy

```
projektit/[nimi]/
├── kuvat/              — kuvat alkuperäiskoossa (kopioita, lähteet jäävät koskematta)
├── esikatselu/         — 1200 px kopiot map tipille (~170 kt, n. 9 % alkuperäisestä)
├── maastokuvat.gpkg    — pistetaso + tyyli tason sisällä
├── maastokuvat.qml     — sama tyyli erillisenä tiedostona
├── kasitellyt.json     — kirjanpito jo tuoduista lähdekuvista
└── ei_sijaintia.txt    — kuvat joita ei voitu sijoittaa, syineen
```

**Raahaa `maastokuvat.gpkg` QGIS:iin.** Tyyli tulee mukana automaattisesti,
koska se on tallennettu GeoPackagen `layer_styles`-tauluun. Jos se jostain syystä
ei tule, lataa `maastokuvat.qml` käsin: tason ominaisuudet → Tyyli → Lataa tyyli.

## Mitä QGIS:ssä näkyy

| Ominaisuus | Miten | Kuvan koko |
|---|---|---|
| **Hiiriesikatselu** | *View → Show Map Tips* (suom. Näytä karttavihjeet), myös nappina Attributes Toolbarissa → osoita pistettä | 620 px |
| **Lomakekuva** | *Identify Features* → `Kuva`-kentässä liite-widget näyttää kuvan | lomakkeen leveys × 480 px |
| **Avaa katselimessa** | Attributes Toolbarin **Feature Action** -nappi (pudotusvalikossa) → klikkaa pistettä. Myös Identify-tuloksissa → *Run Actions* → **Avaa kuva** | alkuperäinen, 4032 px |
| **Kuvaussuunta** | Nuoli kääntyy `suunta`-kentän mukaan; ilman suuntaa pyöreä piste | |

Karttavihje toimii vain kun **taso on aktiivisena** Layers-panelissa.

Kokoja säädetään moduulin `qgis_taso.py` vakioista `MAP_TIP_LEVEYS` (620) ja
`LOMAKE_KUVA_KORKEUS` (480), ja esikatselukuvan tarkkuutta `maastokuvat.py`:n
`ESIKATSELU_PX`-vakiosta (1200). Kun `ESIKATSELU_PX`-arvoa kasvatetaan, seuraava
ajo uusii liian pienet esikatselut automaattisesti.

**Avaa kuva** on tason oletustoiminto, joten Feature Action -työkalu avaa
täysikokoisen kuvan yhdellä klikkauksella ilman valikoita.

Kuvan polku johdetaan lausekkeessa `.gpkg`-tiedoston omasta sijainnista, joten
koko `projektit/[nimi]/`-kansion voi siirtää ilman että viittaukset katkeavat.

## Kuvaussuunta

Suunta luetaan EXIF-kentästä `GPSImgDirection`. **Kaikki kamerat eivät kirjoita
sitä:** tämän koneen 98 Samsung SM-G991B -kuvassa se puuttui kaikista, iPhone
yleensä kirjoittaa. Kun suunta puuttuu, piste piirtyy pyöreänä ja `suunta`-kentän
voi täyttää QGIS:ssä käsin (0–360 astelukusäädin) — symboli muuttuu heti nuoleksi.

Käsin täytetyt `suunta`- ja `huomio`-arvot **säilyvät** kun sovellus ajetaan
uudelleen; muut kentät sovellus kirjoittaa itse ja ne on lukittu lomakkeessa.

## Työskentely erissä

Kuvia voi lisätä useassa ajossa samaan projektiin:

- `kasitellyt.json` estää saman lähdekuvan tuomisen kahdesti. Tunniste on
  tiedostonimi + EXIF-kuvausaika — ei kokoa tai tiivistettä, koska GPS:n
  kirjoittaminen kuvaan muuttaisi ne.
- Jos poistat kohdekuvan `kuvat/`-kansiosta käsin, sama kuva tuodaan uudelleen.
- Taso rakennetaan aina koko `kuvat/`-kansiosta, joten se pysyy ajan tasalla.
- GPX-lokeja voi antaa monta. Pisteet yhdistetään aikajärjestykseen ja
  päällekkäiset aikaleimat karsitaan.

## Aukkosuoja

Yli `max_aukko_min` (oletus 10 min) pituisten GPX-pistevälien yli **ei
interpoloida**. Ilman tätä loggerin yön yli sammuminen antaisi aamun kuvalle
hiljaisesti keksityn sijainnin illan ja aamun pisteiden välistä. Aukot listataan
ajon alussa, ja niihin osuvat kuvat kirjataan `ei_sijaintia.txt`:hin syineen.

## Aikavyöhyke

GPS-loggeri kirjoittaa ajat UTC:nä, kamera paikallisena aikana. Lokin ajat
muunnetaan Helsingin aikaan automaattisesti (kesä/talvi), joten kellodriftiksi
annetaan vain kameran kellon todellinen heitto — ei tunteja.

## EXIF-kirjoitus

GPX:stä päätelty koordinaatti kirjoitetaan **vain projektikansion kopioon**,
ei alkuperäiseen kuvaan. Näin kuva on paikkatietoinen missä tahansa ohjelmassa,
mutta lähdekansio jää koskemattomaksi. (Sisarsovellus `pipeline.py` kirjoittaa
lähdekuvaan, koska se ei kopioi kuvia erikseen.)

## Vielä päättämättä

- **GitHub-vienti.** Tasossa on valmiina `url`-kenttä ja lauseke käyttää sitä
  ensisijaisesti paikallisen polun sijaan, joten kuvien vienti julkiseen repoon
  on pieni lisäys. Vaatii julkisen repon (privaatin raw-URL:t vaativat tokenin)
  ja verkkoyhteyden. Nyt kenttä jätetään tyhjäksi ja kaikki toimii paikallisesti.
- **Valmis .qgz-projekti taustakartalla.** Nyt tuotetaan vain taso; MML-taustakartan
  voi lisätä omaan projektiin itse.

## Vaatimukset

```bash
pip install pillow gpxpy piexif      # QGIS tulee järjestelmästä (python3-qgis)
```

Testattu: QGIS 3.44.11, Python 3.12.

## Testit

```bash
python3 test_maastokuvat.py
```

46 väittämää oikeilla JPEG- ja GPX-tiedostoilla väliaikaishakemistossa:
EXIF-luku, GPX-interpolointi, aukkosuoja, aikavyöhykemuunnos, duplikaattisuoja,
käsin täytettyjen arvojen säilyminen ja tyylin selviäminen GeoPackagesta.

## Tiedostot

| Tiedosto | Sisältö |
|---|---|
| `maastokuvat.py` | Ajo ja kyselyt, kuvien tuonti, tason kokoaminen |
| `exif_gpx.py` | EXIF-luku/kirjoitus, GPX-lokit, interpolointi, aukot |
| `qgis_taso.py` | GeoPackagen kirjoitus, symbolit, map tip, lomake, toiminnot |
| `test_maastokuvat.py` | Regressiotesti |
