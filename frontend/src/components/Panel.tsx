import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { LngLat, Meta, Mode, RecResponse, Recommendation, SearchItem } from "../types";
import { fmtDist, makeT, ruleTitle, type Lang } from "../i18n";
import {
  IAlert, IBan, IBuilding, IBus, ICar, ICheck, ICrosshair, IHelp, IInfo, ILocate, IMap, IPin, ISearch, IStar, ITrain, IWalk, IX, Logo,
} from "./Icons";

interface Props {
  lang: Lang;
  meta: Meta | null;
  mode: Mode;
  setMode: (m: Mode) => void;
  destLabel: string;
  setDestLabel: (s: string) => void;
  destination: LngLat | null;
  origin: LngLat | null;
  originLabel: string;
  picking: "destination" | "origin" | null;
  setPicking: (p: "destination" | "origin" | null) => void;
  onPickSearch: (it: SearchItem) => void;
  onClearDestination: () => void;
  onMyLocation: () => void;
  maxWalk: number;
  setMaxWalk: (n: number) => void;
  resp: RecResponse | null;
  loading: boolean;
  error: string | null;
  selectedRank: number | null;
  onSelectRank: (r: number) => void;
  onOpenSegment: (id: string) => void;
}

const kindLabel = (k: string, t: (k: string) => string) => {
  const v = t("kindl_" + k);
  return v === "kindl_" + k ? k.replace(/_/g, " ") : v;
};

const kindIcon = (k: string) =>
  k === "street" ? <IMap size={16} /> : ["station", "stop_position", "subway_entrance"].includes(k) ? <ITrain size={16} />
    : ["platform", "bus_station", "bus_stop"].includes(k) ? <IBus size={16} /> : <IBuilding size={16} />;

function SearchBox({ lang, value, onChange, onPick, picking, onTogglePick, onClear }: {
  lang: Lang; value: string; onChange: (s: string) => void; onPick: (it: SearchItem) => void;
  picking: boolean; onTogglePick: () => void; onClear: () => void;
}) {
  const t = makeT(lang);
  const [items, setItems] = useState<SearchItem[]>([]);
  const [open, setOpen] = useState(false);
  const [hl, setHl] = useState(0);
  const timer = useRef<number>();
  const typed = useRef(false);

  useEffect(() => {
    if (!typed.current) return;
    window.clearTimeout(timer.current);
    if (value.trim().length < 2) { setItems([]); return; }
    timer.current = window.setTimeout(() => {
      api.search(value).then((r) => { setItems(r); setHl(0); setOpen(true); }).catch(() => setItems([]));
    }, 140);
  }, [value]);

  const pick = (it: SearchItem) => { typed.current = false; onPick(it); setOpen(false); };

  return (
    <div className="input-wrap">
      <span className="input-icon"><ISearch size={17} /></span>
      <input
        className="input" value={value} placeholder={t("search_placeholder")} aria-label={t("destination")}
        onChange={(e) => { typed.current = true; onChange(e.target.value); }}
        onFocus={() => items.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (!open || !items.length) return;
          if (e.key === "ArrowDown") { e.preventDefault(); setHl((h) => Math.min(h + 1, items.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setHl((h) => Math.max(h - 1, 0)); }
          if (e.key === "Enter") { e.preventDefault(); pick(items[hl]); }
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {value ? (
        <button className="input-act" onClick={onClear} title={t("clear")} aria-label={t("clear")}><IX size={16} /></button>
      ) : (
        <button className={`input-act ${picking ? "on" : ""}`} onClick={onTogglePick} title={t("pick_on_map")} aria-label={t("pick_on_map")}><ICrosshair size={17} /></button>
      )}
      {open && items.length > 0 && (
        <div className="suggest">
          {items.map((it, i) => (
            <button key={it.name + i} className={i === hl ? "hl" : ""} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(it)} onMouseEnter={() => setHl(i)}>
              <span className="s-ic">{kindIcon(it.kind)}</span>
              <span style={{ minWidth: 0 }}>
                <div className="s-name">{it.name}</div>
                <div className="s-kind">{kindLabel(it.kind, t)}{it.alt[0] ? ` · ${it.alt[0]}` : ""}</div>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultCard({ r, lang, sel, mode, onClick, onOpenSegment }: {
  r: Recommendation; lang: Lang; sel: boolean; mode: Mode; onClick: () => void; onOpenSegment: () => void;
}) {
  const t = makeT(lang);
  return (
    <div className={`card ${sel ? "sel" : ""}`} onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick()}>
      <div className="card-top">
        <div className="rank">{r.rank}</div>
        <div style={{ minWidth: 0 }}>
          <div className="street">{r.street || "—"}</div>
          <div className="sub">{t("dir_" + r.compass)}{r.length_m ? ` · ${t("free_length")} ${Math.round(r.length_m)} m` : ""}</div>
        </div>
        {r.rank === 1 && <span className="best-tag">{t("rank_best")}</span>}
      </div>
      <div className="metrics">
        {mode !== "driver" && (
          <div className="metric walk"><span className="mi"><IWalk size={18} /></span>
            <div><div className="mv">{fmtDist(r.walk_m, lang)}</div><div className="ml">{r.walk_min} {t("min")} {t("walk")}</div></div>
          </div>
        )}
        {r.drive_min != null ? (
          <div className="metric drive"><span className="mi"><ICar size={18} /></span>
            <div><div className="mv">{r.drive_min} {t("min")}</div><div className="ml">{fmtDist(r.drive_m, lang)} {t("drive")}</div></div>
          </div>
        ) : (
          <div className="metric drive"><span className="mi"><ICar size={18} /></span><div><div className="mv">—</div><div className="ml">{t("driver_location")}?</div></div></div>
        )}
      </div>
      <div className="chips">
        <span className="chip ok"><ICheck size={12} />{t("st_VERIFIED")}</span>
        {r.official && <span className="chip brand"><IStar size={12} />{t("official")}</span>}
        {r.crossing && !r.crossing.must_cross && mode !== "driver" && <span className="chip">{t("same_side")}</span>}
        {r.crossing?.must_cross && r.crossing.safe_crossing && <span className="chip warn">{t("cross_safe")} · {r.crossing.crossing_distance_m} m</span>}
        {r.crossing?.must_cross && !r.crossing.safe_crossing && <span className="chip no"><IAlert size={12} />{t("cross_unsafe")}</span>}
        {r.notes.map((n) => <span key={n} className="chip" title={n}>{ruleTitle(n, lang)}</span>)}
        <span className="chip" style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); onOpenSegment(); }}><IInfo size={12} />{t("why")}</span>
      </div>
    </div>
  );
}

export default function Panel(p: Props) {
  const t = makeT(p.lang);
  const [collapsed, setCollapsed] = useState(false);
  const stats = p.meta?.stats.by_status;
  const totalKm = stats ? Object.values(stats).reduce((a, s) => a + s.length_m, 0) / 1000 : 0;
  const door = p.resp?.curb_at_door;
  const hasQuery = p.mode === "driver" ? !!p.origin : !!p.destination;

  return (
    <section className={`panel glass ${collapsed ? "collapsed" : ""}`}>
      <button className="sheet-handle" aria-label="toggle panel" onClick={() => setCollapsed((c) => !c)} />
      <div className="panel-head">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">Burda<b>Saxla</b></div>
            <div className="brand-sub"><span className="dot-live" />{t("tagline")} · {t("area")}</div>
          </div>
        </div>
        <div className="seg-ctl" role="tablist">
          {(["dropoff", "pickup", "driver"] as Mode[]).map((m) => (
            <button key={m} role="tab" aria-selected={p.mode === m} className={p.mode === m ? "on" : ""} onClick={() => p.setMode(m)}>
              {m === "driver" ? <ICar size={15} /> : m === "dropoff" ? <IPin size={15} /> : <IWalk size={15} />}
              {t("mode_" + m)}
            </button>
          ))}
        </div>
      </div>

      <div className="panel-body">
        <div className="mode-hint" style={{ marginTop: 0 }}>{t("mode_" + p.mode + "_hint")}</div>

        {p.mode !== "driver" && <>
          <div className="field-label"><span>{t(p.mode === "pickup" ? "passenger_location" : "destination")}</span></div>
          <SearchBox lang={p.lang} value={p.destLabel} onChange={p.setDestLabel} onPick={p.onPickSearch}
            picking={p.picking === "destination"} onTogglePick={() => p.setPicking(p.picking === "destination" ? null : "destination")}
            onClear={p.onClearDestination} />
        </>}

        <div className="field-label"><span>{t("driver_location")}</span></div>
        <div className="loc-row">
          <button className={`loc-chip ${p.picking === "origin" ? "on" : ""}`} onClick={() => p.setPicking(p.picking === "origin" ? null : "origin")}>
            <span className="ic"><ICar size={18} /></span>
            <span className={`tx ${p.origin ? "" : "muted"}`}>{p.origin ? p.originLabel : t("set_on_map")}</span>
          </button>
          <button className="sq-btn" onClick={p.onMyLocation} title={t("my_location")} aria-label={t("my_location")}><ILocate size={17} /></button>
        </div>

        {p.mode !== "driver" && <>
          <div className="field-label"><span>{t("walk_limit")}</span><span>{p.maxWalk} m</span></div>
          <input className="range" type="range" min={100} max={1000} step={50} value={p.maxWalk} onChange={(e) => p.setMaxWalk(+e.target.value)} aria-label={t("walk_limit")} />
        </>}

        {p.error && <div className="err">{t("error")}: {p.error}</div>}

        {!hasQuery && (
          <div className="intro">
            <h3>{t("start_hint_title")}</h3>
            <p>{p.mode === "driver" ? t("driver_start_hint") : t("start_hint")}</p>
            {stats && (
              <div className="stat-grid">
                <div className="stat ok"><div className="v">{(stats.VERIFIED.length_m / 1000).toFixed(1)}</div><div className="l">km · {t("st_VERIFIED")}</div></div>
                <div className="stat no"><div className="v">{(stats.PROHIBITED.length_m / 1000).toFixed(1)}</div><div className="l">km · {t("st_PROHIBITED")}</div></div>
                <div className="stat unk"><div className="v">{(stats.UNKNOWN.length_m / 1000).toFixed(1)}</div><div className="l">km · {t("st_UNKNOWN")}</div></div>
              </div>
            )}
          </div>
        )}

        {hasQuery && p.mode !== "driver" && door && (
          <div className={`door ${door.status}`} onClick={() => p.onOpenSegment(door.segment_id)} role="button">
            <span className="d-ic">{door.status === "PROHIBITED" ? <IBan size={16} /> : door.status === "VERIFIED" ? <ICheck size={16} /> : <IHelp size={16} />}</span>
            <div>
              <div className="d-t">{t(door.status === "PROHIBITED" ? "door_prohibited" : door.status === "VERIFIED" ? "door_ok" : "door_unknown")}</div>
              <div className="d-s">
                {door.name}{door.reasons.length ? " — " + [...new Set(door.reasons.map((r) => ruleTitle(r.rule, p.lang)))].join(", ") : ""}
              </div>
            </div>
          </div>
        )}

        {hasQuery && (
          <>
            <div className="results-head">
              <h4>{t("results")}</h4>
              {p.loading ? <small>{t("finding")}</small> : p.resp?.diagnostics && <small>{p.resp.diagnostics.ranked} / {p.resp.diagnostics.candidates_in_radius}</small>}
            </div>
            {p.resp?.warnings?.map((w) => <div key={w} className="warn-line"><IAlert size={13} />{t("warn_" + w)}</div>)}
            {p.resp?.results.map((r) => (
              <ResultCard key={r.rank + r.segment_id} r={r} lang={p.lang} mode={p.mode} sel={p.selectedRank === r.rank}
                onClick={() => p.onSelectRank(r.rank)} onOpenSegment={() => p.onOpenSegment(r.segment_id)} />
            ))}
            {!p.loading && p.resp && p.resp.results.length === 0 && (
              <div className="empty">
                <div className="e-ic"><IBan size={22} /></div>
                <h4>{p.resp.message && p.resp.message !== "no_verified_spot" ? t("msg_" + p.resp.message) : t("no_spot")}</h4>
                <p>{t("no_spot_hint")}</p>
              </div>
            )}
          </>
        )}

        <div className="banner"><IInfo size={14} /><span>{t("demo_banner")}</span></div>
        <div className="mob-attr">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors · Basemap © Esri, HERE, Garmin · Leaflet</div>
      </div>
      <div className="panel-foot">
        <span>{totalKm.toFixed(1)} {t("stat_curb")}</span>
        <span>{p.meta?.mode === "static" ? `${t("static_badge")} · ` : ""}OSM · {p.meta?.ruleset}</span>
      </div>
    </section>
  );
}
