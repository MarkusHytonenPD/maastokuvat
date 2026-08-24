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

Vaiheittainen ohje kysymyksistä, QGIS-käytöstä ja vianetsinnästä:
[KAYTTOOHJE.md](KAYTTOOHJE.md).

Sovellus kysyy:

1. **Projektin nimi** → `projektit/[nimi]/`
2. **Kuvien lähde** — `1` paikallinen kuvakansio (oletus) tai `2` Google Photos
   -jakoalbumi (ks. [Google Photos -albumi lähteenä](#google-photos--albumi-lähteenä))
3. **Kuvakansio(t)** tai **albumin linkki** — kansioita yksi polku per rivi,
   tyhjä rivi lopettaa
4. **GPX-lokit** (valinnainen) — tiedostoja tai kansio; monta lokia sallittu
5. **Kameran kellodrifti** minuutteina — vain kellon heitto, aikavyöhyke hoidetaan itse
6. **Suurin sallittu GPX-aukko** minuutteina (oletus 10)
7. **Kirjoitetaanko GPX-koordinaatti kuvakopion EXIF:iin** (oletus kyllä)
8. **Viedäänkö kuvat GitHubiin** (oletus kyllä)

Kohdat 7–8 kysytään vain paikalliselle kuvakansiolle: Google-lähteessä kuvia ei
kopioida, joten niiden EXIF:iin ei kirjoiteta eikä niitä viedä GitHubiin.

## Mitä syntyy

```
projektit/[nimi]/
├── kuvat/              — kuvat alkuperäiskoossa (kopioita, lähteet jäävät koskematta)
├── esikatselu/         — 1200 px kopiot map tipille (~170 kt, n. 9 % alkuperäisestä)
├── maastokuvat.gpkg    — pistetaso + tyyli tason sisällä
├── maastokuvat.qml     — sama tyyli erillisenä tiedostona
├── kasitellyt.json     — kirjanpito jo tuoduista lähdekuvista
├── tila.json           — tason sisällön tiiviste (estää turhat uudelleenkirjoitukset)
├── projekti.json       — GitHub-repo ja/tai Google-albumin linkki
└── ei_sijaintia.txt    — kuvat joita ei voitu sijoittaa, syineen
```

Google Photos -lähteellä `kuvat/`- ja `esikatselu/`-kansioita ei synny lainkaan:
projektikansioon jää vain `.gpkg`, `.qml` ja kirjanpito, yhteensä joitakin satoja
kilotavuja.

**Raahaa `maastokuvat.gpkg` QGIS:iin.** Tyyli tulee mukana automaattisesti,
koska se on tallennettu GeoPackagen `layer_styles`-tauluun. Jos se jostain syystä
ei tule, lataa `maastokuvat.qml` käsin: tason ominaisuudet → Tyyli → Lataa tyyli.

## Mitä QGIS:ssä näkyy

| Ominaisuus | Miten | Kuvan koko |
|---|---|---|
| **Hiiriesikatselu** | *View → Show Map Tips* (suom. Näytä karttavihjeet), myös nappina Attributes Toolbarissa → osoita pistettä | 620 px |
| **Lomakekuva** | *Identify Features* → `Kuva`-kentässä liite-widget näyttää kuvan | lomakkeen leveys × 480 px |
| **Avaa katselimessa** | Attributes Toolbarin **Feature Action** -nappi (pudotusvalikossa) → klikkaa pistettä. Myös Identify-tuloksissa → *Run Actions* → **Avaa kuva** | alkuperäinen, 4032 px |
| **Kuvaussuunta** | Nuoli kääntyy `suunta`-kentän mukaan; ilman suuntaa pyöreä piste tai vinoneliö | |
| **Drone erikseen** | Dronekuvat piirtyvät sinisinä, maasta kuvatut oranssina | |

Karttavihje toimii vain kun **taso on aktiivisena** Layers-panelissa.

Kokoja säädetään moduulin `qgis_taso.py` vakioista `MAP_TIP_LEVEYS` (620) ja
`LOMAKE_KUVA_KORKEUS` (480), ja esikatselukuvan tarkkuutta `maastokuvat.py`:n
`ESIKATSELU_PX`-vakiosta (1200). Kun `ESIKATSELU_PX`-arvoa kasvatetaan, seuraava
ajo uusii liian pienet esikatselut automaattisesti.

**Avaa kuva** on tason oletustoiminto, joten Feature Action -työkalu avaa
täysikokoisen kuvan yhdellä klikkauksella ilman valikoita.

Kuvan polku johdetaan lausekkeessa `.gpkg`-tiedoston omasta sijainnista, joten
koko `projektit/[nimi]/`-kansion voi siirtää ilman että viittaukset katkeavat.

## Symbolit

Väri kertoo laitteen, muoto kertoo tiedetäänkö kuvaussuunta:

| Symboli | Sääntö | Selite tasolla |
|---|---|---|
| Sininen kolmio, kääntyy | `laitetyyppi = 'drone'` ja suunta tiedossa | Drone · kuvaussuunta tiedossa |
| Sininen vinoneliö | drone, ei suuntaa | Drone |
| Oranssi kolmio, kääntyy | muu laite ja suunta tiedossa | Maasta · kuvaussuunta tiedossa |
| Oranssi piste | muu laite, ei suuntaa | Maasta |

Värit: maasta `#e8622a`, drone `#1f6feb`. Oranssi/sininen on turvallinen pari
myös puna-vihersokealle, ja **muoto** erottaa laitteet vielä harmaasävy-
tulosteessa. Drone tunnistetaan EXIF `Make` -kentästä (dji, autel, parrot,
skydio, yuneec — `exif_gpx.tunnista_laite`), joten mitään ei tarvitse valita
ajossa.

Säännöt ovat listassa `qgis_taso.SAANNOT` (suodatin, muoto, koko, väri,
kääntyykö). Lista on mukana `tyylin_tunniste()`-tiivisteessä, joten symbolin
muokkaus saa seuraavan ajon kirjoittamaan tason uudelleen myös silloin kun
kuvadata on ennallaan.

Suodattimissa on `coalesce("laitetyyppi", '')`, koska sääntöpohjainen renderöijä
jättäisi kohteen piirtämättä kokonaan jos yksikään sääntö ei osu — NULL-arvo
käsin muokatulla rivillä riittäisi hukkaamaan pisteen kartalta.

Nuolen kulma on kompassisuunta suoraan. Mitattu renderöidyistä pikseleistä:
0° → pohjoinen, 45° → koillinen, 90° → itä, 180° → etelä, 270° → länsi.

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

## Google Photos -albumi lähteenä

Lähteeksi voi antaa julkisen Google Photos -jakoalbumin linkin
(`https://photos.app.goo.gl/…`). Silloin **kuvia ei kopioida mihinkään**: taso
viittaa suoraan Googlen osoitteisiin, ja `kuvat/`-kansiota ei synny.

```
url            → https://lh3.googleusercontent.com/pw/[tunnus]=d       (alkuperäinen)
url_esikatselu → https://lh3.googleusercontent.com/pw/[tunnus]=w1200   (map tip)
```

Albumi on jaettava **"kaikille joilla on linkki"**, muuten kuvat eivät näy
QGIS:ssä. Linkki kirjataan `projekti.json`-tiedostoon, joten uudelleenajossa
riittää painaa Enter.

### Miksi ei Googlen APIa

| Este | Seuraus |
|---|---|
| Library API rajattiin **31.3.2025** vain sovelluksen itse lataamaan sisältöön; jaettujen albumien funktiot palauttavat `403 PERMISSION_DENIED` | albumia ei voi listata API:lla |
| API **ei palauta EXIF-GPS:ää** (Google jätti sijainnin pois tietosuojasyistä) | juuri se tieto jota tämä sovellus tarvitsee puuttuisi |
| API:n `baseUrl` vanhenee **60 minuutissa** | osoitetta ei voi tallentaa GeoPackageen |

Siksi `google_photos.py` lukee jakolinkin julkisen sivun ja poimii sen
datalohkosta kuvien `lh3.googleusercontent.com`-osoitteet. Ne toimivat ilman
kirjautumista. **Tämä ei ole dokumentoitu rajapinta:** jos Google muuttaa sivun
rakennetta, korjattava kohta on `google_photos._MEDIA`.

### Miten koordinaatit saadaan

Pienennetystä `=w1200`-kuvasta EXIF on riisuttu, mutta `=d` tarjoilee
alkuperäisen tiedoston GPS-kenttineen — ja tukee **Range-pyyntöä**. Sovellus
lataa vain kuvan ensimmäiset **128 kt** (`google_photos.EXIF_TAVUJA`), mikä
riittää koko EXIF-lohkoon. 300 kuvan albumi maksaa siis ~40 MB eikä 600 MB, ja
mitään ei jää levylle. Lataukset tehdään 8 rinnakkain (~40 s / 300 kuvaa).

Tulos jää `kasitellyt.json`-kirjanpitoon Googlen media-id:n alle, joten
**uudelleenajo ei lataa mitään**. GPX-interpolointi sen sijaan tehdään joka
ajossa uudelleen — välimuistissa on vain kuvan oma EXIF — joten myöhemmin
annettu GPX-loki sijoittaa myös aiemmin hylätyt kuvat.

Samasta 128 kt:n alusta luetaan kaikki muutkin EXIF-kentät, joten
**laitetyyppi** (puhelin / drone / järjestelmäkamera), kamera, kuvausaika,
kuvaussuunta ja korkeus toimivat Google-lähteessä täsmälleen kuten
paikallisilla kuvilla — myös järjestelmäkameran kuvien sijoittaminen
GPX-lokista.

### Mitä menetetään

- **Osoitteiden pysyvyys ei ole taattu.** Jos albumin jakaminen lopetetaan, kuva
  poistetaan tai Google kierrättää tunnisteet, tason kuvat katoavat kaikki
  kerralla — eikä paikallista varakopiota ole.
- **Taso vaatii verkkoyhteyden.** Paikallisella kuvakansiolla kuvat luetaan
  levyltä ja verkko on vain vara; Google-lähteessä verkko on ainoa lähde.
- **Identify-lomakkeen liite-widget jää tyhjäksi**, koska se näyttää
  `polku`-kentän tiedostoa eikä sitä ole. Map tip ja **Avaa kuva** toimivat
  normaalisti — ne käyttävät verkko-osoitetta.
- Videoita ja muita ei-JPEG-tiedostoja ei sijoiteta; ne kirjataan
  `ei_sijaintia.txt`:hin syineen.
- Albumin kuvat luetaan sivun ensimmäisestä datalohkosta. 300 kuvan albumi
  luettiin kokonaan; **paljon suuremmilla albumeilla sivutusta ei ole testattu**
  — ajo kertoo montako kuvaa löytyi, joten luku kannattaa vilkaista.

Jos kuvat halutaan pysyviksi, sama albumi kannattaa ladata levylle (Google
Takeout tai albumin lataus zipinä) ja ajaa paikallisena kuvakansiona — silloin
kuvat menevät myös GitHubiin.

### Verifiointi verkkoa vasten

Regressiotesti ajaa Google-haaran ilman verkkoa (albumin haku ja EXIF-luku
korvataan paikallisilla kuvilla). Aitoa albumia vasten mitattu 24.8.2026,
300 kuvan albumi:

| Asia | Tulos |
|---|---|
| Albumin jäsennys | 300 kuvaa, 1,2 s |
| `=d` + Range `0-131071` | HTTP 206, EXIF + GPS luettu, `Content-Disposition` antoi alkuperäisen nimen |
| `=w1200` | 225 kt, EXIF riisuttu |
| 16 kuvan EXIF rinnakkain | 2,1 s |
| Map tipin renderöinti | QtWebKit latasi kuvan Googlelta (1200 × 540 px) — sama moottori jota QGIS:n karttavihje käyttää |

## Kuvat GitHubissa

Kuvat viedään repoon **[MarkusHytonenPD/maastokuvat](https://github.com/MarkusHytonenPD/maastokuvat)**
alkuperäiskoossa, ja taso saa niihin raw-osoitteet:

```
url            → …/main/projektit/[nimi]/kuvat/[tiedosto]        (alkuperäinen, ~2 MB)
url_esikatselu → …/main/projektit/[nimi]/esikatselu/[tiedosto]   (1200 px, ~170 kt)
```

**Repo on julkinen.** Se on pakko: privaatin repon raw-osoite vaatii tokenin,
jota QGIS ei osaa antaa, joten kuvat eivät näkyisi lainkaan.

**Paikallinen tiedosto voittaa aina.** Tason lauseke on
`CASE WHEN "polku" <> '' AND file_exists(paikallinen) THEN file://… WHEN url <> '' THEN url ELSE … END`,
eli tällä koneella kuvat luetaan levyltä (nopea, toimii offline) ja verkko-osoitetta
käytetään vain jos tiedostoa ei ole. Ehto `"polku" <> ''` on Google-lähteen takia:
tyhjällä polulla `file_exists()` osuisi projektikansioon (hakemisto on olemassa)
ja verkko-osoite jäisi käyttämättä.

### Toinen kone

Kopioi pelkkä `maastokuvat.gpkg` ja avaa se QGIS:ssä — siinä kaikki. Kuvat
tulevat GitHubista eikä levytilaa kulu kilotavua enempää. Tyyli on tiedoston
sisällä, joten mitään muuta ei tarvitse siirtää.

Vaihtoehtoisesti `git clone` tuo kuvatkin levylle, jolloin taso toimii myös
ilman verkkoa.

### Kokorajat

| Raja | Arvo | Näillä kuvilla |
|---|---|---|
| Yksittäinen tiedosto | 100 MB (esto) | 2,0 MB/kuva |
| Repo, suositus | 1 GB | ~460 kuvaa (kuva + esikatselu) |
| Repo, yläraja | ~5 GB | ~2 300 kuvaa |

Git-historia ei kevene: poistettu kuva jää historiaan, ja koon saa alas vain
kirjoittamalla historian uudelleen. **Älä käytä Git LFS:ää** — raw-osoite ei
tarjoile LFS-sisältöä kuvana, joten `<img>`-viittaus rikkoutuisi.

Vienti tapahtuu ajon lopussa automaattisesti (`git_push`); ajossa voi vastata
`e`, jos haluaa vain paikallisen tason. Kohderepo luetaan työkopion
`origin`-remotesta; `maastokuvat.py`:n vakiot `GITHUB_USER` / `GITHUB_REPO` /
`GITHUB_BRANCH` ovat vain varalla, jos remotea ei ole.

### Kun repo täyttyy

Mitattuna **89 MB per 40 kuvan projekti** (2,0 MB kuva + 0,17 MB esikatselu), eli
1 GB ≈ 11 projektia ja 5 GB ≈ 57 projektia. Kovaa estoa ei ole; yli ~5 GB:ssä
GitHub voi pyytää siivoamaan.

Kun yksi repo täyttyy, **ohjaa uudet projektit uuteen repoon** (esim.
`maastokuvat-2027`). Vanhat projektit toimivat ikuisesti vanhaa repoa vasten,
koska osoitteet ovat absoluuttisia eikä niihin tarvitse koskea.

Repo tallennetaan siksi **projektikohtaisesti** tiedostoon `projekti.json`:

```json
{ "github": { "user": "MarkusHytonenPD", "repo": "maastokuvat", "branch": "main" } }
```

Uusi projekti saa kohteensa työkopion `origin`-remotesta (ei koodivakiosta, jotta
osoite ei voi erota siitä minne push menee). Jos projekti kuuluu eri repoon kuin
työkopio, sovellus **varoittaa eikä pushaa** — muuten vanhan projektin
uudelleenajo kirjoittaisi sen osoitteet uuteen repoon, jossa niitä kuvia ei ole.
Poista `projekti.json`, jos haluat oikeasti siirtää projektin kuvat toiseen repoon.

Muut keinot: pienempi kuvakoko uusille projekteille (2560 px ≈ 0,7 MB
kolminkertaistaa kapasiteetin), toinen isäntä (vain URL-pohja vaihtuu), tai
viimeisenä `git filter-repo` joka poistaa alkuperäiset historiasta ja jättää
esikatselut — silloin map tipit toimivat mutta täysikokoisten linkit katkeavat.

### Kevyt työkopio toiselle koneelle

Jos et halua kuvia levylle, kloonaa ilman kuvablobeja — **552 kt** koko repon
sijaan (mitattu):

```bash
git clone --no-checkout --filter=blob:none https://github.com/MarkusHytonenPD/maastokuvat.git
cd maastokuvat
git sparse-checkout set --no-cone '/*' '!/projektit/*/kuvat/*' '!/projektit/*/esikatselu/*'
git checkout main
```

Saat `.gpkg`:t ja koodin; kuvat tulevat raw-osoitteista. Pysyy pienenä
riippumatta repon koosta.

### Turhat commitit estetty

`tila.json` sisältää tiivisteen tason datasta ja tyylistä. Jos kumpikaan ei ole
muuttunut, `.gpkg`:tä ja `.qml`:ää ei kirjoiteta uudelleen lainkaan, joten ajo
ilman uusia kuvia ei tuota committia. Tämä vaati kaksi asiaa:

- Toimintojen UUID:t johdetaan nimestä (`_vakaa_uuid`) — satunnainen
  `QUuid.createUuid()` vaihtoi tyylin joka ajolla.
- Käsin täytetyt arvot luetaan vanhasta tasosta suoraan SQLitesta read-only-
  tilassa. GeoPackagen avaaminen QGIS/GDAL:lla muuttaa tiedostoa myös silloin
  kun mitään ei kirjoiteta.

QGIS kirjoittaa `.qml`:n XML-attribuutit satunnaisessa järjestyksessä, joten
kun taso todella kirjoitetaan, sen diff on iso vaikka muutos olisi pieni.

## Vielä päättämättä

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

114 väittämää oikeilla JPEG- ja GPX-tiedostoilla väliaikaishakemistossa:
EXIF-luku, GPX-interpolointi, aukkosuoja, aikavyöhykemuunnos, duplikaattisuoja,
käsin täytettyjen arvojen säilyminen, esikatselun uusiminen, symbolisäännöt
(drone omalla värillä, jokainen kohde osuu täsmälleen yhteen sääntöön),
GitHub-osoitteet,
projektikohtainen repo, Google Photos -lähde (puhelin, drone ja
järjestelmäkamera) ja tyylin selviäminen
GeoPackagesta. Testit eivät koske oikeaan git-repoon **eivätkä verkkoon**:
Google-haara ajetaan paikallisilla kuvilla, jotka korvaavat albumin haun ja
EXIF-latauksen.

## Tiedostot

| Tiedosto | Sisältö |
|---|---|
| `maastokuvat.py` | Ajo ja kyselyt, kuvien tuonti, tason kokoaminen |
| `exif_gpx.py` | EXIF-luku/kirjoitus, GPX-lokit, interpolointi, aukot |
| `google_photos.py` | Google Photos -jakoalbumin luku: albumin jäsennys, EXIF Range-pyynnöllä |
| `qgis_taso.py` | GeoPackagen kirjoitus, symbolit, map tip, lomake, toiminnot |
| `test_maastokuvat.py` | Regressiotesti |
| `KAYTTOOHJE.md` | Käytännön käyttöohje: ajo, QGIS, vianetsintä |
