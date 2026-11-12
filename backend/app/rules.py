"""Versioned catalog of legal rules applied by the deterministic rule engine.

Every number here is a *configuration* of the legal text, not engine logic.
The legal/product owner must verify each entry against the text currently in
force (Law of the Republic of Azerbaijan "On Road Traffic", Art. 52 and the
road-sign / road-marking rules) before production use. Bump `version` when a
parameter changes so affected segments can be recomputed and audited.
"""
from dataclasses import dataclass, field, asdict

RULESET_VERSION = "2026.11-mvp1"


@dataclass(frozen=True)
class Rule:
    id: str
    version: int
    effect: str            # "prohibit" (red) | "info" (note only, no prohibition)
    legal_ref: str
    params: dict = field(default_factory=dict)
    approximation: bool = False  # True when geometry is estimated, not measured

    def to_dict(self):
        return asdict(self)


RULES: dict[str, Rule] = {r.id: r for r in [
    Rule("PEDESTRIAN_CROSSING", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52",
         {"before_m": 5.0, "crossing_half_width_m": 2.0}),
    Rule("INTERSECTION", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52",
         {"edge_buffer_m": 5.0}, approximation=True),
    Rule("BUS_STOP", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52",
         {"radius_m": 15.0}),
    Rule("BUS_LANE", 1, "prohibit", "Yol nişanı 5.14 / marşrut nəqliyyat vasitələri zolağı",
         {"taxi_exception": False}),
    Rule("BRIDGE_TUNNEL", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52 (körpü, estakada, tunel)"),
    Rule("UNDER_BRIDGE", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52 (körpü və estakadaların altı)",
         {}, approximation=True),
    Rule("MOTORWAY", 1, "prohibit", "Avtomagistrallarda dayanma qadağası"),
    Rule("ROUNDABOUT", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52 (yolayrıcında)"),
    Rule("TRAFFIC_SIGNAL", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52 (svetoforun görünməsinə mane olma)",
         {"before_m": 10.0}, approximation=True),
    Rule("LEVEL_CROSSING", 1, "prohibit", "Yol hərəkəti haqqında Qanun, m.52 (dəmir yolu keçidi)",
         {"radius_m": 10.0}),
    Rule("SIGN_3_27", 1, "prohibit", "Yol nişanı 3.27 — Dayanmaq qadağandır",
         {"zone": "sign_to_next_intersection"}),
    Rule("MARKING_1_4", 1, "prohibit", "Üfüqi nişanlanma 1.4 — sarı bütöv xətt (dayanma qadağası)"),
    Rule("OSM_NO_STOPPING", 1, "prohibit", "OSM: parking:*:restriction=no_stopping (yoxlanılmalıdır)"),
    # Informational: these do NOT forbid a short passenger stop.
    Rule("SIGN_3_28", 1, "info", "Yol nişanı 3.28 — Durmaq qadağandır (dayanmaq olar)"),
    Rule("MARKING_1_10", 1, "info", "Üfüqi nişanlanma 1.10 — sarı qırıq xətt (durmaq qadağandır, dayanmaq olar)"),
    Rule("OSM_NO_PARKING", 1, "info", "OSM: parking:*:restriction=no_parking"),
    Rule("ONE_WAY_LEFT_SIDE", 1, "info", "Yaşayış məntəqələrində birtərəfli yolun sol tərəfində dayanmağa icazə verilir"),
    Rule("OFFICIAL_ZONE", 1, "info", "AYNA tərəfindən elan edilmiş minib-düşmə məntəqəsi"),
]}


def ruleset():
    return {"version": RULESET_VERSION, "rules": [r.to_dict() for r in RULES.values()]}
