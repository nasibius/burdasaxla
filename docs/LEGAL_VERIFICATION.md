# Legal verification of the BurdaSaxla rule engine

**Source checked:** “Yol hərəkəti haqqında” Azərbaycan Respublikasının Qanunu, **No. 517-IQ, 03.07.1998**,
status *Qüvvədədir* (in force). Official consolidated text from the state legal-acts register
**e-qanun.az, framework 3423** — <https://e-qanun.az/framework/3423>.

* Retrieved: **2026-11-12** (file `frameworks/3/f_3423.html`, SHA-256 prefix `4c8a39851a93a3e8`).
* The text includes the latest amendment, **471-VIIQD of 14.07.2026** (in force 28.07.2026). That amendment changes
  Articles 30, 46-2, 53 and 84, **not** Articles 48, 52, 64 or 69.
* e-qanun lists versions up to 01.05.2026 (`v_3423_6`). The consolidated file served on the retrieval date was used.

**Method.** I downloaded the official text and read the relevant articles in full. Each rule in
`backend/app/rules.py` was checked against them. Quotes below are copied from the official text.
I am not a lawyer: this is a documented reading of the text, to be confirmed by the team's legal reviewer.

Verification levels used in the app:

| Level | Meaning |
|---|---|
| **verified_text** | The condition (and distance, if any) is stated in the quoted text. |
| **interpretation** | The text is verified, but how we apply it to map geometry or scope is our reading. |
| **heuristic** | The law states the condition only qualitatively; the number we use is our estimate. Never RED. |

## Key definitions (Art. 1)

| Art. | Term | Official text (excerpt) | Consequence for the app |
|---|---|---|---|
| 1.29 | *dayanma* (stopping) | “adamların minməsi və ya düşməsi, yaxud yüklərin yığılması və ya boşaldılması üçün zəruri olan vaxt ərzində nəqliyyat vasitəsinin hərəkətsiz vəziyyətə gətirilməsidir” | A passenger pick-up/drop-off **is dayanma**. The map answers “may I stop (dayanma) here?”. |
| 1.31 | *durma* (standing/parking) | “... digər səbəblərə görə hərəkətsiz vəziyyətə gətirilmişdirsə və onun dayanması adamların minməsi və ya düşməsi ... üçün zəruri olan vaxtdan ...” | Restrictions on *durma* (3.28, 1.10) **do not** forbid a drop-off. |
| 1.11 | *yolayrıcı* (intersection) | “yolların bir səviyyədə hər hansı kəsişməsi, birləşməsi və ya şaxələnməsi ...” | Intersections are computed from the road graph. |
| 1.15-1, 1.15-3 | *velosiped zolağı*, *velosiped yolu* | “velosiped yolu – ... velosiped cığırı və ya zolağıdır” | A painted bike lane is a “bicycle road”, so 52.IV.10-1 applies to it. |
| 1.44 | *ümumi istifadədə olan nəqliyyat vasitəsi* | “... müəyyən edilmiş marşrut üzrə təyin edilmiş dayanacaqlarla hərəkət edən nəqliyyat vasitəsidir (avtobus, trolleybus, tramvay)” | “Public transport” = bus, trolleybus, tram. **Taxis are not included**, so 52.IV-I (stops only at designated places) does not apply to taxis or private cars. |

## Rules, sources and implementation status

| Rule id | Legal source | Exact condition (official text) | Exceptions | Effect in app | Level | Status vs v1 |
|---|---|---|---|---|---|---|
| PEDESTRIAN_CROSSING | 52.IV.4 | “piyada keçidlərində və onlara 5 metrdən az yaxınlıqda” | — | RED, crossing ±(2 m + 5 m) on **both** sides | verified_text (crossing width estimated) | **Fixed.** v1 applied 5 m only *before* the crossing (a Russian PDD reading). |
| INTERSECTION | 52.IV.6 | “hərəkət hissələrinin kəsişməsində və kəsişən hərəkət hissəsinin kənarından 5 metrdən az yaxınlıqda” | T-junction: opposite the side road if there is a 1.1–1.4 line or a dividing strip | RED; opposite side of a T-junction → **YELLOW** (T_JUNCTION_EXCEPTION) | verified_text (edge estimated from width/lanes) | **Exception added.** |
| BUS_STOP | 52.IV.7 | “dayanacaq meydançasına, meydança olmadıqda isə ... 5.12 və ya 5.13 yol nişanlarına 15 metrdən az yaxınlıqda” | — | RED 15 m from the stop sign or platform ends, on the stop's side | verified_text | **Fixed:** measured from platform ends; rail/metro platforms excluded (Art. 1.44). |
| BUS_LANE_SOLID / _DASHED / _UNKNOWN_LINE | 48.IV | “... digər nəqliyyat vasitələrinin həmin zolaqda hərəkəti və dayanması qadağandır. Əgər ... qırıq-qırıq nişanlama xətti ilə ... ayrılmışdırsa, ... hərəkət hissəsinin sağ kənarında sərnişinlərin minməsi və düşməsi üçün bu zolağa keçməyə icazə verilir, lakin bu, ümumi istifadədə olan nəqliyyat vasitələri üçün maneə yaratmamalıdır.” | **Dashed line: drop-off allowed** (without obstructing buses) | Solid → RED; dashed → info; unknown (all OSM data) → **YELLOW** | verified_text | **Fixed.** v1 made every bus lane RED. |
| TUNNEL | 52.IV.2 | “tunellərdə” | — | RED | verified_text | — |
| BRIDGE / BRIDGE_LANES_UNKNOWN | 52.IV.2 | “estakadalarda, körpülərdə (əgər həmin istiqamətdə üçdən az hərəkət zolağı varsa)” | ≥ 3 lanes in that direction: not prohibited by this clause | < 3 lanes → RED; ≥ 3 → no restriction; unknown → **YELLOW** | verified_text | **Fixed.** v1 made every bridge RED. |
| UNDER_BRIDGE | 52.IV.2 | “... və onların altında” | — | RED under the structure | **interpretation** (scope of “onların altında”) | — |
| LEVEL_CROSSING | 52.IV.2 | “dəmiryol keçidlərində” | — | RED ±6 m | verified_text (extent estimated) | — |
| MOTORWAY | 52.IV.11 | “avtomagistrallarda ... 5.15 və ya 6.11 ... meydançalarından kənarda” | marked rest areas | RED | interpretation (OSM motorway = legal avtomagistral) | none in area |
| ROUNDABOUT | 52.IV.6 | (intersection area) | — | RED | interpretation | — |
| DRIVEWAY_BLOCKING | 52.IV.8 | “başqa nəqliyyat vasitələrinin hərəkətini (girmə və ya çıxma) qeyri-mümkün etdiyi ... yerlərdə” | — | RED across a mapped driveway mouth, on its side | interpretation | **New.** |
| BIKE_LANE | 52.IV.10-1 + 1.15-3 | “... digər nəqliyyat vasitələrinin velosiped yollarında” | bicycles, small e-vehicles | RED where OSM `cycleway:<side>=lane` | verified_text | **New** (6.9 km in the area). |
| TAXI_STAND | 52.IV.10-2 | “taksi minik avtomobili olmayan nəqliyyat vasitələrinin 5.14 nişanı ilə işarələnmiş duracaq yerlərində” | **taxis** | RED for private cars only | verified_text | **New** (per-vehicle status). |
| SIGN_3_27 | 52.IV.10; 64.VI; 64.VIII.3; 64.IX | “3.27 yol nişanının və bu nişanla birlikdə tətbiq edildikdə 1.4 nişanlanma xəttinin təsir zonalarında”; zone “nişanın qoyulduğu yerdən ən yaxın yolayrıcına qədərdir ... yola bitişik ərazilərdən yola çıxış yerlərində ... nişanlar qüvvəsini itirmir”; “yolun yalnız nişan qurulmuş tərəfinə şamil edilir” | public transport (64.V.1); zone shortened by plates 7.2.2/7.2.3 or by the length of a paired 1.4 line | RED, side-specific, in the direction of traffic | verified_text | Zone modes (7.2.2, 7.2.3, paired 1.4) **added**. |
| SIGN_3_28 | 52.VI.6; 64.V.3; 64.V.4 | “3.28 yol nişanının ... təsir zonalarında” — listed under **durma** prohibitions (52.VI) | taxis with meter on; vehicles with the disability sign | **info only** (stopping allowed) | verified_text | Confirmed (≠ 3.27). |
| MARKING_1_4 / MARKING_1_4_UNPAIRED | 52.IV.10; 69.I.4 | “1.4 — **3.27 nişanı ilə birlikdə tətbiq edildikdə** dayanma qadağan olunan yerləri bildirir” | — | With verified 3.27 → RED; **alone → YELLOW** | verified_text | **Fixed.** The 2009 amendment (769-IIIQ) removed “müstəqil” (independently); v1 treated 1.4 alone as RED. |
| MARKING_1_10 | 52.VI.6; 69.I.10 | “1.10 — 3.28, 5.40 nişanları ilə birlikdə tətbiq edildikdə duracağın qadağan olunduğu yerləri bildirir” | — | info only | verified_text | Confirmed. |
| TRAFFIC_SIGNAL | 52.IV.8 | “... svetofor siqnallarının, yol nişanlarının qarşısını tutmaqla başqa sürücülərin bunları görməsinə mane olduğu ... yerlərdə” | — | **YELLOW**, 10 m before the signal | **heuristic** (no distance in law) | **Fixed.** v1 made it RED. |
| ONE_WAY_LEFT_SIDE | 52.II | “Yolun sol tərəfində dayanmağa ... birtərəfli hərəkət yollarında ... icazə verilir” | trucks > 3.5 t: only for loading | info | verified_text | — |
| SINGLE_ROW | 52.I | “... yolun hərəkət hissəsinin kənarında bir cərgədə” | — | note on every stop | verified_text | — |
| OBSERVED_PROHIBITION | 52.IV.1/3/5/8/9/11 | clause chosen by the field observer | per clause | RED once verified | verified_text | **New:** the only way to apply 52.IV.3 (solid line < 3 m) and 52.IV.5 (visibility < 100 m), which can't be computed from OSM. |
| NOT_SURVEYED | — | — | — | **YELLOW** wherever no verified field survey covers the curb | — | **New.** Missing sign data never produces GREEN. |
| PENDING_OBSERVATION, OSM_NO_STOPPING, SOURCE_CONFLICT | — | — | — | YELLOW (unreviewed or conflicting data) | — | **New.** |

## Rules that remain unverified or are not evaluated

* **52.IV.3** (stopping where the gap to a 1.1/1.3/1.11 line is < 3 m) and **52.IV.5** (visibility < 100 m): these need
  lane-marking and visibility data that OSM doesn't have. They can only be recorded by field observers (OBSERVED_PROHIBITION).
  This is one reason an unsurveyed curb is never GREEN.
* **52.IV.1** (tram tracks): no trams in the area. Not modelled.
* **Time-limited plates** (8.x / 7.x time windows): the text is recorded but not evaluated. The engine treats the sign as always active.
* **Sign pictograms and the appendices** (Əlavə 4/5) are images on e-qanun.az, so they could not be text-checked. Sign
  *numbers* and their *legal effects* are verified from the article text.
* **52.IV.6 measurement point:** the law measures from the *edge of the crossed carriageway*. The edge is estimated
  from OSM width/lanes, not measured.
* **UNDER_BRIDGE scope** and **MOTORWAY / ROUNDABOUT mapping** are interpretations (see the table).
* **Bus lanes:** the legal requirement that the lane be marked with signs 5.9 / 5.10.x is assumed from OSM tags, not verified on site.

## Geographic coverage

* Area modelled: 28 May district bbox (40.3725–40.3870 N, 49.8390–49.8605 E), about 93 km of curb (both sides).
* **Verified field surveys: 0 km (0 %).** No real survey or official observation has been entered yet, so the map has
  **no GREEN curbs**. RED curbs come from verified statutory rules applied to OSM-mapped objects. Everything else is YELLOW.
