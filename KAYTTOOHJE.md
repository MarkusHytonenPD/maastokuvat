# Käyttöohje — maastokuvat

Käytännön ohje päivittäiseen työhön: kuvat kentältä kartalle QGIS:iin.
Tekninen kuvaus ja asennus on [README.md](README.md):ssä.

---

## 1. Käynnistäminen

Avaa pääte ja aja kaksi komentoa:

```bash
cd /home/markus/omat-apit/maastokuvat
python3 maastokuvat.py
```

Ohjelma vastaa otsikolla ja alkaa kysellä:

```
==============================================================
  Maastokuvat — kuvat kartalle QGIS:iin
==============================================================

Projektin nimi:
>
```

Ohjelma on tekstipohjainen: se kysyy asiat järjestyksessä ja tekee työn vasta
viimeisen vastauksen jälkeen. Kaikkiin kysymyksiin on järkevä oletus, joka
kelpuutetaan pelkällä Enterillä.

Keskeytys milloin tahansa: **Ctrl+C**. Mitään ei jää puolitiehen niin että se
rikkoutuisi — pahimmillaan osa kuvista on jo kopioitu, ja seuraava ajo jatkaa
siitä.

---

## 2. Kysymykset järjestyksessä

### Projektin nimi

```
Projektin nimi:
> heinavesi_ita
```

Nimi on kansion nimi, joten vältä välilyöntejä ja ääkkösiä. Sama nimi = sama
projekti: kuvat lisätään vanhojen jatkoksi. Uusi nimi = uusi projekti.

### Kuvien lähde

```
Kuvien lähde:
  1) paikallinen kuvakansio — kuvat kopioidaan projektiin
  2) Google Photos -jakoalbumi — kuvia ei kopioida, taso viittaa Googleen
Valinta [1]:
```

Enter valitsee paikallisen kansion, eli vanhan tutun tavan. Valitse **2**, kun
kuvat ovat jo Google Photosissa eikä niitä haluta kopioida levylle tai
GitHubiin — ks. [Google Photos -jakoalbumi](#google-photos--jakoalbumi) alla.

### Kuvakansio(t)

```
Kuvakansio(t):
Yksi polku per rivi. Tyhjä rivi lopettaa.
  > /home/markus/Lataukset/hein_ita_kuvat
      + /home/markus/Lataukset/hein_ita_kuvat
  >
```

Anna kansio, jossa kuvat ovat. Useampi kansio: yksi per rivi. **Tyhjä rivi
päättää listan.** Ohjelma lukee kansiosta kaikki `.jpg`- ja `.jpeg`-tiedostot
(ei alikansioita).

Helpoin tapa syöttää polku: raahaa kansio päätteeseen, niin polku ilmestyy
itsestään.

### Google Photos -jakoalbumi

Kysytään vain jos valitsit lähteeksi **2**:

```
Google Photos -jakoalbumin linkki (albumissa: Jaa → Kopioi linkki).
Albumin on oltava jaettu kaikille joilla on linkki — muuten kuvat
eivät näy QGIS:ssä.
  > https://photos.app.goo.gl/6RwptiEYPhoYY8vEA
```

Linkin saa Google Photosista: avaa albumi → **Jaa** → *Kopioi linkki*. Albumin
jakoasetus on oltava **"kaikki joilla on linkki"**; muuten QGIS ei saa kuvia
näkyviin, koska se ei kirjaudu Google-tilillesi.

Linkki jää muistiin (`projekti.json`), joten seuraavassa ajossa riittää **Enter**:

```
Tyhjä rivi = tälle projektille kirjattu linkki:
  https://photos.app.goo.gl/6RwptiEYPhoYY8vEA
  >
```

Tässä tilassa **kuvia ei kopioida mihinkään**. Ohjelma lataa jokaisen kuvan
alusta 128 kt lukeakseen koordinaatin EXIF:istä, ja taso viittaa Googlen
osoitteisiin. 300 kuvan albumi kesti **37 s** ja projektikansioon jäi **412 kt**
(vertailun vuoksi paikallinen tuonti olisi vienyt ~660 MB). Kysymyksiä
EXIF-kirjoituksesta ja GitHubista ei tule, koska kopioita ei ole.

Toinen ajo samalle albumille on lähes välitön (**3 s**): kertaalleen luetut
EXIF-tiedot ovat `kasitellyt.json`-kirjanpidossa eikä niitä ladata uudelleen.

Lue myös [README.md](README.md):n kohta *Google Photos -albumi lähteenä* —
siinä kerrotaan mitä tässä tilassa menetetään (taso hajoaa jos albumin jako
loppuu, kuvat vaativat verkkoyhteyden).

### GPX-lokit

```
Onko mukana GPS-loggerin GPX-lokeja? (k/e): e
```

Vastaa **e**, jos kuvat on otettu puhelimella tai dronella — niissä koordinaatti
on jo kuvassa. Vastaa **k** vain jos mukana on järjestelmäkameran kuvia, joissa
ei ole GPS:ää.

Jos vastaat **k**, tulee kolme lisäkysymystä:

```
GPX-lokit — yksi polku per rivi, tai kansio (kaikki sen .gpx-tiedostot).
Tyhjä rivi lopettaa.
  > /home/markus/Lataukset/lokit
      + 20260702.gpx
      + 20260703.gpx
  >

Kameran kellodrifti minuutteina (0 jos synkronoitu puhelimeen).
Aikavyöhyke hoidetaan automaattisesti.
  Drifti [0]: 0

Suurin sallittu aukko GPX-pisteiden välissä minuutteina.
Pidempien aukkojen (loggeri pois päältä) yli ei interpoloida.
  Aukko [10]: 10
```

- **Kansion voi antaa tiedostojen sijaan** — siitä otetaan kaikki .gpx:t. Lokeja
  voi olla monta, esimerkiksi yksi per päivä.
- **Drifti** on vain kameran kellon heitto. Älä laita tunteja aikavyöhykkeen
  takia — ohjelma tietää että loggeri kirjoittaa UTC:tä ja kamera paikallista
  aikaa, ja hoitaa muunnoksen itse. Jos kameran kello on 3 minuuttia edellä,
  anna `3`.
- **Aukko** suojaa keksityiltä sijainneilta. Jos loggeri on ollut yön yli pois
  päältä, aamun kuvalle ei arvata sijaintia illan ja aamun pisteiden välistä
  vaan kuva ohitetaan. Oletus 10 minuuttia on hyvä; kasvata vain jos loggeri
  tallentaa harvakseltaan.

### EXIF-kirjoitus

```
Kirjoitetaanko GPX:stä saatu koordinaatti kuvakopion EXIF:iin? (K/e): K
```

Enter riittää. Tällöin GPX:stä päätelty sijainti kirjoitetaan kuvaan, jolloin
kuva on paikkatietoinen missä tahansa ohjelmassa myöhemminkin.
**Alkuperäisiin kuviisi ei kosketa** — kirjoitus tehdään projektikansion
kopioon.

### GitHub-vienti

```
Viedäänkö kuvat GitHubiin (MarkusHytonenPD/maastokuvat)? (K/e): K
```

Enter riittää. Ohjelma commitoi ja pushaa itse. Vastaa **e** vain jos haluat
tehdä tason paikallisesti etkä julkaista kuvia vielä; jo aiemmin viedyn
projektin verkko-osoitteet eivät katoa siitä.

---

## 3. Mitä ajo tulostaa

Näyte oikeasta ajosta, jossa oli mukana GPX-loki:

```
--- GPS-loggerin lokit ---
    20260702.gpx: 40 pistettä
  40 pistettä (02.07. 10:00 – 02.07. 16:19)
  1 aukkoa yli 10 min — näiden yli ei interpoloida:
    02.07. 10:19 – 02.07. 16:00  (341 min)

--- Kuvien tuonti (4 lähdekuvaa) ---
  ✓ 20260702_101500.jpg  (62.385500, 29.065400)  exif
  ✓ 20260702_101812.jpg  (62.382100, 29.060500)  exif
  ⊕ IMG_4417.jpg  (62.387400, 29.065000)  gpx
  ⚠ IMG_4418.jpg: (02.07. 13:00) GPX-aukko 341 min (02.07. 10:19–02.07. 16:00) — loggeri pois päältä?

--- QGIS-taso ---
  GitHub-kohde: MarkusHytonenPD/maastokuvat (main)
  3 kuvapistettä → …/projektit/esimerkki/maastokuvat.gpkg
  tyyli: gpkg-tyyli ok / qml: Created default style file as …

--- GitHub-vienti ---
  Commit: Maastokuvat: esimerkki (3 kuvapistettä)  (9 tiedostoa)
  Pushataan GitHubiin… (isot kuvat voivat viedä hetken)
  ✓ Pushattu: MarkusHytonenPD/maastokuvat (main)

==============================================================
  Valmis!
  Kuvia tuotu:        3  (EXIF 2, GPX 1)
  Kuvapisteitä tasolla: 3  (kuvaussuunta 0:lla)
  Ilman sijaintia:    1  → …/projektit/esimerkki/ei_sijaintia.txt
  GitHub:             pushattu

  Raahaa QGIS:iin:    …/projektit/esimerkki/maastokuvat.gpkg
==============================================================
```

Aukot listataan **ennen** kuvien käsittelyä, joten näet heti onko lokeissa
katvealueita. Yllä loggeri on ollut pois päältä 341 minuuttia, ja siihen väliin
osuva `IMG_4418.jpg` jäi sijoittamatta.

Merkit rivien alussa:

| Merkki | Tarkoittaa |
|---|---|
| ✓ | koordinaatti kuvan omasta EXIF:istä |
| ⊕ | koordinaatti pääteltiin GPX-lokista |
| ⚠ | kuvaa ei voitu sijoittaa — syy kerrotaan, kuva ohitetaan |

### Google-albumin ajo

Sama ajo Google Photos -albumista (oikea ajo, 300 kuvan albumi):

```
--- Google Photos -albumi ---
  300 kuvaa albumissa
  luetaan 300 kuvan EXIF verkosta (~128 kt/kuva)…
    25/300
    50/300
    …
  ⚠ 20260813_095725.jpg: ei EXIF-GPS:ää eikä GPX-lokia
  ⚠ 20260814_190008.jpg: ei EXIF-GPS:ää eikä GPX-lokia

--- QGIS-taso ---
  293 kuvapistettä → …/projektit/heinavesi_google/maastokuvat.gpkg
  tyyli: gpkg-tyyli ok / qml: Created default style file as …

==============================================================
  Valmis!
  Kuvia albumissa:    300  (EXIF verkosta 299, kirjanpidosta 0)
  Sijoitettu:         293  (EXIF 293, GPX 0)
  Kuvapisteitä tasolla: 293  (kuvaussuunta 0:lla)
  Ilman sijaintia:    7  → …/projektit/heinavesi_google/ei_sijaintia.txt

  Raahaa QGIS:iin:    …/projektit/heinavesi_google/maastokuvat.gpkg
  Kuvat luetaan Google Photosista: taso vaatii verkkoyhteyden ja
  toimii niin kauan kuin albumi on jaettu linkillä.
==============================================================
```

*EXIF verkosta* kertoo montako kuvaa ladattiin nyt ja *kirjanpidosta* montako
saatiin muistista. Toisessa ajossa luvut ovat päinvastoin, eikä verkkoa
käytetä kuvien lukemiseen lainkaan.

Ohitetut kuvat kirjataan myös tiedostoon `ei_sijaintia.txt` projektikansioon,
joten niitä ei tarvitse etsiä ruudun tulosteesta jälkikäteen. Ohitettua kuvaa
ei kopioida projektiin lainkaan, joten voit korjata syyn (esim. antaa puuttuvan
GPX-lokin) ja ajaa saman kansion uudelleen.

---

## 4. Tason avaaminen QGIS:ssä

1. Avaa QGIS.
2. Raahaa **`projektit/[nimi]/maastokuvat.gpkg`** tiedostoselaimesta QGIS-ikkunaan.
3. Taso ilmestyy Layers-paneeliin nimellä `maastokuvat`, symbolit ja kaikki
   asetukset valmiina.

Taustakartan voi lisätä itse, esimerkiksi MML:n maastokartan omasta
projektistasi — tämä ohjelma ei koske projektiisi muuten.

### Kuva näkyviin hiirellä

Kytke päälle **View → Show Map Tips** (löytyy myös nappina Attributes
Toolbarista). Osoita sen jälkeen kuvapistettä: kuva, kuvausaika, korkeus ja
kamera ilmestyvät kuplaan.

> **Jos kupla ei ilmesty:** klikkaa `maastokuvat`-taso aktiiviseksi Layers-
> paneelissa. Karttavihjeet toimivat vain aktiivisella tasolla.

### Kuva isompana

| Haluat | Tee näin |
|---|---|
| Kuva + kaikki tiedot lomakkeella | **Identify Features** → klikkaa pistettä |
| Täysikokoinen kuva katselimeen | **Feature Action** (Attributes Toolbarin pudotusvalikossa) → klikkaa pistettä |

Feature Action avaa alkuperäisen 4032 px kuvan järjestelmän kuvakatselimeen.
Sama löytyy Identify-tuloksista kohdasta *Run Actions* → **Avaa kuva**.

> **Google-albumin taso:** karttavihje ja **Avaa kuva** toimivat normaalisti
> (kuva tulee Googlelta), mutta Identify-lomakkeen kuvaruutu jää tyhjäksi —
> se näyttää levyllä olevan tiedoston, eikä sellaista ole. Muut kentät
> lomakkeella näkyvät kuten ennenkin.

### Symbolit

**Väri kertoo laitteen:**

- **Oranssi** — maasta kuvattu (puhelin tai järjestelmäkamera)
- **Sininen** — drone

**Muoto kertoo suunnan:**

- **Kolmio** — kuvaussuunta tiedossa, kärki osoittaa kuvaussuuntaan
  (0° = pohjoinen, 90° = itä)
- **Pyöreä piste** (maasta) tai **vinoneliö** (drone) — suunta ei tiedossa

Useimmat puhelimet eivät tallenna kuvaussuuntaa, joten pyöreä piste on
normaali tilanne. Dronen tunnistus tulee kuvan EXIF:istä automaattisesti (DJI,
Autel, Parrot, Skydio, Yuneec) — mitään ei tarvitse valita ajossa.

Layers-paneelin kolmio tason nimen edessä avaa selitteen, jossa neljä ryhmää
näkyvät nimillä *Drone · kuvaussuunta tiedossa*, *Drone*,
*Maasta · kuvaussuunta tiedossa* ja *Maasta*. Ryhmän voi piilottaa
raksin poistamalla — esimerkiksi jos haluat katsoa vain dronekuvia.

---

## 5. Kuvaussuunnan täyttäminen käsin

Kun haluat merkitä mihin suuntaan kuva on otettu:

1. **Layer → Toggle Editing** (myös kynäkuvake Digitizing Toolbarissa)
2. **Identify Features** (Ctrl+Shift+I) → klikkaa kuvapistettä
3. Kirjoita **Kuvaussuunta (°)** -kenttään asteluku: 0 = pohjoinen,
   90 = itä, 180 = etelä, 270 = länsi
4. **Layer → Save Layer Edits**, ja lopuksi Toggle Editing pois päältä

Huom: `Ctrl+S` tallentaa QGIS-**projektin**, ei tason muokkauksia. Tason
tallennuksella ei ole pikanäppäintä.

Symboli muuttuu heti nuoleksi. Käsin täytetty suunta **säilyy** kun ajat
ohjelman uudelleen — samoin `Huomio`-kenttään kirjoitettu teksti. Muut kentät
ohjelma kirjoittaa itse, ja ne on siksi lukittu lomakkeessa.

---

## 6. Lisää kuvia samaan projektiin

Aja ohjelma uudelleen ja anna **sama projektin nimi**. Kerro kuvakansio, jossa
uudet kuvat ovat — vanha kansio kelpaa myös, jo tuodut kuvat ohitetaan:

```
  Kuvia tuotu:        16  (EXIF 16, GPX 0)
  Jo tuotu aiemmin:   41
```

Näin voit ottaa kuvia useassa erässä ja ajaa ohjelman aina koko kansiolla
huolehtimatta kaksoiskappaleista. Tunniste on tiedostonimi + kuvausaika.

Jos poistat kuvan `kuvat/`-kansiosta käsin, se tuodaan seuraavassa ajossa
uudelleen. Näin voi korvata huonon kuvan paremmalla.

**Google-albumilla** riittää lisätä kuvat albumiin puhelimessa ja ajaa ohjelma
uudelleen (linkkiin Enter). Vain uusien kuvien EXIF ladataan; vanhat tulevat
kirjanpidosta. Albumista **poistettu** kuva katoaa myös tasolta, koska taso
rakennetaan aina albumin nykyisestä sisällöstä.

Jos mikään ei ole muuttunut, ohjelma sanoo sen eikä kirjoita tasoa turhaan:

```
  41 kuvapistettä — data ja tyyli ennallaan, tasoa ei kirjoitettu uudelleen
  Ei muutoksia committoitavaksi.
```

---

## 7. Taso toiselle koneelle

Kopioi **pelkkä `maastokuvat.gpkg`** (esim. muistitikulla tai pilvessä) ja avaa
se toisella koneella QGIS:ssä. Kuvat tulevat GitHubista, tyyli on tiedoston
sisällä. Levytilaa kuluu kilotavuja.

Verkkoyhteys tarvitaan kuvien näkymiseen. Jos haluat kuvat myös levylle
offline-käyttöön, kloonaa repo:

```bash
git clone https://github.com/MarkusHytonenPD/maastokuvat.git
```

Kevyt vaihtoehto ilman kuvia (552 kt koko repon sijaan) on kuvattu
[README.md](README.md):n kohdassa *Kevyt työkopio toiselle koneelle*.

Google Photos -albumista tehty taso on tässä helpoin: `.gpkg` on muutaman sadan
kilotavun tiedosto, joka toimii millä koneella tahansa ilman repoa tai
kloonausta. Kuvat tulevat suoraan Googlelta niin kauan kuin albumi on jaettu.

---

## 8. Vianetsintä

| Viesti tai oire | Mitä se tarkoittaa |
|---|---|
| `ei EXIF-GPS:ää eikä GPX-lokia` | Kuvassa ei ole koordinaattia. Aja uudelleen ja anna GPX-loki, tai sijoita kuva käsin QGIS:ssä. |
| `GPX-aukko 341 min — loggeri pois päältä?` | Kuva on otettu aikana jolta ei ole GPS-pisteitä. Sijaintia ei arvata. Anna puuttuva loki tai nosta aukkorajaa, jos loggeri vain tallentaa harvakseltaan. |
| `aikaleima GPX-lokien ulkopuolella` | Väärä loki tai väärä päivä. Tarkista että annoit oikean päivän lokin. |
| `ei EXIF-aikaleimaa` | Kuva on käsitelty jossain ohjelmassa joka poisti EXIF:in. Ei korjattavissa jälkikäteen. |
| Kaikki kuvat 3 h väärässä paikassa | Kellodriftiin on annettu tunteja. Anna 0 ja aja uudelleen: aikavyöhyke hoituu itsestään. |
| `⚠ Origin-remotea ei ole` | Työkopio ei ole git-repo. Kuvat ovat silti tallessa paikallisesti. |
| `⚠ Tämän projektin kuvat ovat repossa X` | Projekti kuuluu toiseen repoon kuin tämä työkopio. Osoitteita ei muuteta eikä pushata. Aja projekti oikeassa työkopiossa. |
| Karttavihje ei näy | `View → Show Map Tips` päälle **ja** taso aktiiviseksi Layers-paneelissa. |
| Kuva ei näy vihjeessä toisella koneella | Ei verkkoyhteyttä, tai kuvia ei ole viety GitHubiin. |
| `Albumista ei löytynyt kuvia` | Linkki ei ole voimassa tai albumia ei ole jaettu linkillä. Kokeile linkkiä selaimessa. Jos se toimii selaimessa, Google on muuttanut sivunsa rakennetta — ks. [README.md](README.md), *Google Photos -albumi lähteenä*. |
| `Ei ole Google Photos -jakolinkki` | Linkin pitää alkaa `https://photos.app.goo.gl/` tai `https://photos.google.com/share/`. Albumin nimi tai kuvakaappaus ei kelpaa. |
| `lataus epäonnistui (HTTP 500)` | Googlen ohimenevä virhe. Ohjelma yrittää kolmesti; jos kuva silti jäi väliin, aja uudelleen — kirjanpito lataa vain puuttuvat. |
| `ei ole kuva (video/mp4)` | Albumissa on video. Videoita ei sijoiteta kartalle. |
| Google-albumin kuvat lakkasivat näkymästä | Albumin jakaminen on lopetettu, kuvat poistettu tai verkko poikki. Kuvat eivät ole tallessa projektissa — palauta jako tai aja albumi paikallisena kuvakansiona. |
| Taso näyttää vanhalta QGIS:ssä | Ohjelma kirjoitti `.gpkg`:n uudelleen. Poista taso QGIS:stä ja raahaa uudelleen. |
| Symbolit ovat QGIS:n oletuspalloja | Tyyli ei latautunut. Tason ominaisuudet → Tyyli → Lataa tyyli → `maastokuvat.qml`. |

Sulje taso QGIS:stä ennen ajoa, jos ohjelma valittaa ettei se voi kirjoittaa
GeoPackagea.

---

## 9. Huomioitavaa

- **Kuvat ovat julkisia.** Repo on julkinen, koska QGIS ei saa kuvia privaatista
  reposta. Älä vie kuvia joiden ei pidä näkyä ulkopuolisille. Sama pätee
  Google-albumiin: linkillä jaetun albumin kuvat näkyvät kaikille joilla on
  `.gpkg`-tiedosto, ilman kirjautumista.
- **Google-albumin taso ei ole arkisto.** Kuvat pysyvät vain Googlessa. Jos
  albumin jako loppuu tai kuvat poistetaan, tason kuvat katoavat kaikki
  kerralla. Pitkäaikaiseen säilytykseen aja kuvat paikallisena kuvakansiona,
  jolloin ne kopioidaan projektiin ja GitHubiin.
- **Poistaminen ei riitä.** Kertaalleen pushattu kuva jää git-historiaan, vaikka
  poistat sen myöhemmin. Mieti ennen ensimmäistä vientiä.
- **Alkuperäiset kuvasi jäävät koskematta.** Ohjelma kopioi kuvat eikä muokkaa
  lähdekansiota.
- **Sisarsovellus.** Jos kuvat pitää kiinnittää rakennuksiin ja julkaista
  selainkarttana, käytä `rak_kult_kuvakarttajulkaisu/pipeline.py`:tä. Tämä
  ohjelma sijoittaa kuvat vain omaan koordinaattiinsa QGIS-tasolle.
