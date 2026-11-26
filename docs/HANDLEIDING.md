# Handleiding: Proxyfilter for photo/wallpanel

Deze handleiding gaat stap voor stap van installatie tot een wandpaneel dat alleen nog de updates
krijgt die zijn dashboard nodig heeft. Reken op 10 tot 15 minuten.

**Inhoud**

1. [Wat je nodig hebt](#1-wat-je-nodig-hebt)
2. [Hoe het werkt](#2-hoe-het-werkt)
3. [Installeren](#3-installeren)
4. [Dashboard kiezen en hoe het paneel herkend wordt](#4-dashboard-kiezen-en-hoe-het-paneel-herkend-wordt)
5. [Het paneel naar poort 8124 laten wijzen](#5-het-paneel-naar-poort-8124-laten-wijzen)
6. [Controleren en opschonen](#6-controleren-en-opschonen)
7. [De uitsluitlijst](#7-de-uitsluitlijst)
8. [Afremmen (throttling)](#8-afremmen-throttling)
9. [Instellingen van de add-on](#9-instellingen-van-de-add-on)
10. [Echte client-adressen en bans](#10-echte-client-adressen-en-bans)
11. [Privacy en beveiliging](#11-privacy-en-beveiliging)
12. [Problemen oplossen](#12-problemen-oplossen)

---

## 1. Wat je nodig hebt

- **Home Assistant OS of Supervised** (add-ons hebben de Supervisor nodig), op **aarch64** of **amd64**.
- Een wandpaneel, tablet of fotolijst met de **Home Assistant Companion-app** of een kioskbrowser.

## 2. Hoe het werkt

Een dashboard in Home Assistant abonneert zich op **alle** entiteiten, niet alleen op wat er op het
scherm staat. Bij een grote installatie zijn dat duizenden updates per minuut. Een telefoon merkt
daar weinig van, maar een goedkoop wandpaneel wordt er traag van.

De add-on zit tussen het paneel en Home Assistant. Alles wordt doorgestuurd, alleen het
entiteiten-abonnement van het paneel wordt aangepast. Een entiteit komt bij het paneel als:

1. hij op een van de gekozen dashboards staat (**altijd**), of
2. in de modus *exclude* (standaard) hij niet in de uitsluitlijst staat.

Nieuwe entiteiten komen in de *exclude*-modus vanzelf door, dus niets wat je later toevoegt verdwijnt van het paneel.

## 3. Installeren

1. Ga naar **Instellingen → Add-ons → Add-on-winkel → ⋮ → Repositories** en voeg toe:
   `https://github.com/GruttePier013/nspanel-proxyfilter-wallpanel`
2. Installeer **Proxyfilter for photo/wallpanel** en start hem.
3. Open **Proxyfilter** in de zijbalk. Het blok *Setup* opent vanzelf tot er een dashboard gekozen is
   en een paneel verbinding heeft.

> Installeer via de repository, niet als kopie in `/addons`: lokale add-ons worden nooit bijgewerkt.
> Zet op het tabblad *Info* eventueel **Automatisch bijwerken** aan.

## 4. Dashboard kiezen en hoe het paneel herkend wordt

1. **Kies je dashboard(s):** klik op het gestippelde label van het dashboard dat het paneel opent.
   Wisselt het paneel tussen dashboards, kies ze dan allemaal.
2. **Kies hoe het paneel herkend wordt:**
   - **Aparte poort (aanbevolen):** alles wat via poort **8124** verbindt, wordt gefilterd. Alleen het
     paneel gebruikt 8124; telefoons en browsers houden het gewone adres. Geen tokens of gebruikers nodig.
   - **Op Home Assistant-gebruiker:** één poort voor iedereen, alleen de gekozen gebruiker(s) worden
     gefilterd. Maak eerst een aparte gebruiker voor het paneel (*Instellingen → Personen → Gebruikers*).

## 5. Het paneel naar poort 8124 laten wijzen

In de **Companion-app** op het paneel:

1. **Instellingen → Companion-app → Servers** (of *Server & netwerk*) → tik op je server.
2. Zet de **interne verbindings-URL** op `http://<ip-van-home-assistant>:8124`. Heeft de app ook een
   *externe URL*, zet die dan op hetzelfde adres, zodat hij niet terugvalt op poort 8123.
3. Ga terug naar het dashboard. Toont het paneel nog de oude verbinding, sluit de app dan en open hem opnieuw.

Vind je de instelling niet, verwijder de server dan en voeg hem opnieuw toe met
`http://<ip-van-home-assistant>:8124`, en log in (als de gekozen gebruiker, bij *Op Home Assistant-gebruiker*).

Gebruik je een kioskbrowser of fotolijst-app, zet de start-URL dan op
`http://<ip-van-home-assistant>:8124`, eventueel met het pad van je dashboard
(bijvoorbeeld `/dashboard-wallpanel/0`).

> **Zet poort 8124 nooit open naar het internet.** De add-on weigert standaard publieke adressen.

## 6. Controleren en opschonen

1. Binnen een minuut toont de samenvatting bovenaan `1 / 1` gefilterde verbindingen, en het log
   `ws auth … OK`. Er mag geen waarschuwing `NOT reachable` in het log staan.
2. Zie je de oranje waarschuwing *not set up for reverse proxies*? Volg dan [stap 10](#10-echte-client-adressen-en-bans).
3. Na een paar minuten toont de web-UI de **drukste entiteiten** die nog bij het paneel komen. Klik op
   **exclude** (of een label met jokerteken) en op **Save**. Binnen 30 seconden geldt de nieuwe lijst
   en verbindt het paneel opnieuw; *Traffic removed* loopt op.

## 7. De uitsluitlijst

- Het bestand staat in de **eigen** configuratiemap van de add-on (`addon_configs/…_proxyfilter_wallpanel`,
  via Samba of de File editor) en wordt automatisch aangemaakt met voorbeelden. Bewerk het in de
  web-UI (bij elke opslag blijft een `.bak`-kopie) of met de hand.
- Eén patroon per regel; `*` en `?` zijn jokertekens, `#` begint commentaar:
  `sensor.voorbeeld_omvormer_*`. Een regel uit het add-on-log plakken mag ook; de entiteit wordt eruit gehaald.
- Ongeldige regels worden in de web-UI geweigerd; in een met de hand bewerkt bestand worden ze genegeerd.
- Wijzigingen gelden binnen 30 seconden.

**Altijd beschermd**, ook als een patroon erop past:

1. entiteit-id's die in het dashboard staan;
2. jokertekens in het dashboard, zoals filters van `auto-entities`;
3. alle entiteiten van een **apparaat** of **gebied** waar het dashboard naar verwijst.

Voorbeeld: met `sensor.air_*` in de lijst wordt `sensor.air_monitor_*` geblokkeerd, maar blijft
`sensor.air_mini_*` zichtbaar als het dashboard die gebruikt.

**Een entiteit controleren:** typ een entiteit-id bij **Check an entity**. Je krijgt de exacte reden
waarom hij wel of niet doorkomt.

## 8. Afremmen (throttling)

Entiteiten op je dashboard komen altijd door, ook als ze elke seconde veranderen (vermogensmeters).
De kaart **Throttling** toont de drukste entiteiten met per entiteit een keuzelijst (maximaal één
update per 2 s tot 5 min). Tussenliggende updates worden samengevoegd en de laatste stand wordt
geleverd, dus het paneel toont nooit een verouderde eindwaarde.

## 9. Instellingen van de add-on

Alles heeft een goede standaardwaarde. Dashboards, filterbereik en gebruikers kies je in de web-UI.

| Optie | Standaard | Betekenis |
|---|---|---|
| `upstream` | `http://homeassistant:8123` | adres van Home Assistant, gezien vanuit de add-on |
| `mode` | `exclude` | `exclude`, of `include` (alleen dashboard-entiteiten, streng) |
| `exclude_file` | `proxyfilter_exclude.txt` | pad in de eigen configuratiemap (`.txt` of `.list`) |
| `max_connections` | `20` | maximaal aantal gelijktijdige websocket-verbindingen |
| `local_only` | `true` | verbindingen vanaf publieke IP-adressen weigeren |
| `trusted_proxies` | leeg | een reverse proxy die *vóór* deze add-on staat |
| `heavy_per_minute` | `20` | updates per minuut waarboven een dashboard-entiteit een waarschuwing geeft |
| `top` | `25` | regels per lijst in de lograpporten (0 = geen) |
| `min_per_minute` / `min_per_hour` | `2` / `120` | entiteiten onder deze aantallen verschijnen niet in lograpporten |
| `verbose` | `false` | elk HTTP-verzoek loggen |

De gefilterde poort is **8124**. Een andere poort stel je in onder *Netwerk* op het tabblad
*Configuratie*; de Companion-app moet dan dezelfde poort gebruiken.

**Self-test:** de web-UI heeft een kaart *Self-test* (draait ook bij het starten): Home Assistant
bereikbaar, mappen leesbaar en schrijfbaar, dashboards gevonden, uitsluitlijst bruikbaar. Druk op
*Run again* nadat je iets hebt opgelost.

## 10. Echte client-adressen en bans

Home Assistant ziet de add-on als afzender van elk verzoek. Wil je dat bans na mislukte logins,
"alleen lokaal"-gebruikers en vertrouwde netwerken blijven werken, zet dan in `configuration.yaml`:

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.30.32.0/23
```

en herstart Home Assistant. De add-on controleert dit bij het starten en elke minuut, tot het werkt.
Een `X-Forwarded-For` die een client zelf meestuurt, wordt altijd vervangen door het echte adres.

## 11. Privacy en beveiliging

- De add-on ziet al het verkeer van het paneel, ook logins en tokens, en stuurt het door. Inloggen blijft bij Home Assistant.
- **Filteren is een prestatiefunctie, geen beveiliging:** de add-on kan updates alleen verbergen, nooit meer laten zien dan Home Assistant zou sturen.
- De configuratiemap van Home Assistant is **alleen-lezen** gekoppeld; de add-on schrijft alleen in zijn eigen map en zijn eigen `/data`.
- Tokens worden nooit opgeslagen of gelogd.
- De web-UI is alleen bereikbaar via Home Assistant (alleen beheerders).

Volledig dreigingsmodel (Engels): [SECURITY.md](../SECURITY.md).

## 12. Problemen oplossen

| Probleem | Oplossing |
|---|---|
| "Filtered / open connections" blijft 0 | Het paneel gebruikt `:8124` nog niet. Controleer de server-URL in de Companion-app. |
| Niets gefilterd bij *Op Home Assistant-gebruiker* | De gebruiker van het paneel is niet gekozen, of het log zegt `ws user … passthrough`. De naam moet overeenkomen met de weergavenaam in Home Assistant. |
| Een kaart op het paneel blijft leeg | De entiteit staat in de uitsluitlijst *en* is niet op een gekozen dashboard gevonden (bijv. een YAML-dashboard of een sjabloon in een eigen kaart). **Check an entity** laat zien waarom. |
| Inloggen blijft herhalen | Zoek in het log naar `login … -> 4xx`; controleer `upstream`. |
| Bouwen van de add-on mislukt met een netwerkfout | Het apparaat bereikt de container-registry niet. Controleer DNS/internet (`ha dns restart`) en kies *Opnieuw bouwen*. |
| Filter lijkt vast na een herstart van Home Assistant | Het paneel verbindt vanzelf opnieuw; herstart anders de Companion-app. |

**Beperkingen:** dashboards in YAML-modus staan niet in de web-UI (hun entiteiten zijn niet uit de
opslag te lezen). Zet ze om naar opslagmodus, of sluit hun entiteiten niet uit. Entiteiten die alleen
via sjablonen tijdens het draaien ontstaan, worden niet herkend.

Meer (Engels): [Documentation](../proxyfilter_wallpanel/DOCS.md) · Problemen melden:
[issues](https://github.com/GruttePier013/nspanel-proxyfilter-wallpanel/issues).
