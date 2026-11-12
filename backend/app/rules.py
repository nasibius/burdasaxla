"""Versioned catalog of the legal rules applied by the deterministic rule engine.

Source of law (verified 2026-11-12 against the official consolidated text):
  "Yol hərəkəti haqqında" Azərbaycan Respublikasının Qanunu, No. 517-IQ (03.07.1998),
  status "Qüvvədədir", e-qanun.az framework 3423, consolidated text incl. amendment
  471-VIIQD (14.07.2026). Quotes below are copied from that text. See docs/LEGAL_VERIFICATION.md.

Effects
  prohibit  -> RED: a verified legal rule forbids *dayanma* (stopping, Art. 1.29 — which is
               what a passenger pick-up / drop-off legally is) for this vehicle class here.
  caution   -> YELLOW: the rule may apply but its legal condition cannot be evaluated from the
               available data (unknown lane count, unknown line type, unquantified distance,
               unverified observation, conflicting sources...). Blocks GREEN.
  info      -> note only; does not restrict stopping (e.g. 3.28 restricts *durma*, not *dayanma*).

Verification levels
  verified_text   the condition and distance are stated in the law text quoted here.
  interpretation  the law text is verified, but how we map it to geometry or scope is our reading.
  heuristic       the law states the condition qualitatively; the number used is our estimate.

Every geometric parameter is configuration, not engine logic. Bump `version` of a rule
(and RULESET_VERSION) when a parameter or reading changes, so results stay auditable.
"""
from dataclasses import asdict, dataclass, field

RULESET_VERSION = "2026.11-law517IQ-v2"

LAW_TITLE = "“Yol hərəkəti haqqında” Azərbaycan Respublikasının Qanunu (No. 517-IQ, 03.07.1998)"
LAW_URL = "https://e-qanun.az/framework/3423"
LAW_RETRIEVED = "2026-11-12"
LAW_VERSION_NOTE = "Consolidated text served by e-qanun.az on 2026-11-12, includes amendment 471-VIIQD (14.07.2026)."

VEHICLE_CLASSES = ("taxi", "private")


@dataclass(frozen=True)
class Rule:
    id: str
    version: int
    effect: str                 # prohibit | caution | info
    article: str                # e.g. "52.IV.4"
    verification: str           # verified_text | interpretation | heuristic
    quote: str                  # official Azerbaijani text (excerpt)
    applies_to: str = "dayanma"  # dayanma (stopping) | durma (standing/parking) | none
    params: dict = field(default_factory=dict)
    exempt: tuple = ()          # vehicle classes the rule does not apply to
    note: str = ""              # implementation note / interpretation explained

    @property
    def legal_ref(self):
        return f"Yol hərəkəti haqqında Qanun (517-IQ), m.{self.article}" if self.article else ""

    def to_dict(self):
        d = asdict(self)
        d["legal_ref"] = self.legal_ref
        d["source_url"] = LAW_URL if self.article else None
        return d


_R = [
    # ------------------------------------------------------------ prohibitions
    Rule("PEDESTRIAN_CROSSING", 2, "prohibit", "52.IV.4", "verified_text",
         "piyada keçidlərində və onlara 5 metrdən az yaxınlıqda [dayanma qadağandır]",
         params={"buffer_m": 5.0, "crossing_half_width_m": 2.0},
         note="Both directions. v1 wrongly applied 5 m only before the crossing (Russian PDD reading). "
              "Crossing width is not in OSM; ±2 m around the crossing node is an estimate."),
    Rule("INTERSECTION", 2, "prohibit", "52.IV.6", "verified_text",
         "hərəkət hissələrinin kəsişməsində və kəsişən hərəkət hissəsinin kənarından 5 metrdən az yaxınlıqda",
         params={"edge_buffer_m": 5.0},
         note="Crossed-carriageway edge is estimated from OSM width/lanes. Junctions with yard/driveway "
              "service roads are not treated as intersections (Art. 64.VI distinguishes 'yola bitişik "
              "ərazilərdən çıxış yerləri'); stopping across them is covered by DRIVEWAY_BLOCKING."),
    Rule("BUS_STOP", 2, "prohibit", "52.IV.7", "verified_text",
         "dayanacaq meydançasına, meydança olmadıqda isə ümumi istifadədə olan nəqliyyat vasitələrinin dayanacaq "
         "yerini işarə edən 5.12 və ya 5.13 yol nişanlarına 15 metrdən az yaxınlıqda",
         params={"radius_m": 15.0},
         note="Measured from the OSM stop node (≈ sign) or from the ends of a mapped platform. "
              "Side-specific. Rail/metro platforms excluded (Art. 1.44: public transport = bus, trolleybus, tram)."),
    Rule("BUS_LANE_SOLID", 1, "prohibit", "48.IV", "verified_text",
         "5.9, 5.10.1—5.10.3 nişanları ilə işarə edilmiş, ümumi istifadədə olan nəqliyyat vasitələri üçün nəzərdə "
         "tutulmuş zolağı olan yollarda hərəkət edən digər nəqliyyat vasitələrinin həmin zolaqda hərəkəti və "
         "dayanması qadağandır.",
         note="Applied when a verified observation records the bus lane separated by a solid line."),
    Rule("TUNNEL", 1, "prohibit", "52.IV.2", "verified_text",
         "dəmiryol keçidlərində, tunellərdə, habelə estakadalarda, körpülərdə (əgər həmin istiqamətdə üçdən az "
         "hərəkət zolağı varsa) və onların altında"),
    Rule("BRIDGE", 2, "prohibit", "52.IV.2", "verified_text",
         "estakadalarda, körpülərdə (əgər həmin istiqamətdə üçdən az hərəkət zolağı varsa)",
         params={"min_lanes_allowed": 3},
         note="Only when the lane count in that direction is known to be < 3. Unknown -> BRIDGE_LANES_UNKNOWN."),
    Rule("UNDER_BRIDGE", 1, "prohibit", "52.IV.2", "interpretation",
         "... estakadalarda, körpülərdə (...) və onların altında",
         note="'və onların altında' read as applying to everything under a bridge/overpass. "
              "Extent under the structure is estimated from the bridge's width."),
    Rule("LEVEL_CROSSING", 1, "prohibit", "52.IV.2", "verified_text", "dəmiryol keçidlərində",
         params={"half_extent_m": 6.0}, note="Extent of the crossing estimated as ±6 m around the OSM node."),
    Rule("MOTORWAY", 1, "prohibit", "52.IV.11", "interpretation",
         "avtomagistrallarda və ya 5.3 nişanı ilə işarələnmiş yollarda 5.15 və ya 6.11 nişanları ilə işarələnmiş "
         "xüsusi dayanacaq meydançalarından kənarda dayanma qadağandır",
         note="OSM highway=motorway assumed to be a legal 'avtomagistral'. None in the 28 May area."),
    Rule("ROUNDABOUT", 1, "prohibit", "52.IV.6", "interpretation",
         "hərəkət hissələrinin kəsişməsində",
         note="A roundabout carriageway is treated as part of the intersection area (Art. 1.11 yolayrıcı)."),
    Rule("DRIVEWAY_BLOCKING", 1, "prohibit", "52.IV.8", "interpretation",
         "başqa nəqliyyat vasitələrinin hərəkətini (girmə və ya çıxma) qeyri-mümkün etdiyi ... yerlərdə",
         params={"extra_m": 1.0},
         note="Stopping across the mouth of a mapped service road / driveway blocks entry or exit."),
    Rule("BIKE_LANE", 1, "prohibit", "52.IV.10-1", "verified_text",
         "velosiped və kiçik elektrik nəqliyyat vasitələri istisna olmaqla, digər nəqliyyat vasitələrinin "
         "velosiped yollarında",
         note="Art. 1.15-3: 'velosiped yolu — ... velosiped cığırı və ya zolağıdır' — a painted bike lane (1.15-1) is a "
              "bicycle road, so stopping in it is prohibited. Data: OSM cycleway:<side>=lane. Separated tracks do not "
              "affect the curb."),
    Rule("TAXI_STAND", 1, "prohibit", "52.IV.10-2", "verified_text",
         "taksi minik avtomobili olmayan nəqliyyat vasitələrinin 5.14 nişanı ilə işarələnmiş duracaq yerlərində",
         exempt=("taxi",)),
    Rule("SIGN_3_27", 2, "prohibit", "52.IV.10; 64.VI; 64.VIII.3; 64.IX", "verified_text",
         "3.27 yol nişanının və bu nişanla birlikdə tətbiq edildikdə 1.4 nişanlanma xəttinin təsir zonalarında; "
         "3.26—3.30 nişanlarının qüvvəsi nişanın qoyulduğu yerdən ən yaxın yolayrıcına qədərdir ... "
         "yola bitişik ərazilərdən yola çıxış yerlərində ... nişanlar qüvvəsini itirmir; "
         "3.10, 3.27—3.30 qadağan nişanlarının qüvvəsi yolun yalnız nişan qurulmuş tərəfinə şamil edilir",
         note="Zone: from the sign, in the direction of traffic, to the next intersection (way splits and driveway "
              "exits do not end it), or the length of a paired 1.4 line (64.VIII.3), or an explicit 7.2.2/7.2.3 "
              "extent. Does not apply to public transport (64.V.1) — not a vehicle class in this app."),
    Rule("MARKING_1_4", 2, "prohibit", "52.IV.10; 69.I.4", "verified_text",
         "1.4 — 3.27 nişanı ilə birlikdə tətbiq edildikdə dayanma qadağan olunan yerləri bildirir",
         note="Only together with a verified 3.27 sign on the same curb. The 2009 amendment (769-IIIQ) removed "
              "'müstəqil' (independently) — a 1.4 line alone is MARKING_1_4_UNPAIRED (caution)."),
    Rule("OBSERVED_PROHIBITION", 1, "prohibit", "52.IV", "verified_text",
         "52.IV — dayanmanın qadağan olunduğu yerlər (müşahidəçinin seçdiyi bənd)",
         note="A field observation recording another 52.IV condition (e.g. IV.3 solid line < 3 m, IV.5 visibility "
              "< 100 m). The observer must cite the clause; reviewed before it applies."),
    # ------------------------------------------------------------ caution (YELLOW)
    Rule("NOT_SURVEYED", 1, "caution", "", "verified_text",
         "",
         note="No verified field observation covers this curb. Signs (3.27), markings and conditions such as "
              "52.IV.3 (solid line < 3 m) and 52.IV.5 (visibility < 100 m) are unknown, so stopping cannot be "
              "confirmed as legal. Missing sign data never means 'allowed'."),
    Rule("BUS_LANE_UNKNOWN_LINE", 1, "caution", "48.IV", "verified_text",
         "Əgər bu zaman həmin zolaq qırıq-qırıq nişanlama xətti ilə qalan hərəkət hissəsindən ayrılmışdırsa, ... "
         "hərəkət hissəsinin sağ kənarında sərnişinlərin minməsi və düşməsi üçün bu zolağa keçməyə icazə verilir, "
         "lakin bu, ümumi istifadədə olan nəqliyyat vasitələri üçün maneə yaratmamalıdır.",
         note="Bus lane known (OSM) but the separating line type is not: dashed = drop-off allowed, solid = prohibited."),
    Rule("BRIDGE_LANES_UNKNOWN", 1, "caution", "52.IV.2", "verified_text",
         "körpülərdə (əgər həmin istiqamətdə üçdən az hərəkət zolağı varsa)",
         note="Bridge with no usable lane count in OSM."),
    Rule("TRAFFIC_SIGNAL", 2, "caution", "52.IV.8", "heuristic",
         "nəqliyyat vasitəsi svetofor siqnallarının, yol nişanlarının qarşısını tutmaqla başqa sürücülərin bunları "
         "görməsinə mane olduğu ... yerlərdə",
         params={"before_m": 10.0},
         note="The law gives no distance. 10 m before the signal is our estimate, so it is shown as caution, not red."),
    Rule("T_JUNCTION_EXCEPTION", 1, "caution", "52.IV.6", "verified_text",
         "1.1—1.4 nişanlama xətti, yaxud ayırıcı zolağı olan üçtərəfli yolayrıclarındakı yan keçidin qarşı "
         "tərəfində dayanma halları istisna olmaqla",
         note="Opposite side of a T-junction: stopping is allowed if there is a 1.1–1.4 line or a dividing strip. "
              "Marking data is missing, so this stretch is caution instead of red."),
    Rule("MARKING_1_4_UNPAIRED", 1, "caution", "69.I.4", "verified_text",
         "1.4 — 3.27 nişanı ilə birlikdə tətbiq edildikdə dayanma qadağan olunan yerləri bildirir",
         note="A 1.4 line was observed without a verified 3.27 sign on the same curb. Find/verify the sign."),
    Rule("TUNNEL_PASSAGE", 1, "caution", "52.IV.2", "interpretation", "tunellərdə",
         note="OSM tunnel=building_passage: unclear whether a passage under a building is a 'tunel'."),
    Rule("PENDING_OBSERVATION", 1, "caution", "", "verified_text", "",
         note="An unreviewed observation (manual, OSM import, Mapillary/AI) reports a prohibition here."),
    Rule("OSM_NO_STOPPING", 2, "caution", "", "verified_text", "",
         note="OSM parking:*:restriction=no_stopping on this side — mapper data, not reviewed. Import it "
              "into the validation queue to confirm."),
    Rule("SOURCE_CONFLICT", 1, "caution", "", "verified_text", "",
         note="Verified sources disagree here (e.g. an official pick-up zone on a curb where a statutory "
              "prohibition applies). Needs review. A conflict never relaxes a verified statutory prohibition: "
              "such a curb stays RED and carries this flag; otherwise it is YELLOW."),
    # ------------------------------------------------------------ info (no effect on stopping)
    Rule("SIGN_3_28", 2, "info", "52.VI.6; 64.V.3; 64.V.4", "verified_text",
         "3.28 yol nişanının və bu nişanla birlikdə tətbiq edildikdə 1.10 nişanlanma xəttinin təsir zonalarında "
         "[durma qadağandır]",
         applies_to="durma",
         note="Restricts durma (standing/parking, Art. 1.31), not dayanma (Art. 1.29) — a pick-up/drop-off is allowed. "
              "Exempt: taxis with meter on (64.V.3), vehicles with the disability sign (64.V.4)."),
    Rule("MARKING_1_10", 2, "info", "52.VI.6; 69.I.10", "verified_text",
         "1.10 — 3.28, 5.40 nişanları ilə birlikdə tətbiq edildikdə duracağın qadağan olunduğu yerləri bildirir",
         applies_to="durma"),
    Rule("BUS_LANE_DASHED", 1, "info", "48.IV", "verified_text",
         "... hərəkət hissəsinin sağ kənarında sərnişinlərin minməsi və düşməsi üçün bu zolağa keçməyə icazə "
         "verilir, lakin bu, ümumi istifadədə olan nəqliyyat vasitələri üçün maneə yaratmamalıdır.",
         note="Drop-off allowed only without obstructing buses."),
    Rule("ONE_WAY_LEFT_SIDE", 2, "info", "52.II", "verified_text",
         "Yolun sol tərəfində dayanmağa və durmağa yaşayış məntəqələrində ... birtərəfli hərəkət yollarında ... "
         "icazə verilir",
         note="Trucks > 3.5 t only for loading/unloading on the left side."),
    Rule("SINGLE_ROW", 1, "info", "52.I", "verified_text",
         "nəqliyyat vasitələrinin yolun sağ tərəfində — yol çiyinində, yol çiyini olmadıqda isə yolun hərəkət "
         "hissəsinin kənarında bir cərgədə dayanmasına və durmasına icazə verilir",
         note="Stop only in one row at the curb — never double-park."),
    Rule("OFFICIAL_ZONE", 1, "info", "", "verified_text", "",
         note="Pick-up/drop-off point published by AYNA (source URL recorded on the feature)."),
    Rule("OSM_NO_PARKING", 2, "info", "", "verified_text", "", applies_to="durma"),
]

RULES: dict[str, Rule] = {r.id: r for r in _R}


def ruleset():
    return {"version": RULESET_VERSION, "law": {"title": LAW_TITLE, "url": LAW_URL, "retrieved": LAW_RETRIEVED,
                                                 "version_note": LAW_VERSION_NOTE},
            "rules": [r.to_dict() for r in RULES.values()]}
