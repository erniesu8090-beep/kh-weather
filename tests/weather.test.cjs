const test = require('node:test');
const assert = require('node:assert/strict');
const W = require('../weather.js');

test('missing, sentinel and invalid rainfall never become zero', () => {
  for (const input of [null, undefined, '', ' ', '-', 'X', '-99', '-998', Infinity, 'NaN']) assert.equal(W.finiteRain(input), null);
  assert.equal(W.finiteRain('0.0'), 0);
  assert.equal(W.finiteRain('1,250.5'), 1250.5);
  assert.equal(W.rainLevel(null).text, '暫無資料');
  assert.equal(W.rainLevel({ten_min: '-'}).text, '暫無資料');
  assert.equal(W.rainLevel({ten_min: '0'}).text, '近10分鐘無雨');
});
test('CWA rainfall categories use duration and exact thresholds', () => {
  assert.equal(W.rainLevel({ten_min: 3, one_hr: 15}).text, '降雨中');
  assert.equal(W.rainLevel({one_hr: 40}).text, '大雨');
  assert.equal(W.rainLevel({all_hr: 80}).text, '大雨');
  assert.equal(W.rainLevel({three_hr: 100}).text, '豪雨');
  assert.equal(W.rainLevel({all_hr: 200}).text, '豪雨');
  assert.equal(W.rainLevel({three_hr: 200}).text, '大豪雨');
  assert.equal(W.rainLevel({all_hr: 350}).text, '大豪雨');
  assert.equal(W.rainLevel({all_hr: 500}).text, '超大豪雨');
});
test('Taiwan times are interpreted independently of browser timezone', () => {
  assert.equal(W.timestamp('2026/10/17 09:10:00'), Date.parse('2026-10-17T01:10:00Z'));
  assert.equal(W.timestamp('2026-10-17T09:10:00+08:00'), Date.parse('2026-10-17T01:10:00Z'));
  const now = Date.parse('2026-10-17T01:40:01Z');
  assert.equal(W.stale('2026-10-17 09:10:00', now), true);
  assert.equal(W.stale('2026-10-17 09:30:00', now), false);
  assert.equal(W.stale('', now), true);
  assert.equal(W.stale('2026-10-17 11:30:00', now), true);
});
test('time ranges use actual timestamps, not assumed frame counts', () => {
  const scans = [
    {url: 'c', time: '2026/10/17 09:30:00'},
    {url: 'a', time: '2026/10/17 08:00:00'},
    {url: 'b', time: '2026/10/17 09:02:00'},
    {url: 'd', time: '2026/10/17 09:15:00'}
  ];
  assert.deepEqual(W.filterScans(scans, .5).map(s => s.url), ['b', 'd', 'c']);
  assert.equal(W.filterScans(scans, 6).length, 4);
  assert.equal(scans[0].url, 'c');
  assert.deepEqual(W.filterScans(null, 1), []);
});
test('API normalization preserves per-station observation times and missing data', () => {
  const raw = [{StationId:'C0V450', StationName:'鳳森', GeoInfo:{CountyName:'高雄市',TownName:'小港區'}, ObsTime:{DateTime:'2026-10-17T09:20:00+08:00'}, RainfallElement:{Past10Min:{Precipitation:'-99'},Past1hr:{Precipitation:'0.0'}}}, {StationId:'other',GeoInfo:{CountyName:'臺北市'}}];
  const [st] = W.normalizeStations(raw);
  assert.equal(W.normalizeStations(raw).length, 1);
  assert.equal(st.code, 'C0V45');
  assert.equal(st.fullCode, 'C0V450');
  assert.equal(st.ten_min, '-');
  assert.equal(st.ten_min_num, null);
  assert.equal(st.one_hr_num, 0);
  assert.equal(st.observed_at, raw[0].ObsTime.DateTime);
});
