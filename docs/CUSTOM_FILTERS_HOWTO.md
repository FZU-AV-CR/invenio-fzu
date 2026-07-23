# Jak přidat vlastní (custom) filtr do fasetového vyhledávání

Tento dokument popisuje architekturu a přesný postup, jak jsme v tomto
repozitáři implementovali vlastní filtry nad rámec standardních
checkbox facetů (OpenSearch `terms` agregace) -- rozsahové filtry
(min/max), textové substring filtry, přesné (exact-match) filtry a
speciálně sky-position (cone search) filtr pro FRAM.

Cílem je, aby šlo tento vzor v budoucnu replikovat pro další modely
nebo pole, bez nutnosti znovu objevovat stejné detaily/pasti.

## Obsah

1. Přehled architektury (server + klient)
2. Kdy použít který typ filtru
3. Server strana: vlastní `Facet` třída (`facets.py`)
4. Server strana: registrace filtru (`metadata.yaml` `facet-def` vs. `model.py` `AddToDictionary`)
5. Klient strana: input komponenta v `CustomFilters.jsx`
6. Accordion layout (rolování/collapse) a "Clear" tlačítko
7. Sky-position (cone search) -- speciální dvoukolový příklad
8. Časté chyby a jak se jim vyhnout
9. Checklist pro přidání nového filtru

---

## 1. Přehled architektury

Standardní InvenioRDM/oarepo facet = OpenSearch `terms` agregace →
checkbox seznam hodnot v bočním panelu. To funguje dobře pro pole s
malým, opakujícím se počtem hodnot (např. `site`, `ccd`, `manufacturer`).

Pro pole, kde by checkbox seznam byl nepoužitelný (kontinuální čísla,
rozsahly, vysoce kardinální/skoro unikátní řetězce), místo toho
používáme **vlastní `Facet` třídu**, která:

- nevrací žádné agregační "bucket" hodnoty (žádný checkbox seznam),
- pouze **filtruje** výsledky na základě hodnoty, kterou pošle klient.

Tato vlastní `Facet` třída se zaregistruje pod stejným klíčem
(`filters` klíč v react-searchkit), jaký posílá formulářový input v
`CustomFilters.jsx`. Server (`GroupedFacetsParam`/`FacetsParam`) najde
tento klíč ve slovníku `RecordFacets` a zavolá `add_filter(values)` na
odpovídající instanci facetu.

```
[UI input] --(Search button)--> currentQueryState.filters = [[key, value], ...]
                                        |
                                        v
                        react-searchkit → GET /api/<model>?...&<key>=<value>
                                        |
                                        v
                 GroupedFacetsParam.apply() hledá `key` v `self.facets` dict
                                        |
                                        v
                    facets[key].add_filter([value]) -> dsl.Q(...)
```

**Důležité**: Filtr, který není zaregistrovaný v `self.facets`
(server-side dict), je **tiše ignorován** -- žádná chyba, žádný efekt,
vrátí se všechny záznamy. Toto byl zdroj nejvíc matoucích bugů (viz
sekce 8).

---

## 2. Kdy použít který typ filtru

| Typ pole | Vzor | Třída | Příklad |
|---|---|---|---|
| Malý set opakujících se hodnot | checkbox facet (default) | (žádná, oarepo default `TermsFacet`) | `site`, `manufacturer`, `batch` |
| Kontinuální číslo / rozsah | min/max input | `RangeQueryFacet` | `exposure`, `altitude`, `azimuth` |
| Datum jako řetězec `YYYYMMDD` | min/max (date input) | `RangeQueryFacet` | `observation_night` |
| Vysoce kardinální keyword/array, substring hledání | textový input | `TextMatchFacet` | `filename`, `target`, `tray_numbers`, `qr_list`, `components` |
| Pole mimo naše vlastnictví (CCMM/RDM preset), přesná shoda | textový input | `ExactMatchFacet` | `title` (přes `.keyword` sub-pole) |
| Virtuální filtr napříč více poli, žádné jedno pole v `metadata.yaml` | vlastní vstupní formulář | vlastní `Facet` (např. `ConeSearchFacet`) | sky position (RA/Dec/radius) |

---

## 3. Server strana: vlastní `Facet` třída

Každý model má vlastní `models/<model>/facets.py`. Kopíruje se stejný
vzor (žádné sdílení mezi modely -- každý model si drží svou vlastní
kopii, viz `models/fram/facets.py`, `models/sipm/facets.py`,
`models/atlas_itk/facets.py`).

Kostra libovolné "filter-only" (bez agregace) facet třídy:

```python
from invenio_records_resources.services.records.facets import Facet
from invenio_search.engine import dsl

class MyFacet(Facet):
    post_filter = False  # aplikuje se přímo, ne přes post_filter

    def __init__(self, field=None, label=None, **kwargs):
        # DŮLEŽITÉ: field/label MUSÍ být uloženy ručně -- základní
        # dsl.Facet/Facet třída kwargs "field" nepřebírá automaticky
        # do self._params, takže by jinak self._field zůstalo None.
        self._field = field
        self._label = label or ""
        super().__init__(label=label, **kwargs)

    def get_aggregation(self):
        # Minimální agregace -- nezobrazujeme žádné buckets.
        return dsl.A("filter", dsl.Q("match_all"))

    def get_values(self, data, filter_values):
        return {"buckets": []}

    def get_labelled_values(self, data, filter_values):
        # UI šablona čte facet._label přímo -- nutné vrátit i zde.
        return {"buckets": [], "label": str(getattr(self, "_label", ""))}

    def add_filter(self, filter_values):
        """Toto je jádro -- převede hodnoty z URL/filters pole na dsl.Q."""
        if not filter_values:
            return None
        q = None
        for value in filter_values:
            rq = self._build_query(value)   # vlastní parsovací logika
            if rq is None:
                continue
            q = rq if q is None else q | rq
        return q
```

Existující implementace v repozitáři (všechny dědí přesně z tohoto
vzoru, liší se jen v `_build_query`/`add_filter` logice):

- **`RangeQueryFacet`** (`models/fram/facets.py`) -- parsuje
  `"min..max"` řetězec (kterýkoliv konec může chybět), vrací
  `dsl.Q("range", **{field: {"gte":..., "lte":...}})`. Hodnoty se
  pokusí converovat na `int`/`float`, jinak zůstanou string (funguje
  i pro lexikograficky řazené `YYYYMMDD` keyword pole).
- **`TextMatchFacet`** (ve všech třech modelech) -- bere prostý
  string, escapuje `*`/`?`, vrací
  `dsl.Q("wildcard", **{field: {"value": f"*{escaped}*", "case_insensitive": True}})`.
  Funguje i na `array` polích s `keyword` items (OpenSearch/Lucene
  indexuje každý prvek pole zvlášť, wildcard matchne, pokud sedí
  JAKÝKOLIV prvek).
- **`ExactMatchFacet`** (`models/fram/facets.py`) -- `dsl.Q("term", **{field: value})`,
  používá se pro pole, která nevlastníme (např. `title` z CCMM presetu).
- **`ConeSearchFacet`** (`models/fram/facets.py`) -- viz sekce 7,
  speciální dvoukolový vzor.

---

## 4. Server strana: registrace filtru

Existují **dva** způsoby registrace, podle toho, jestli filtr patří
k jednomu konkrétnímu poli v `metadata.yaml`, nebo je to "virtuální"
filtr bez odpovídajícího pole.

### 4a. Standardní pole -> `facet-def` v `metadata.yaml`

```yaml
exposure:
  type: float
  facet-def:
    facet: models.fram.facets.RangeQueryFacet
    field: metadata.exposure       # POVINNÉ -- viz sekce 8, past č. 1
    label:
      en: Exposure
      cs: Expozice
```

**KRITICKY DŮLEŽITÉ**: pokud zapíšete `facet-def`, oarepo NEDOPLNÍ
`field`/`label` automaticky (to se děje jen když `facet-def` úplně
chybí a použije se default `TermsFacet`). Musíte vždy explicitně
napsat `field:` a `label:` uvnitř `facet-def` bloku, jinak
`self._field` zůstane `None` a chyba se projeví matoucím
`TypeError: keywords must be strings` hluboko v `dsl.Q(...)`.

Toto se používá pro:
- `models/fram/metadata.yaml`: `target`, `observation_night`,
  `exposure`, `alt_az.altitude`, `alt_az.azimuth`, `filename`.
- `models/sipm/metadata.yaml`: `tray_numbers`, `qr_list`.
- `models/atlas_itk/metadata.yaml`: `components`, `component_types`,
  `files`.

### 4b. Virtuální filtr (žádné jedno pole) -> `AddToDictionary` v `model.py`

Pro filtry, které nemají 1:1 odpovídající pole (`cone_search`) nebo
patří k poli, které nevlastníme (`title` z CCMM presetu), se facet
injektuje přímo do generovaného `RecordFacets` slovníku:

```python
from oarepo_model.customizations import AddToDictionary
from .facets import ConeSearchFacet, ExactMatchFacet

customizations=[
    ...
    AddToDictionary(
        "RecordFacets",
        {"cone_search": ConeSearchFacet(
            field="metadata.healpix_idx",
            footprint_field="metadata.footprint",
        )},
    ),
    AddToDictionary(
        "RecordFacets",
        {"metadata.title": ExactMatchFacet(field="metadata.title.keyword")},
    ),
    ...
]
```

Klíč v prvním argumentu `AddToDictionary("RecordFacets", {KLÍČ: facet})`
musí **přesně** odpovídat `filterKey` řetězci, který posílá JSX (viz
sekce 5).

### AddFacetGroup vs. RecordFacets

`AddFacetGroup(name="default", facets=[...])` řídí, které facety se
zobrazí jako **browsable checkbox seznam** (agregační buckety) v
bočním panelu. `RecordFacets` slovník (do kterého `AddFacetGroup` i
`facet-def` i `AddToDictionary` všechny nakonec zapisují) je plný
seznam VŠECH registrovaných filtrů, které server rozezná v query
parametrech -- bez ohledu na to, jestli jsou v `AddFacetGroup` nebo
ne.

**Proto**: filtr NEMUSÍ být v `AddFacetGroup`, aby fungoval jako
filtr -- `AddFacetGroup` ovlivňuje jen to, jestli se zobrazí
checkbox/bucket seznam. Filtry z `CustomFilters.jsx` (min/max, text,
cone search) typicky **nejsou** v `AddFacetGroup` vůbec (nemají žádný
browsable bucket seznam, jen input formulář) -- viz `metadata.altitude`,
`metadata.azimuth`, `cone_search` atd., které v žádném z modelů nejsou
v `AddFacetGroup`.

Pole, která byla vyřazena z `AddFacetGroup` a nahrazena textovým
filtrem (`tray_numbers`, `qr_list`, `components`, `component_types`,
`files`), je proto potřeba pouze:
1. odebrat z `AddFacetGroup` (aby nezobrazovala nepoužitelný checkbox
   seznam s tisíci hodnotami),
2. zaregistrovat `facet-def` (aby filtr fungoval),
3. přidat input do `CustomFilters.jsx`.

---

## 5. Klient strana: input komponenta v `CustomFilters.jsx`

Každý model má `ui/<model>/semantic-ui/js/<model>/search/CustomFilters.jsx`,
zaregistrovaný jako `SearchApp.facets` override v `search/index.js`:

```js
// search/index.js
import CustomFilters from "./CustomFilters";
...
export const componentOverrides = {
  [`${overridableIdPrefix}.ResultsList.item`]: ResultsListItem,
  [`${overridableIdPrefix}.SearchApp.facets`]: CustomFilters,
};
```

`CustomFilters` komponenta nejdřív vyrenderuje standardní checkbox
facety (`<SearchAppFacets {...props} />` -- to, co je v
`AddFacetGroup`), a pak pod tím vlastní accordion panely s
input-based filtry.

### Pomocné funkce pro práci s `filters` polem

React-searchkit drží aktivní filtry jako pole `[key, value]` dvojic v
`currentQueryState.filters`. Přidání/odebrání konkrétního filtru
(beze změny ostatních) se dělá přes dvě pomocné funkce, které jsou v
každém `CustomFilters.jsx` nahoře:

```js
const withFilter = (filters, key, value) => [
  ...(filters || []).filter((f) => f[0] !== key),
  ...(value != null ? [[key, value]] : []),
];

const withoutFilter = (filters, key) =>
  (filters || []).filter((f) => f[0] !== key);
```

### Vzor jednoho filtru (textový substring, `makeTextFilter` factory)

```jsx
const makeTextFilter = (filterKey, labelText, placeholderText) => {
  const TextFilterComponent = ({
    currentQueryState,
    updateQueryState,
    active,
    onToggle,
  }) => {
    const [value, setValue] = useState("");

    const apply = () => {
      if (!value) return;
      updateQueryState({
        ...currentQueryState,
        filters: withFilter(currentQueryState.filters, filterKey, value),
      });
    };

    const clear = () => {
      setValue("");
      updateQueryState({
        ...currentQueryState,
        filters: withoutFilter(currentQueryState.filters, filterKey),
      });
    };

    return (
      <FilterPanel label={labelText} active={active} onToggle={onToggle}>
        <Form.Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholderText}
        />
        <Button.Group size="small" fluid>
          <Button primary onClick={apply} type="button">{i18next.t("Search")}</Button>
          <Button basic onClick={clear} type="button">{i18next.t("Clear")}</Button>
        </Button.Group>
      </FilterPanel>
    );
  };
  ...
  return withState(TextFilterComponent);   // withState = react-searchkit HOC,
                                            // poskytuje currentQueryState/updateQueryState
};

const FilenameFilter = makeTextFilter(
  "metadata.filename",
  i18next.t("Filename"),
  i18next.t("e.g. 20170814041208-419-RA.fits")
);
```

Klíčové věci:
- `filterKey` (první argument, např. `"metadata.filename"`) musí
  **přesně** odpovídat klíči, pod kterým je facet zaregistrovaný na
  serveru (`facet-def` field name, nebo `AddToDictionary` klíč).
- `withState(...)` (react-searchkit) obalí komponentu a předá jí
  `currentQueryState`/`updateQueryState` -- BEZ toho nemá komponenta
  přístup k aktivním filtrům.
- Tlačítko "Search" volá `apply()` explicitně (na rozdíl od
  standardních checkbox facetů, které aplikují okamžitě při kliknutí)
  -- to je záměr, protože uživatel potřebuje nejdřív dopsat celou
  hodnotu (min i max, celé RA/Dec/radius) předtím, než se odešle dotaz.
- Tlačítko "Clear" vyprázdní lokální React state (`setValue("")`) A
  odstraní filtr z `currentQueryState.filters`.

### Vzor rozsahového filtru (min/max, `makeRangeFilter` factory)

Stejný vzor jako textový, jen `apply()` sestaví jeden string
`"${min}..${max}"` (kterýkoliv konec může být prázdný):

```jsx
const apply = () => {
  const minNum = min === "" ? null : parseFloat(min);
  const maxNum = max === "" ? null : parseFloat(max);
  if ((minNum !== null && Number.isNaN(minNum)) ||
      (maxNum !== null && Number.isNaN(maxNum)) ||
      (minNum === null && maxNum === null)) {
    return; // validace -- nic neposílej, pokud jsou obě pole prázdná/neplatná
  }
  updateQueryState({
    ...currentQueryState,
    filters: withFilter(
      currentQueryState.filters,
      filterKey,
      `${minNum !== null ? minNum : ""}..${maxNum !== null ? maxNum : ""}`
    ),
  });
};
```

Tento string `"min..max"` je přesně to, co `RangeQueryFacet.add_filter`
na serveru očekává a parsuje (`value.partition("..")`).

---

## 6. Accordion layout (rolování) a Clear

Aby se do jednoho úzkého bočního panelu vešlo víc filtrů najednou
(cone search, night, altitude, azimuth, exposure, target, filename,
title...), je každý filtr zabalený do sdíleného `FilterPanel`
wrapperu, který používá Semantic UI `Accordion`:

```jsx
const FilterPanel = ({ label, active, onToggle, children }) => (
  <>
    <Accordion.Title active={active} onClick={onToggle}>
      <Icon name="dropdown" />
      {label}
    </Accordion.Title>
    <Accordion.Content active={active}>
      <Form size="small">{children}</Form>
    </Accordion.Content>
  </>
);
```

`active`/`onToggle` NENÍ vlastněno jednotlivým filtrem, ale rodičovskou
`CustomFilters` komponentou, přes jednoduchý `openPanels` state
(klíčováno interním identifikátorem panelu, NE server-side filter
klíčem -- viz komentář v `FILTER_PANELS`):

```jsx
export const CustomFilters = (props) => {
  const [openPanels, setOpenPanels] = useState({});
  const togglePanel = (key) =>
    setOpenPanels((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <>
      <SearchAppFacets {...props} />
      <Accordion exclusive={false} styled fluid className="custom-filters-accordion">
        {FILTER_PANELS.map(({ key, Component }) => (
          <Component key={key} active={!!openPanels[key]} onToggle={() => togglePanel(key)} />
        ))}
      </Accordion>
    </>
  );
};
```

`exclusive={false}` na `<Accordion>` dovoluje mít otevřených víc
panelů najednou (např. Altitude + Azimuth zároveň) -- Semantic UI
default by jinak zavíral ostatní panely při otevření nového.

`FILTER_PANELS` pole na konci souboru definuje pořadí zobrazení a
mapuje interní `key` (jen pro `openPanels` state, nezávislé na
server-side filter klíči) na komponentu:

```jsx
const FILTER_PANELS = [
  { key: "cone_search", Component: ConeSearchInputs },
  { key: "observation_night", Component: NightFilter },
  { key: "altitude", Component: AltitudeFilter },
  ...
];
```

Pro přidání nového filtru do UI tedy stačí: (1) vytvořit komponentu
(přes `makeTextFilter`/`makeRangeFilter` factory, nebo vlastní), (2)
přidat řádek do `FILTER_PANELS`.

---

## 7. Sky-position (cone search) -- speciální dvoukolový příklad

Cone search (`ConeSearchFacet` v `models/fram/facets.py`) je
nejsložitější příklad, protože kombinuje:

1. **Virtuální registraci** (sekce 4b) -- klíč `"cone_search"`
   neodpovídá žádnému jednomu poli v `metadata.yaml`.
2. **JSON hodnotu místo prostého stringu** -- JSX pošle
   `JSON.stringify({ lat, lon, radius })` místo `"min..max"` nebo
   prostého textu:

   ```jsx
   const lon = raNum > 180 ? raNum - 360 : raNum; // RA 0-360 -> lon -180..180
   updateQueryState({
     ...currentQueryState,
     filters: withFilter(
       currentQueryState.filters,
       "cone_search",
       JSON.stringify({ lat: decNum, lon, radius: radiusNum })
     ),
   });
   ```

3. **Dvě kola dotazu, spojená AND (`&`)**:
   - **Kolo 1** (hrubý filtr, vždy aplikovaný): `healpix_idx` pole je
     HEALPix (NSIDE=64) index pixelu STŘEDU záběru, spočítaný při
     nahrání záznamu. `hp.query_disc()` vrátí seznam pixelů v okruhu
     `radius + MAX_FOV_RADIUS_DEG` (rozšířeno o max. možný poloměr
     zorného pole, aby se nikdy neztratil false negative -- viz
     docstring `MAX_FOV_RADIUS_DEG` v `facets.py`). Výsledek: `dsl.Q("terms", **{"metadata.healpix_idx": [...]})`.
   - **Kolo 2** (přesná kontrola, AND): `footprint` pole (GeoJSON
     polygon skutečného pokrytí záběru, `geo_shape` mapping) se
     porovná s `circle` tvarem o poloměru = **skutečný** uživatelův
     radius (BEZ rozšíření z kola 1) pomocí `geo_shape`
     `intersects` query. Toto odfiltruje false positivy, které kolo 1
     kvůli rozšířenému poloměru propustilo.

```python
def _build_cone_query(self, value):
    params = json.loads(value)
    lat, lon, radius = float(params["lat"]), float(params["lon"]), float(params["radius"])
    round1 = self._build_round1_query(lat, lon, radius)   # terms na healpix_idx
    round2 = self._build_round2_query(lat, lon, radius)   # geo_shape na footprint
    return round1 & round2
```

4. **OpenSearch mapping override** (`PatchIndexPropertyMapping` v
   `model.py`) -- `center_geo` a `footprint` jsou v `metadata.yaml`
   deklarovány jako `object`/`dynamic-object` (protože oarepo
   nepodporuje `geo_point`/`geo_shape` nativně jako typ pole), takže
   se jejich vygenerovaný OpenSearch mapping ručně přepíše:

   ```python
   PatchIndexPropertyMapping(
       "metadata.center_geo",
       {"type": "geo_point", "properties": None, "dynamic": None},
   ),
   PatchIndexPropertyMapping(
       "metadata.footprint",
       {"type": "geo_shape", "properties": None, "dynamic": None, "ignore_above": None},
   ),
   ```

   Toto je nutné spustit/ověřit po `./run.sh reset` (přegenerování
   indexu) -- `PatchIndexPropertyMapping` je vstup do generování
   mappingu, ne výstup, takže přežije i `./run.sh update`.

Registrace v `model.py`:

```python
AddToDictionary(
    "RecordFacets",
    {"cone_search": ConeSearchFacet(
        field="metadata.healpix_idx",
        footprint_field="metadata.footprint",
    )},
),
```

---

## 8. Časté chyby a jak se jim vyhnout

### Past č. 1: chybějící `field:`/`label:` v `facet-def`

Pokud `facet-def` blok obsahuje jen `facet: ...` bez explicitního
`field:`, `self._field` v konstruktoru zůstane `None`. Projeví se to
matoucím `TypeError: keywords must be strings` z `dsl.Q("range", **{None: ...})`,
daleko od skutečné příčiny. **Vždy** pište `field:` explicitně.

### Past č. 2: filtr není v `RecordFacets` -> tiché ignorování

Pokud klíč, který JSX posílá (`filterKey`), neodpovídá přesně žádnému
klíči v `RecordFacets` (ani přes `facet-def`, ani přes
`AddToDictionary`), server vrátí `200 OK` a **všechny** záznamy --
bez chybové hlášky. Vždy si dvakrát ověřte, že:
- `filterKey` v JSX (`makeTextFilter("metadata.tray_numbers", ...)`)
- `field:` v `facet-def` YAML (`field: metadata.tray_numbers`)
- (nebo klíč v `AddToDictionary("RecordFacets", {"KLÍČ": ...})`)

...jsou identické řetězce.

### Past č. 3: kolize cesty u vnořených objektů (`path.endswith(key)` bug)

Objevili jsme bug v `oarepo_model`'s `ObjectDataType.get_facet()`: pokud
rodičovský objekt končí stejným textem jako název dceřiného pole
(např. rodič `altitude_azimuth`, dítě `azimuth` -- `"altitude_azimuth".endswith("azimuth")`
je `True`), vygeneruje se špatná facet cesta (chybí `.azimuth` suffix),
což ticho rozbije filtr přesně jako past č. 2. **Řešení**: pojmenovat
rodičovský objekt tak, aby jeho název nekončil stejně jako název
žádného dceřiného pole (v repozitáři: přejmenováno `altitude_azimuth`
→ `alt_az`).

### Past č. 4: wire formát query parametru

Nepředpokládejte formát URL parametru (`facets[key]=value` vs. bare
`key=value`) -- ověřte to vždy v DevTools Network tab / server logu.
V tomto projektu react-searchkit posílá **bare** `key=value` (ne PHP
style `facets[key]=value`).

### Past č. 5: `_label` atribut a UI šablona

UI šablona pro zobrazení facetů přistupuje k `facet._label` přímo.
Pokud vaše vlastní `Facet` třída nepoužívá `LabelledFacetMixin`, MUSÍTE
nastavit `self._label = label or ""` ručně v konstruktoru, jinak
`AttributeError`.

---

## 9. Checklist pro přidání nového filtru

1. [ ] Rozhodnout typ filtru (rozsah / text substring / exact match /
       virtuální) -- viz tabulka v sekci 2.
2. [ ] Pokud žádná vhodná třída neexistuje v `models/<model>/facets.py`,
       přidat ji (zkopírovat vzor z existující třídy).
3. [ ] Zaregistrovat na serveru:
   - Standardní pole → `facet-def` v `metadata.yaml`, **vždy** s
     explicitním `field:` a `label:`.
   - Virtuální/cizí pole → `AddToDictionary("RecordFacets", {...})` v
     `model.py`.
4. [ ] Pokud pole bylo dosud v `AddFacetGroup` (checkbox seznam),
       odebrat ho odtud (jinak bude mít nepoužitelně dlouhý bucket
       seznam navíc k novému textovému filtru).
5. [ ] V `CustomFilters.jsx`: vytvořit komponentu přes
       `makeTextFilter`/`makeRangeFilter` (nebo custom, jako
       `ConeSearchInputsComponent`), `filterKey` musí přesně odpovídat
       serverovému klíči z kroku 3.
6. [ ] Přidat záznam do `FILTER_PANELS` pole (pořadí zobrazení).
7. [ ] Ověřit end-to-end: DevTools Network tab -- zkontrolovat přesný
       query parametr v požadavku, a že filtr skutečně omezí výsledky
       (ne "200 OK ale beze změny", což signalizuje past č. 2/3).
8. [ ] Pokud jde o geo/prostorové pole -- zkontrolovat, že OpenSearch
       mapping je patchnutý přes `PatchIndexPropertyMapping` a že index
       byl přegenerován (`./run.sh reset`).

---

## Reference na existující soubory

| Model | Facets | Metadata (facet-def) | UI CustomFilters |
|---|---|---|---|
| FRAM | `models/fram/facets.py` | `models/fram/metadata.yaml` | `ui/fram/semantic-ui/js/fram/search/CustomFilters.jsx` |
| SiPM | `models/sipm/facets.py` | `models/sipm/metadata.yaml` | `ui/sipm/semantic-ui/js/sipm/search/CustomFilters.jsx` |
| Atlas ITk | `models/atlas_itk/facets.py` | `models/atlas_itk/metadata.yaml` | `ui/atlas_itk/semantic-ui/js/atlas_itk/search/CustomFilters.jsx` |

Registrace facetů v Pythonu (AddFacetGroup, AddToDictionary,
PatchIndexPropertyMapping): `models/<model>/model.py`.
