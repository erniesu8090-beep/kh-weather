/* Shared data rules: missing observations must never become zero rainfall. */
(function (root) {
  const finiteRain = value => {
    if (value === null || value === undefined || String(value).trim() === '') return null;
    const n = Number(String(value).replaceAll(',', '').trim());
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  const rainLevel = station => {
    const ten = finiteRain(station?.ten_min);
    const one = finiteRain(station?.one_hr);
    const three = finiteRain(station?.three_hr);
    const day = finiteRain(station?.all_hr);
    if (day >= 500) return { text: '超大豪雨', tone: 'danger' };
    if (day >= 350 || three >= 200) return { text: '大豪雨', tone: 'danger' };
    if (day >= 200 || three >= 100) return { text: '豪雨', tone: 'danger' };
    if (day >= 80 || one >= 40) return { text: '大雨', tone: 'warning' };
    if (ten === null) return { text: '暫無資料', tone: 'muted' };
    return { text: ten > 0 ? '降雨中' : '近10分鐘無雨', tone: ten > 0 ? 'primary' : 'muted' };
  };
  function timestamp(value) {
    if (!value) return NaN;
    const normalized = String(value).trim().replaceAll('/', '-').replace(' ', 'T');
    return Date.parse(/(?:Z|[+-]\d\d:?\d\d)$/i.test(normalized) ? normalized : normalized + '+08:00');
  }
  const stale = (value, now = Date.now(), minutes = 30) => !Number.isFinite(timestamp(value)) || now - timestamp(value) > minutes * 60000 || timestamp(value) - now > 5 * 60000;
  const filterScans = (scans, hours) => {
    const ordered = [...(scans || [])].filter(s => s?.url).sort((a, b) => timestamp(a.time) - timestamp(b.time));
    const latest = timestamp(ordered.at(-1)?.time);
    if (hours === 6 || !Number.isFinite(latest)) return ordered;
    return ordered.filter(s => timestamp(s.time) >= latest - hours * 3600000);
  };
  function normalizeStations(rawStations) {
    return (rawStations || []).filter(st => st.GeoInfo?.CountyName?.includes('高雄') || String(st.GeoInfo?.CountyCode) === '64000').map(st => {
      const id = String(st.StationId || '');
      const result = { code: id.length === 6 && /[0-9]$/.test(id) ? id.slice(0, 5) : id, fullCode: id, name: st.StationName, region: st.GeoInfo?.TownName, observed_at: st.ObsTime?.DateTime || '' };
      for (const [field, source] of Object.entries({ten_min: 'Past10Min', one_hr: 'Past1hr', three_hr: 'Past3hr', six_hr: 'Past6Hr', twl_hr: 'Past12hr', all_hr: 'Past24hr', today: 'Now'})) {
        const n = finiteRain(st.RainfallElement?.[source]?.Precipitation);
        result[field] = n === null ? '-' : String(n);
        result[field + '_num'] = n;
      }
      return result;
    });
  }
  const api = { finiteRain, rainLevel, timestamp, stale, filterScans, normalizeStations };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Weather = api;
})(typeof window === 'undefined' ? globalThis : window);
