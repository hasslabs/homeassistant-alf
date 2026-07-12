# Alf (Länsförsäkringar) - Home Assistant-integration

**🇸🇪 Svenska** | [🇬🇧 English](README.en.md)

Läser in all statistik från dina **Alf**-enheter (och kan valfritt styra smarta plugg) i Home
Assistant via samma `lfhub.net`-moln-API som Alf-appen använder - **utan att röra Alf-hubben**, så
försäkringsrabatten och den bemannade larmcentralen påverkas inte.

Alf är Länsförsäkringars white-label av Onics/Develco (varumärket *frient*). Hubben är avsiktligt låst
(inget lokalt API), så integrationen pratar med molnet i stället. API:t kartlades genom att
reverse-engineera Android-appen - se [`docs/api/alf-cloud-api.md`](docs/api/alf-cloud-api.md).

## Vad du får

- **Binära sensorer:** rök, läcka, rörelse, öppning, manipulering och anslutning per enhet.
- **Sensorer:** temperatur, luftfuktighet, effekt, energi, ljusstyrka, batteri (% eller volt).
- **Switchar** (valfritt, av som standard): smart plugg på/av.

Entiteterna byggs generiskt från varje enhets `features[]`, så nya enhetstyper dyker upp automatiskt.
Enheter grupperas under sin gateway; rum mappas till områden.

## Enheter och vad varje entitet betyder

Ovanliga/okända signaler exponeras som **diagnostik**-entiteter (dolda under "Diagnostik" på
enhetssidan), så inget tappas bort och inget felmärks.

### Smart plugg (frient)
- **Plugg** - på/av-switch (endast när styrning är aktiverad).
- **Effekt** (W) - momentan effektförbrukning.
- **Energi** (Wh) - ackumulerad förbrukning (`total_increasing`).

### Brandvarnare (frient)
- **Rök** - brand/rök upptäckt.
- **Temperatur** (°C).

### Läckdetektor (frient)
- **Läcka** - fukt/översvämning upptäckt vid sensorn.
- **Temperatur** (°C).

### LeakBot (fastklämd på inkommande vattenröret)
LeakBot ligger *inte i* vatten som en vanlig läckpuck. Den kläms fast på det **kalla** inkommande
röret precis efter huvudkranen och känner av **temperatur** ("Thermi-Q"): när vatten rinner kyls
röret, och en dold läcka gör att vatten rinner hela tiden så röret hålls kallt i ett avslöjande
mönster. Utifrån det härleds dessa signaler:

| Entitet | Kan visa | Normalt | Vad det betyder / om den avviker |
|---|---|---|---|
| **Läcka** | `Läcka` / `Torrt` | **Torrt** | LeakBots samlade läck-bedömning. `Läcka` = den tror det läcker på tilloppet. **Det är den här du bygger automationer/notiser på.** |
| **Högt vattenflöde** | `Av` / `På` | **Av** | Rå diagnostik-bit. `På` = vatten har runnit stadigt längre än normal användning förklarar (möjlig läcka). Tolkad, ej verifierad - bygg inte larm på den. |
| **Varmt rör** | `Av` / `På` | **Av** | Rå diagnostik-bit. `På` = röret den klämmer på är för varmt för att mäta läckor tillförlitligt (troligen fel rör). Tolkad, ej verifierad. |
| **Lossnat från röret** | `Av` / `På` | **Av** | Rå diagnostik-bit, **opålitlig** - vissa enheter som sitter korrekt visar ändå `På`. Därför **avstängd som standard**. Lita inte på den för att avgöra om klämman lossnat. |
| **Problem** | `OK` / `Problem` | **OK** | Hårdvaruhälsa på själva enheten. `Problem` = fel på enheten (behöver ses över). |
| **Anslutning** | `Ansluten` / `Frånkopplad` | **Ansluten** | `Frånkopplad` = enheten är offline (batteri, räckvidd eller hubben nere). |

**En frisk LeakBot:** Läcka = `Torrt`, Problem = `OK`, Anslutning = `Ansluten`.

Högt vattenflöde / Varmt rör / Lossnat är **råa, tolkade diagnostik-bitar** (inte verifierade fel-larm),
så de visas som vanliga `Av`/`På`-sensorer under Diagnostik - inte som röda "Problem". Speciellt
**Lossnat från röret är opålitlig** (kan visa `På` fast klämman sitter kvar) och är därför avstängd som
standard. **Läcka**, **Problem** och **Anslutning** är de du bygger automationer på.

> Betydelserna för Högt vattenflöde / Varmt rör / Lossnat är härledda ur LeakBots Thermi-Q-mekanik och
> API-fältnamnen, inte bekräftade. Om **Läcka** visar `Läcka` medan allt är torrt: kolla Alf-appen - det
> kan vara en äkta smygläcka att utreda.

### Gateway (Develco) och batterier
- **Anslutning** - hubben är online. (Dess interna `mode`/`scan`-inställningar exponeras inte.)
- Batterienheter får en **Batteri** (%) eller **Batterispänning** (V) som diagnostik-sensor.

## Inloggning (BankID-QR, sedan på egen hand)

Inloggning sker med BankID. När du lägger till integrationen visar Home Assistant en **BankID-QR-kod**
- skanna den i BankID-appen ("Skanna QR-kod") och godkänn. Ingen inklistring av token. Baksidan är
Keycloak OIDC: access-token gäller i 5 dygn och refresh-token i 30 dygn och **roterar vid varje
förnyelse**, så efter den enda inloggningen kör integrationen vidare på egen hand i all evighet. Den
roterade refresh-token sparas automatiskt; om sessionen någon gång går ut ber Home Assistant dig logga
in med BankID igen (reauth).

## Klienthemligheten (client secret)

Android-klienten är konfidentiell, så tokenförnyelse kräver en statisk `client_secret`. Det är en
**icke-personlig app-hemlighet** - identisk för varje Alf-installation och dessutom extraherbar ur
APK:n - så den är **inbyggd i integrationen** (`custom_components/alf/const.py`). Den är värdelös på
egen hand: varje session kräver ändå din egen BankID-inloggning. Inget du behöver konfigurera.

## Installera via HACS (rekommenderas)

[![Öppna i HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hasslabs&repository=homeassistant-alf&category=integration)

1. HACS -> trepunktsmenyn -> **Custom repositories** -> lägg till
   `https://github.com/hasslabs/homeassistant-alf`, kategori **Integration** (eller klicka på knappen).
2. Installera **Alf** och starta om Home Assistant.
3. Inställningar -> Enheter och tjänster -> Lägg till integration -> **Alf**, och **skanna BankID-QR:en**.

## Installera manuellt

1. Kopiera `custom_components/alf/` till din HA:s `config/custom_components/`.
2. Starta om Home Assistant.
3. Inställningar -> Enheter och tjänster -> Lägg till integration -> **Alf**. En BankID-QR-kod visas -
   skanna den i BankID-appen ("Skanna QR-kod") och godkänn. Bocka i "Aktivera styrning" i sista steget
   om du vill ha plugg-switchar.
4. Styrning kan även slås på senare via Integration -> Konfigurera.

## Inte för livskritisk timing

Home Assistant pollar molnet (~45 s), så läck-/rökändringar här släpar något. Alf:s larmcentral är kvar
som realtids-säkerhetsväg; den här integrationen är för överblick, historik och automationer.

## Utveckling

- `alfcloud/` är en fristående, enhetstestad async-klient (tokenförnyelse + rotation, homes/devices,
  styrning). Kör `python -m pytest`. Den är **vendrad** in i `custom_components/alf/alfcloud/` för
  leverans - kopiera om efter ändringar: `Copy-Item alfcloud/*.py custom_components/alf/alfcloud/`.
- Recon-verktyg, spec och planer ligger under `recon/` och `docs/`.

## Juridiskt

Inofficiell interoperabilitet för personligt bruk med ditt eget Alf-konto. API:t är inte offentligt och
kan ändras utan förvarning. Inga personliga uppgifter är incheckade - endast appens icke-personliga
`client_secret` (se ovan).
