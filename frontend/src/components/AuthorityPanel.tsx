import { useEffect, useMemo, useState } from 'react';
import { CircleMarker, GeoJSON, LayerGroup, LayersControl, MapContainer, Polygon, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet';
import type { Lang } from '../i18n';
import type { LngLat, SegFeature } from '../types';
import { STATIC_MODE } from '../api';
import { csvCell, download, exportPlanning, planningApi, type Candidate, type PlanningSnapshot, type ReviewStatus } from '../planning';
import './authority.css';

const ll = (p: LngLat): [number, number] => [p[1], p[0]];
const statuses: ReviewStatus[] = ['needs_survey', 'shortlist', 'reject', 'more_data_needed'];
function Focus({ candidate }: { candidate?: Candidate }) {
  const map = useMap();
  useEffect(() => { if (candidate) map.fitBounds(candidate.geometry.coordinates.map(ll), { maxZoom: 18, padding: [60, 60], animate: false }); }, [candidate, map]);
  return null;
}
export default function AuthorityPanel({ lang, theme, segments }: { lang: Lang; theme: 'dark' | 'light'; segments: SegFeature[] }) {
  const az = lang === 'az';
  const t = (en: string, translated: string) => az ? translated : en;
  const statusLabel = (s: ReviewStatus) => ({ needs_survey: t('Needs survey', 'Sahə yoxlaması'), shortlist: t('Shortlisted', 'Qısa siyahıda'),
    reject: t('Rejected', 'Rədd edilib'), more_data_needed: t('More data needed', 'Əlavə məlumat lazımdır') })[s];
  const [data, setData] = useState<PlanningSnapshot | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState(''); const [selected, setSelected] = useState('');
  const [threshold, setThreshold] = useState(450); const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useState<'map' | 'activity'>('map');
  const [token, setToken] = useState(''); const [action, setAction] = useState<ReviewStatus>('needs_survey');
  const [reason, setReason] = useState(''); const [notice, setNotice] = useState('');
  const [activityFilter, setActivityFilter] = useState(''); const [sort, setSort] = useState('passengers_per_hour');
  useEffect(() => {
    let live = true; setError(''); setData(null);
    planningApi.snapshot(threshold).then(d => { if (live) setData(d); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [threshold, refresh]);
  const rows = useMemo(() => data?.candidates.filter(c => !filter || c.review_status === filter) ?? [], [data, filter]);
  const candidate = rows.find(c => c.candidate_id === selected);
  const activity = useMemo(() => (data?.passenger_activity ?? []).filter(r => `${r.name} ${r.source_ref}`.toLowerCase().includes(activityFilter.toLowerCase()))
    .sort((a, b) => Number(b[sort as keyof typeof b]) - Number(a[sort as keyof typeof a]) || a.location_id.localeCompare(b.location_id)), [data, activityFilter, sort]);
  const pick = (c: Candidate) => { setSelected(c.candidate_id); setAction(c.review_status); setReason(''); setNotice(''); };
  async function saveReview() {
    if (!candidate || STATIC_MODE) return;
    setBusy(true); setNotice('');
    try { await planningApi.review(candidate, action, reason, token, threshold); setNotice(t('Review saved.', 'Rəy saxlanıldı.')); setRefresh(v => v + 1); }
    catch (e) { setNotice(String(e)); } finally { setBusy(false); }
  }
  async function importFile(file?: File) {
    if (!file || STATIC_MODE) return;
    if (file.size > 2_000_000) { setNotice(t('File exceeds 2 MB.', 'Fayl 2 MB-dan böyükdür.')); return; }
    setBusy(true);
    try { await planningApi.importActivity(JSON.parse(await file.text()), token); setNotice(t('Aggregate records imported.', 'Aqreqat qeydlər idxal edildi.')); setRefresh(v => v + 1); }
    catch (e) { setNotice(String(e)); } finally { setBusy(false); }
  }
  if (error) return <main className="authority-page authority-error" role="alert"><h1>AYNA Planning</h1><p>{error}</p><button onClick={() => setRefresh(v => v + 1)}>{t('Retry', 'Yenidən cəhd')}</button></main>;
  if (!data) return <main className="authority-page authority-error" role="status">{t('Loading planning snapshot…', 'Planlaşdırma məlumatları yüklənir…')}</main>;
  return <main className="authority-page">
    <header className="authority-heading"><span className="authority-eyebrow">BURDASAXLA / {t('AUTHORITY WORKSPACE', 'PLANLAŞDIRMA')}</span>
      <h1>{t('A better curb starts with evidence.', 'Daha yaxşı dayanacaq sübutdan başlayır.')}</h1>
      <p>{t('Investigate future pickup/drop-off capacity. Every proposal requires official assessment.', 'Gələcək minmə/düşmə yerlərini araşdırın. Hər təklif rəsmi qiymətləndirmə tələb edir.')}</p>
      <div className="authority-controls"><label>{t('Study area', 'Tədqiqat ərazisi')} <select aria-label="Study area" value={data.area.id} onChange={() => {}}><option value={data.area.id}>{data.area.name}</option></select></label>
        <span className="authority-badge">{STATIC_MODE ? t('Read-only demonstration', 'Yalnız baxış nümayişi') : t('Backend · authenticated reviews', 'Server · səlahiyyətli rəylər')}</span>
        <span>{t('Data as of', 'Məlumat tarixi')}: {data.source_versions.osm ?? 'unknown'}</span></div>
    </header>
    <div className="authority-metrics">
      <div><strong>{data.summary.verified_official_locations}</strong><span>{t('Verified official records', 'Təsdiqli rəsmi qeydlər')}</span></div>
      <div><strong>{data.summary.survey_tasks}</strong><span>{t('Curb survey tasks', 'Bordür yoxlama tapşırıqları')}</span></div>
      <div><strong>—</strong><span>{t('Coverage not established', 'Əhatə müəyyən edilməyib')}</span></div>
      <div><strong>{data.summary.analyzed_nodes}</strong><span>{t('Access proxies · inventory unknown', 'Giriş proksiləri · inventar naməlum')}</span></div>
    </div>
    <div className="authority-warning"><b>INVENTORY_UNKNOWN</b> · {t('Verified supply inventory incomplete — coverage cannot be established', 'Təsdiqlənmiş yerlərin inventarı natamamdır — əhatə müəyyən edilə bilməz')}<br />
      {t('No infrastructure shortage or legal permission is inferred. Demand is not measured unless sourced records are supplied below.', 'İnfrastruktur çatışmazlığı və ya hüquqi icazə nəticəsi çıxarılmır. Mənbəli qeydlər olmadan tələb ölçülmüş sayılmır.')}</div>
    <nav className="authority-tabs" aria-label="Planning sections"><button aria-pressed={tab === 'map'} onClick={() => setTab('map')}>{t('Survey board', 'Yoxlama paneli')}</button>
      <button aria-pressed={tab === 'activity'} onClick={() => setTab('activity')}>{t('Passenger activity', 'Sərnişin axını')}</button>
      <button onClick={() => { location.hash = ''; }}>{t('← Passenger / Driver', '← Sərnişin / Sürücü')}</button></nav>
    {tab === 'map' ? <div className="authority-workspace">
      <aside className="authority-list"><div className="authority-controls"><label>{t('Review status', 'Rəy statusu')}<select aria-label="Review status filter" value={filter} onChange={e => { setFilter(e.target.value); setSelected(''); }}><option value="">{t('All tasks', 'Bütün tapşırıqlar')}</option>{statuses.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}</select></label>
        <label>{t('Walking scenario (m)', 'Piyada ssenarisi (m)')}<select aria-label="Walking threshold" disabled={STATIC_MODE} value={threshold} onChange={e => setThreshold(Number(e.target.value))}>{[250, 450, 750].map(n => <option key={n}>{n}</option>)}</select></label></div>
        <small>{t('Planning assumption, not a legal distance. Static snapshot uses 450 m. Distances remain unknown until access is verified.', 'Planlaşdırma fərziyyəsidir, hüquqi məsafə deyil. Statik ssenari 450 m-dir. Giriş yoxlanana qədər məsafələr naməlumdur.')}</small>
        <div className="authority-exports"><button onClick={() => exportPlanning(rows, data, 'csv')}>CSV ({rows.length})</button><button onClick={() => exportPlanning(rows, data, 'geojson')}>GeoJSON</button><button onClick={() => { document.body.dataset.authorityPrint = 'list'; window.print(); }}>{t('Print list', 'Siyahını çap et')}</button></div>
        <p>{t('Survey sequence, not a suitability ranking. All numeric scores withheld.', 'Yoxlama ardıcıllığıdır, uyğunluq reytinqi deyil. Rəqəmli ballar göstərilmir.')}</p>
        {!rows.length && <p role="status">{data.empty_reason ?? t('No tasks match this filter.', 'Bu filtrə uyğun tapşırıq yoxdur.')}</p>}
        {rows.map(c => <button key={c.candidate_id} className={`authority-card ${selected === c.candidate_id ? 'selected' : ''}`} onClick={() => pick(c)} aria-pressed={selected === c.candidate_id}>
          {c.is_synthetic_example && <b>SIMULATED EXAMPLE</b>}<span className="authority-card-number">{c.display_order.toString().padStart(2, '0')}</span><div><h3>{c.name}</h3>
            <p>{c.road_side === 'left' ? t('Left curb', 'Sol bordür') : t('Right curb', 'Sağ bordür')} · ≈ {Math.round(c.length_m)} m</p>
            <span>{statusLabel(c.review_status)} · {t('Geometry only', 'Yalnız həndəsə')}</span><small>{t('Survey target · not an authorized stop', 'Yoxlama hədəfi · icazəli dayanacaq deyil')}</small></div></button>)}
      </aside>
      <section className="authority-map-column">
        <div className="authority-map"><MapContainer bounds={data.area.geometry.coordinates[0].map(ll)} zoomControl scrollWheelZoom style={{ height: '100%' }}>
          <TileLayer url={`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${theme === 'dark' ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`} maxNativeZoom={16} maxZoom={19} attribution='© Esri · <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>' />
          <LayersControl position="topright"><LayersControl.Overlay checked name={t('Pilot boundary', 'Pilot sərhədi')}><Polygon positions={data.area.geometry.coordinates[0].map(ll)} pathOptions={{ color: '#8799b8', weight: 2, dashArray: '7 7', fillOpacity: 0.02 }} /></LayersControl.Overlay>
            <LayersControl.Overlay name={t('Current curb restrictions', 'Cari bordür məhdudiyyətləri')}><GeoJSON key={segments.length} data={{ type: 'FeatureCollection', features: segments } as any} style={f => ({ color: f?.properties.status === 'PROHIBITED' ? '#ef596f' : f?.properties.status === 'ALLOWED' ? '#2fd581' : '#d5a735', weight: 2 })} /></LayersControl.Overlay>
            <LayersControl.Overlay checked name={t('Verified official records', 'Təsdiqli rəsmi qeydlər')}><LayerGroup>{data.verified_locations.map(z => <GeoJSON key={z.id} data={z.geometry} style={{ color: '#31bcd2', weight: 7 }}><Tooltip>{t('Verified official record', 'Təsdiqli rəsmi qeyd')} #{z.id} · {z.verified_at ?? 'unknown'}</Tooltip></GeoJSON>)}</LayerGroup></LayersControl.Overlay>
            <LayersControl.Overlay checked name={t('Information gaps / survey tasks', 'Məlumat boşluğu / yoxlama tapşırıqları')}><LayerGroup>{rows.map(c => <Polyline key={c.candidate_id} positions={c.geometry.coordinates.map(ll)} pathOptions={{ color: c.candidate_id === selected ? '#c2a2ff' : '#8995a9', weight: c.candidate_id === selected ? 9 : 5, dashArray: '6 5' }} eventHandlers={{ click: () => pick(c) }}><Tooltip sticky>{c.is_synthetic_example ? 'SIMULATED EXAMPLE · ' : ''}{c.display_order}. {c.name} · {t('Survey only · not legal permission', 'Yalnız yoxlama · hüquqi icazə deyil')}</Tooltip></Polyline>)}</LayerGroup></LayersControl.Overlay>
          </LayersControl>
          {candidate && <CircleMarker center={ll(candidate.geometry.coordinates[0])} radius={7} pathOptions={{ color: '#c2a2ff' }} />}
          <Focus candidate={candidate} />
        </MapContainer></div>
        <div className="authority-map-legend">{t('Dashed gray: survey needed · Purple: selected survey · Cyan: verified official record. These are separate from current curb legality.', 'Boz kəsik: yoxlama tələb olunur · Bənövşəyi: seçilmiş tapşırıq · Mavi: təsdiqli rəsmi qeyd. Cari dayanma qanuniliyindən ayrıdır.')}</div>
        {candidate ? <article className="authority-detail" aria-label="Candidate detail"><div className="authority-controls"><h2>{candidate.name}</h2><button onClick={() => setSelected('')}>{t('Close', 'Bağla')}</button><button onClick={() => { document.body.dataset.authorityPrint = 'candidate'; window.print(); }}>{t('Print candidate', 'Namizədi çap et')}</button></div>
          <code>{candidate.candidate_id}</code><p><b>{t('Requires official field / engineering / legal assessment', 'Rəsmi sahə / mühəndislik / hüquqi qiymətləndirmə tələb olunur')}</b></p>
          {candidate.is_synthetic_example && <b>SIMULATED EXAMPLE</b>}
          <h3>{t('Why survey here?', 'Niyə burada yoxlama?')}</h3><p>{t('An existing mapped curb has incomplete field evidence. The sampling policy selects spaced survey targets; it does not establish demand or a shortage.', 'Xəritədəki bordür haqqında sahə məlumatı natamamdır. Seçim qaydası aralı yoxlama hədəfləri seçir; tələb və ya çatışmazlıq müəyyən etmir.')}</p>
          <dl><dt>{t('Evidence / class', 'Sübut / sinif')}</dt><dd>{candidate.evidence_strength} / {candidate.candidate_class}</dd><dt>{t('Nearest verified zone, walking distance', 'Ən yaxın təsdiqli yerə piyada məsafəsi')}</dt><dd>{candidate.walk_distance_to_verified_zone_m ?? t('Not available', 'Məlum deyil')}</dd><dt>{t('Accessibility benefit / score', 'Əlçatanlıq faydası / bal')}</dt><dd>{t('Unknown / withheld', 'Naməlum / göstərilmir')}</dd><dt>{t('Last field verification', 'Son sahə yoxlaması')}</dt><dd>{candidate.last_verified ?? t('Not available', 'Məlum deyil')}</dd></dl>
          <h3>{t('Why not automatically approved?', 'Niyə avtomatik təsdiqlənmir?')}</h3><ul>{candidate.missing_evidence.map(m => <li key={m}>{m}</li>)}</ul>
          <p>{t('Known cautions', 'Məlum xəbərdarlıqlar')}: {candidate.constraints.join(', ') || t('None recorded; this does not establish feasibility.', 'Qeydə alınmayıb; bu, uyğunluğu təsdiqləmir.')}</p>
          <a href={candidate.source_url} target="_blank" rel="noreferrer">{t('Open source geometry ↗', 'Mənbə həndəsəsini aç ↗')}</a><p>{candidate.algorithm_version} · {data.source_versions.osm}</p>
          <h3>{t('Review', 'Rəy')}</h3><p>{statusLabel(candidate.review_status)}</p>
          {STATIC_MODE ? <p>{t('Read-only demonstration. Reviews require the authenticated backend.', 'Yalnız baxış nümayişi. Rəylər səlahiyyətli server tələb edir.')}</p> : <div className="authority-review"><label>{t('Admin token', 'Admin tokeni')}<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label><label>{t('Action', 'Əməl')}<select aria-label={t("Action", "Əməl")} value={action} onChange={e => setAction(e.target.value as ReviewStatus)}>{statuses.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}</select></label><label>{t('Reason (private audit note)', 'Səbəb (özəl audit qeydi)')}<textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} /></label><button disabled={busy || !token || reason.trim().length < 3} onClick={saveReview}>{t('Save review', 'Rəyi saxla')}</button></div>}
          <ul>{candidate.review_history.map((r, i) => <li key={i}>{statusLabel(r.action)} · {r.reviewed_at}</li>)}</ul><p role="status">{notice}</p>
        </article> : <div className="authority-detail"><h2>{t('Select a survey task', 'Yoxlama tapşırığı seçin')}</h2><p>{t('Inspect its curb geometry, sources and missing evidence before requesting a field assessment.', 'Sahə qiymətləndirməsindən əvvəl bordür həndəsəsini, mənbələri və çatışmayan sübutları yoxlayın.')}</p></div>}
      </section>
    </div> : <section className="authority-activity"><h2>{t('Where passengers get in and out', 'Sərnişinlərin mindiyi və düşdüyü yerlər')}</h2>
      <p>{t('Sourced aggregate passenger movements, kept in a separate table. Compare observation periods and collection methods; these samples do not represent total citywide taxi demand.', 'Mənbəli aqreqat sərnişin hərəkətləri ayrı cədvəldə saxlanılır. Müşahidə dövrlərini və toplama üsullarını müqayisə edin; bu nümunələr şəhərin bütün taksi tələbini əks etdirmir.')}</p>
      <div className="authority-controls"><label>{t('Place / source', 'Yer / mənbə')}<input aria-label="Activity search" value={activityFilter} onChange={e => setActivityFilter(e.target.value)} /></label><label>{t('Sort by', 'Sıralama')}<select value={sort} onChange={e => setSort(e.target.value)}><option value="passengers_per_hour">{t('Movements / hour', 'Hərəkət / saat')}</option><option value="pickups">{t('Boarding passengers', 'Minən sərnişinlər')}</option><option value="dropoffs">{t('Alighting passengers', 'Düşən sərnişinlər')}</option></select></label>
        <button onClick={() => { const keys = ['name', 'pickups', 'dropoffs', 'passengers_per_hour', 'period_start', 'period_end', 'source_ref', 'source_url', 'license', 'collection_method'] as const; download('passenger-activity.csv', [keys.join(',') + ',limitations', ...activity.map(r => keys.map(k => csvCell(r[k])).join(',') + ',' + csvCell('Observed source/period sample; not citywide demand; overlapping sources not summed.'))].join('\r\n'), 'text/csv'); }}>CSV ({activity.length})</button></div>
      <div className="authority-table-wrap"><table><thead><tr>{[t('Place', 'Yer'), t('Boardings', 'Minmə'), t('Alightings', 'Düşmə'), t('Per hour', 'Saatda'), t('Observation period', 'Müşahidə dövrü'), t('Source / method', 'Mənbə / üsul')].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{activity.map(r => <tr key={r.id}><td>{r.name}</td><td>{r.pickups}</td><td>{r.dropoffs}</td><td>{r.passengers_per_hour}</td><td>{r.period_start}<br />{r.period_end}</td><td><a href={r.source_url} target="_blank" rel="noreferrer">{r.source_ref}</a><br />{r.collection_method}<br />{r.license}</td></tr>)}</tbody></table></div>
      {!activity.length && <div className="authority-empty" role="status"><h3>{t('No measured passenger activity available', 'Ölçülmüş sərnişin axını məlumatı yoxdur')}</h3><p>{t('Import authorized aggregate observations to identify busy boarding and alighting places. POIs are not passenger counts.', 'Sıx minmə və düşmə yerlərini müəyyən etmək üçün icazəli aqreqat müşahidələri idxal edin. POI-lər sərnişin sayı deyil.')}</p></div>}
      {STATIC_MODE ? <p>{t('Read-only demonstration · import is available on the authenticated backend.', 'Yalnız baxış nümayişi · idxal səlahiyyətli serverdə mümkündür.')}</p> : <details><summary>{t('Import aggregate observations (JSON)', 'Aqreqat müşahidələri idxal et (JSON)')}</summary><p>{t('Use the documented activity schema. Minimum 24-hour periods; explicit publication permission. No rider IDs or trajectories.', 'Sənədləşdirilmiş axın sxemindən istifadə edin. Minimum 24 saatlıq dövr; açıq yayım icazəsi. Sərnişin identifikatorları və trayektoriyalar qəbul edilmir.')}</p><label>Admin token<input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" /></label><label>{t('JSON file', 'JSON faylı')}<input type="file" accept=".json,application/json" disabled={busy || !token} onChange={e => { void importFile(e.target.files?.[0]); e.target.value = ''; }} /></label></details>}
      <p role="status">{notice}</p>
    </section>}
    <details className="authority-methodology"><summary>{t('Methodology, exclusions & data versions', 'Metodologiya, istisnalar və məlumat versiyaları')}</summary><p>{data.methodology}</p><ul>{data.limitations.map(l => <li key={l}>{l}</li>)}</ul><p>{t('Observed usable curb segments', 'Müşahidə ilə təsdiqli bordür seqmentləri')}: {data.summary.observed_usable_curb_segments}</p><p>Build: {data.generated_at} · Git: {data.source_versions.code_revision} · Inventory: {data.source_versions.verified_inventory} · Run: {data.run_id}</p><p>{data.summary.excluded_segments} {t('segments omitted; full reasons in JSON snapshot/API.', 'seqment çıxarılıb; tam səbəblər JSON/API-dədir.')}</p><ul>{data.exclusions.slice(0, 20).map(e => <li key={e.segment_id}>{e.segment_id}: {e.reason}</li>)}</ul></details>
    <section className="authority-print"><h1>BurdaSaxla · 28 May · Authority survey report</h1><p>Run {data.run_id} · Built {data.generated_at} · OSM {data.source_versions.osm} · Inventory {data.source_versions.verified_inventory}</p><p>{data.methodology}</p><div className="print-list">{rows.map(c => <PrintCandidate key={c.candidate_id} c={c} />)}</div><div className="print-candidate">{candidate && <PrintCandidate c={candidate} />}</div><ul>{data.limitations.map(l => <li key={l}>{l}</li>)}</ul></section>
  </main>;
}
function PrintCandidate({ c }: { c: Candidate }) {
  return <article><h2>{c.is_synthetic_example ? 'SIMULATED EXAMPLE · ' : ''}{c.name}</h2><p>{c.candidate_id} · {c.road_side} · ≈{c.length_m} m · {c.review_status} · {c.candidate_class}</p><p>{c.reasons.join('; ')}</p><p>Missing: {c.missing_evidence.join('; ')}</p><p>Constraints: {c.constraints.join(', ') || 'Unknown'} · Network distance / benefit / score: not available</p><p>Source: {c.source_url} · Algorithm {c.algorithm_version}</p><p>Approximate geometry: {JSON.stringify(c.geometry.coordinates)}</p><b>Requires official field / engineering / legal assessment. Not an authorized stop.</b></article>;
}
