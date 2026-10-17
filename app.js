    // 舊代碼自動遷移映射表
    const DEPRECATED_CODE_MAP = {
      'C0V72': 'C0V90', // 原林園 -> 汕尾
      'C0V73': 'C0V45', // 原大寮 -> 鳳森
      'C0V68': 'CAP04', // 原仁武 -> 國一N361K
      'C0V21': 'C1V20', // 原復興 -> 梅山
      'C0V93': '01V07'  // 原天池 -> 天池新碼 01V07
    };

    const savedStations = (() => {
      try {
        const stored = JSON.parse(localStorage.getItem('kh_rain_stations'));
        if (Array.isArray(stored) && stored.length >= 2) {
          const s1 = DEPRECATED_CODE_MAP[stored[0]] || stored[0];
          const s2 = DEPRECATED_CODE_MAP[stored[1]] || stored[1];
          return [s1, s2];
        }
      } catch (e) {}
      return ['C0V45', 'C0V84'];
    })();

    // --- 應用狀態 ---
    const state = {
      radarMode: 'linyuan',
      data: null,
      pending: null,
      lastAttempt: 0,
      imageToken: 0,
      images: new Map(),
      radarScans: [],
      activeIndex: 0,
      isPlaying: false,
      timer: null,
      hoursFilter: 1,
      stations: [],
      selectedStations: savedStations
    };

    // --- 即時時鐘 ---
    function updateClock() {
      const now = new Date();
      document.getElementById('headerClock').textContent = now.toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
    }
    setInterval(updateClock, 1000);
    updateClock();

    // --- 動態更新頂部 Header 地區標籤 ---
    function updateHeaderDistrictTag() {
      const code1 = state.selectedStations[0] || 'C0V45';
      const code2 = state.selectedStations[1] || 'C0V84';

      const st1 = findStation(code1);
      const st2 = findStation(code2);

      let d1 = '', d2 = '';
      for (const grp of KAOHSIUNG_STATIONS_GROUPS) {
        const s1 = grp.stations.find(s => s.code === code1);
        if (s1) d1 = s1.district;
        const s2 = grp.stations.find(s => s.code === code2);
        if (s2) d2 = s2.district;
      }
      if (!d1 && st1 && st1.region) d1 = st1.region.replace('區', '');
      if (!d2 && st2 && st2.region) d2 = st2.region.replace('區', '');

      const tag = document.getElementById('headerDistrictTag');
      if (!tag) return;

      if (d1 && d2) {
        if (d1 === d2) {
          tag.innerText = `📍 ${d1}區`;
        } else {
          tag.innerText = `📍 ${d1} · ${d2}`;
        }
      } else if (d1 || d2) {
        tag.innerText = `📍 ${d1 || d2}區`;
      } else {
        tag.innerText = `📍 即時測站`;
      }
    }

    // --- 初始化測站下拉選單 ---
    function initStationDropdowns() {
      const selectConfigs = [
        { id: 'stationSelect1', defaultVal: state.selectedStations[0] || 'C0V45', index: 0 },
        { id: 'stationSelect2', defaultVal: state.selectedStations[1] || 'C0V84', index: 1 }
      ];

      selectConfigs.forEach(({ id, defaultVal, index }) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        sel.innerHTML = '';

        KAOHSIUNG_STATIONS_GROUPS.forEach(grp => {
          const optgrp = document.createElement('optgroup');
          optgrp.label = grp.group;
          grp.stations.forEach(st => {
            const opt = document.createElement('option');
            opt.value = st.code;
            opt.textContent = `${st.name} (${st.district})`;
            optgrp.appendChild(opt);
          });
          sel.appendChild(optgrp);
        });

        sel.value = defaultVal;
        if (!sel.value) { sel.value = index === 0 ? 'C0V45' : 'C0V84'; state.selectedStations[index] = sel.value; }

        sel.addEventListener('change', () => {
          state.selectedStations[index] = sel.value;
          try {
            localStorage.setItem('kh_rain_stations', JSON.stringify(state.selectedStations));
          } catch(e) {}
          
          updateHeaderDistrictTag();

          if (state.stations && state.stations.length > 0) {
            renderRainfall({ stations: state.stations });
            updateFreshness();
          } else {
            fetchData();
          }
        });
      });

      updateHeaderDistrictTag();
    }

    // --- 資料載入 ---
    const isLocal = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
    async function fetchJSON(url, timeout = 12000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
      } finally { clearTimeout(timer); }
    }
    function loadScript(id, path, globalName) {
      return new Promise((resolve, reject) => {
        document.getElementById(id)?.remove();
        const script = document.createElement('script');
        script.id = id;
        const finish = error => {
          clearTimeout(timer);
          script.onload = script.onerror = null;
          script.remove();
          if (error) reject(error); else resolve(window[globalName]);
        };
        const timer = setTimeout(() => finish(new Error('資料來源逾時')), 12000);
        script.src = `https://www.cwa.gov.tw/Data/js/obs_img/${path}?_=${Math.floor(Date.now() / 60000)}`;
        script.onload = () => finish();
        script.onerror = () => finish(new Error('資料來源連線失敗'));
        document.body.appendChild(script);
      });
    }
    async function directFallback() {
      const radar = {};
      const toScans = (raw, folder) => Object.values(raw || {}).map(i => ({ url: `https://www.cwa.gov.tw/Data/${folder}/${i.img}`, time: i.text }));
      await Promise.allSettled([
        loadScript('cwaRadarRainScript', 'Observe_radar_rain.js', 'RadarRainImg').then(data => {
          radar.areas = { Area2: { scans_hd: toScans(data?.Area2?.size0, 'radar_rain') } };
        }),
        loadScript('cwaRadarScript', 'Observe_radar.js', 'RadarImg').then(data => {
          radar.no_terrain_scans = toScans(data?.Tab0?.Area0?.size0, 'radar');
          radar.with_terrain_scans = toScans(data?.Tab0?.Area1?.size0, 'radar');
        }),
        loadScript('cwaSatScript', 'Observe_sat.js', 'SatImg').then(data => {
          radar.satellite_scans = toScans(data?.Tab1?.Area1?.size0?.C || data?.Tab1?.Area1?.size1?.C, 'satellite');
        })
      ]);
      return radar;
    }
    let publicConfig;
    async function fetchLiveRainfall() {
      publicConfig ||= await fetchJSON('./config.json');
      if (!publicConfig.cwaApiKey) throw new Error('未設定氣象署公開金鑰');
      const payload = await fetchJSON('https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001?Authorization=' + encodeURIComponent(publicConfig.cwaApiKey));
      const stations = Weather.normalizeStations(payload?.records?.Station);
      if (!stations.length) throw new Error('氣象署未回傳高雄測站');
      return {stations, source: 'OpenData API', fetch_time: new Date().toISOString()};
    }
    async function fetchHostedData() {
      const [rain, radar, snapshot] = await Promise.allSettled([fetchLiveRainfall(), directFallback(), fetchJSON('./weather.json')]);
      const backup = snapshot.status === 'fulfilled' ? snapshot.value : {};
      const liveRadar = radar.status === 'fulfilled' ? radar.value : {};
      const mergedRadar = {...backup.radar};
      for (const key of ['no_terrain_scans', 'with_terrain_scans', 'satellite_scans']) {
        if (liveRadar[key]?.length) mergedRadar[key] = liveRadar[key];
      }
      if (liveRadar.areas?.Area2?.scans_hd?.length) mergedRadar.areas = liveRadar.areas;
      return {
        rainfall: rain.status === 'fulfilled' ? rain.value : backup.rainfall || {stations: []},
        radar: mergedRadar,
        generated_at: rain.status === 'fulfilled' ? new Date().toLocaleString('sv-SE', {timeZone: 'Asia/Taipei'}) : backup.generated_at,
        backup: rain.status !== 'fulfilled'
      };
    }
    function updateFreshness() {
      const data = state.data;
      const status = document.getElementById('dataStatus');
      if (!data || state.connectionFailed) return;
      const selected = state.selectedStations.map(findStation);
      const outdated = data.rainfall?.stale || selected.some(st => !st || Weather.stale(st.observed_at || data.rainfall?.datatime));
      const missing = selected.some(st => Weather.finiteRain(st?.ten_min) === null);
      status.dataset.tone = outdated || missing ? 'warning' : 'success';
      status.textContent = outdated ? '觀測資料過期或時間不明，請留意資料時間' : missing ? '部分測站暫無資料，請選擇其他測站' : `觀測資料正常 · ${data.backup ? '備援觀測資料' : '氣象署即時連線'} · 每分鐘檢查更新`;
      document.getElementById('sourceTime').textContent = `資料取得：${Weather.formatTime(data.generated_at || data.rainfall?.fetch_time)}`;
    }
    function fetchData(force = false) {
      if (state.pending) return state.pending;
      if (force !== true && Date.now() - state.lastAttempt < 10000) return Promise.resolve();
      state.lastAttempt = Date.now();
      const button = document.getElementById('btnRefresh');
      button.disabled = true;
      document.getElementById('iconRefresh').classList.add('spinning');
      state.pending = (async () => {
        try {
          let data;
          try { data = await (isLocal ? fetchJSON('/api/all', 25000) : fetchHostedData()); }
          catch (error) {
            if (!state.data) state.data = {};
            throw error;
          }
          if (!data || !Array.isArray(data.rainfall?.stations)) throw new Error('觀測資料格式錯誤');
          state.data = data;
          state.connectionFailed = false;
          renderRainfall(data.rainfall);
          renderRadar(data.radar || {});
          updateFreshness();
          // Independent radar sources may recover even if the deployed snapshot lacks a product.
          if (!data.radar?.areas?.Area2?.scans_hd?.length) {
            const live = await directFallback();
            state.data.radar = { ...data.radar, ...live };
            renderRadar(state.data.radar);
          }
        } catch (error) {
          state.connectionFailed = true;
          const status = document.getElementById('dataStatus');
          status.dataset.tone = 'warning';
          status.textContent = state.data?.rainfall ? '更新失敗，保留上次觀測 · 請確認時間後使用' : '無法取得資料，請確認網路後按「更新」重試';
          // Rainfall failure must not prevent independent radar display.
          const live = await directFallback();
          if (!state.data) state.data = {};
          state.data.radar = { ...state.data.radar, ...live };
          renderRadar(state.data.radar);
          if (!state.data.rainfall) renderRainfall({ stations: [] });
        } finally {
          button.disabled = false;
          document.getElementById('iconRefresh').classList.remove('spinning');
          state.pending = null;
        }
      })();
      return state.pending;
    }

    // --- 測站搜尋匹配 ---
    function findStation(code) {
      if (!code) return null;
      const targetCode = String(code).trim().toUpperCase();

      // 先查選單裡的測站定義
      let stationMeta = null;
      for (const grp of KAOHSIUNG_STATIONS_GROUPS) {
        const found = grp.stations.find(s => String(s.code).toUpperCase() === targetCode);
        if (found) {
          stationMeta = found;
          break;
        }
      }

      // 1. 從已下載的即時雨量資料中找
      if (state.stations && state.stations.length > 0) {
        // (1) 代碼完全比對
        let matched = state.stations.find(s => {
          const sCode = String(s.code || '').trim().toUpperCase();
          const sFull = String(s.fullCode || '').trim().toUpperCase();
          return (sCode && sCode === targetCode) || (sFull && sFull === targetCode);
        });
        if (matched) return matched;

        // (2) 5 碼前綴比對 (處理如 46744 vs 467441, C0V45 vs C0V450)
        if (targetCode.length >= 4) {
          const tPrefix = targetCode.slice(0, 5);
          matched = state.stations.find(s => {
            const sCode = String(s.code || '').trim().toUpperCase();
            const sFull = String(s.fullCode || '').trim().toUpperCase();
            return (sCode.length >= 4 && sCode.slice(0, 5) === tPrefix) || 
                   (sFull.length >= 4 && sFull.slice(0, 5) === tPrefix);
          });
          if (matched) return matched;
        }

        // (3) 站名比對
        if (stationMeta && stationMeta.name) {
          matched = state.stations.find(s => s.name === stationMeta.name);
          if (matched) return matched;
        }
      }

      return null;
    }

    // --- 渲染 2 個自選測站雨量卡片 ---
    function renderRainfall(data) {
      if (!data || !data.stations) return;
      state.stations = data.stations;

      const code1 = state.selectedStations[0] || 'C0V45';
      const code2 = state.selectedStations[1] || 'C0V84';

      const st1 = findStation(code1);
      const st2 = findStation(code2);

      fillCard('card1', st1, code1);
      fillCard('card2', st2, code2);
      updateHeaderDistrictTag();
    }

    function fillCard(cardPrefix, st, targetCode) {
      const meta = KAOHSIUNG_STATIONS_GROUPS.flatMap(g => g.stations).find(s => s.code === targetCode);
      document.getElementById(`${cardPrefix}Code`).textContent = `${targetCode} · ${meta?.district || '測站'}`;
      for (const [suffix, key] of [['_10m', 'ten_min'], ['_1h', 'one_hr'], ['_3h', 'three_hr'], ['_24h', 'all_hr'], ['Today', 'today']]) {
        const n = Weather.finiteRain(st?.[key]);
        document.getElementById(cardPrefix + suffix).textContent = (n === null ? '—' : n.toFixed(1)) + (suffix === '_10m' ? '' : ' mm');
      }
      const observed = st?.observed_at || state.data?.rainfall?.datatime;
      const badge = document.getElementById(`${cardPrefix}Status`);
      const level = Weather.rainLevel(st);
      badge.textContent = level.text;
      badge.dataset.tone = level.tone;
      document.getElementById(`${cardPrefix}Time`).title = observed || '觀測時間不明';
      document.getElementById(`${cardPrefix}Time`).textContent = `觀測：${Weather.formatTime(observed)}${st && Weather.stale(observed) ? ' · 已過期／時間不明' : ''}`;
    }
    function renderRadar(data) {
      const modes = {
        linyuan: [data?.areas?.Area2?.scans_hd, '林園降雨雷達 · 250m'],
        radar_no_terrain: [data?.no_terrain_scans, '全臺雷達 · 無地形'],
        radar_with_terrain: [data?.with_terrain_scans, '全臺雷達 · 有地形'],
        satellite_taiwan: [data?.satellite_scans, '衛星雲圖 · 彩色色調強化']
      };
      const [all, label] = modes[state.radarMode];
      const previousTime = state.radarScans[state.activeIndex]?.time;
      const wasLatest = state.activeIndex >= state.radarScans.length - 1;
      state.radarScans = Weather.filterScans(all, state.hoursFilter);
      const previousIndex = state.radarScans.findIndex(s => s.time === previousTime);
      state.activeIndex = (state.isPlaying || !wasLatest) && previousIndex >= 0 ? previousIndex : Math.max(0, state.radarScans.length - 1);
      document.getElementById('radarBadge').textContent = label;
      document.querySelector('.dbz-legend-bar').hidden = state.radarMode === 'satellite_taiwan';
      document.getElementById('radarImg').alt = label;
      if (state.isPlaying && state.radarScans.length < 2) togglePlay();
      const slider = document.getElementById('radarSlider');
      slider.max = Math.max(0, state.radarScans.length - 1);
      slider.value = state.activeIndex;
      slider.disabled = state.radarScans.length < 2;
      document.querySelectorAll('.btn-circle-ctrl').forEach(b => b.disabled = state.radarScans.length < 2);
      updateRadarFrame();
    }
    function loadImage(url) {
      if (state.images.has(url)) return state.images.get(url);
      const promise = new Promise((resolve, reject) => {
        const image = new Image();
        const timer = setTimeout(() => { image.onload = image.onerror = null; reject(new Error('影像載入逾時')); }, 12000);
        image.onload = () => { clearTimeout(timer); resolve(image); };
        image.onerror = () => { clearTimeout(timer); reject(new Error('影像載入失敗')); };
        image.src = url;
      });
      state.images.set(url, promise);
      promise.catch(() => state.images.delete(url));
      if (state.images.size > 100) state.images.delete(state.images.keys().next().value);
      return promise;
    }
    async function updateRadarFrame() {
      const token = ++state.imageToken;
      const current = state.radarScans[state.activeIndex];
      const img = document.getElementById('radarImg');
      const status = document.getElementById('imageStatus');
      const viewport = document.querySelector('.radar-viewport');
      document.getElementById('frameCounter').textContent = `${current ? state.activeIndex + 1 : 0} / ${state.radarScans.length}`;
      document.getElementById('radarSlider').value = state.activeIndex;
      if (!current) {
        img.hidden = true; status.hidden = false;
        status.textContent = '此影像來源暫無資料，請切換模式或稍後更新';
        document.getElementById('radarTimestamp').textContent = '尚無影像';
        viewport.setAttribute('aria-busy', 'false');
        return;
      }
      viewport.setAttribute('aria-busy', 'true');
      status.hidden = false; status.textContent = '影像載入中…';
      try {
        await loadImage(current.url);
        if (token !== state.imageToken) return;
        img.src = current.url; img.hidden = false; status.hidden = true;
        document.getElementById('radarTimestamp').textContent = `${current.time || '時間不明'}${state.activeIndex < state.radarScans.length - 1 ? ' · 歷史影格' : ''}${Weather.stale(state.radarScans.at(-1)?.time, Date.now(), 30) ? ' · 來源資料過期' : ''}`;
        const next = state.radarScans[(state.activeIndex + 1) % state.radarScans.length];
        if (next) loadImage(next.url).catch(() => {});
      } catch (error) {
        if (token !== state.imageToken) return;
        img.hidden = true; status.hidden = false;
        status.textContent = '影像載入失敗，可切換影格或按更新重試';
        document.getElementById('radarTimestamp').textContent = `${current.time || '時間不明'} · 影像未載入`;
      } finally {
        if (token === state.imageToken) viewport.setAttribute('aria-busy', 'false');
      }
    }

    // --- 播放動畫控制 ---
    function togglePlay() {
      state.isPlaying = !state.isPlaying;
      const button = document.getElementById('btnPlayPause');
      document.getElementById('playIcon').textContent = state.isPlaying ? 'Ⅱ' : '▶';
      button.setAttribute('aria-pressed', String(state.isPlaying));
      button.setAttribute('aria-label', state.isPlaying ? '暫停影像' : '播放影像');
      clearInterval(state.timer);
      if (state.isPlaying) {
        state.timer = setInterval(() => {
          if (document.hidden || state.radarScans.length < 2 || document.querySelector('.radar-viewport').getAttribute('aria-busy') === 'true') return;
          state.activeIndex = (state.activeIndex + 1) % state.radarScans.length;
          updateRadarFrame();
        }, 800);
      }
    }

    // --- 事件監聽器設定 ---
    document.addEventListener('DOMContentLoaded', () => {


      // 立即更新
      document.getElementById('btnRefresh').addEventListener('click', () => { state.images.clear(); fetchData(true); });

      // 播放按鈕
      document.getElementById('btnPlayPause').addEventListener('click', togglePlay);
      document.getElementById('btnFirst').addEventListener('click', () => {
        state.activeIndex = 0;
        updateRadarFrame();
      });
      document.getElementById('btnLast').addEventListener('click', () => {
        state.activeIndex = state.radarScans.length - 1;
        updateRadarFrame();
      });
      document.getElementById('btnPrev').addEventListener('click', () => {
        if (state.activeIndex > 0) state.activeIndex--;
        updateRadarFrame();
      });
      document.getElementById('btnNext').addEventListener('click', () => {
        if (state.activeIndex < state.radarScans.length - 1) state.activeIndex++;
        updateRadarFrame();
      });

      // 滑桿
      document.getElementById('radarSlider').addEventListener('input', (e) => {
        state.activeIndex = parseInt(e.target.value, 10);
        updateRadarFrame();
      });

      // 雷達模式切換
      document.querySelectorAll('#radarTabs .mode-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('#radarTabs .mode-tab-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          state.radarMode = btn.dataset.mode;
          document.querySelectorAll('#radarTabs button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
          
          const badge = document.getElementById('radarBadge');
          if (state.radarMode === 'linyuan') badge.innerText = '林園降雨雷達 (250m解析度)';
          else if (state.radarMode === 'radar_no_terrain') badge.innerText = '全臺雷達 (無地形)';
          else if (state.radarMode === 'radar_with_terrain') badge.innerText = '全臺雷達 (有地形)';
          else if (state.radarMode === 'satellite_taiwan') badge.innerText = '衛星雲圖 (全臺彩色色調強化)';
          else badge.innerText = '即時影像觀測';

          renderRadar(state.data?.radar || {});
        });
      });

      // 時間跨度按鈕
      document.querySelectorAll('#spanGroup .time-span-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('#spanGroup .time-span-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          state.hoursFilter = parseFloat(btn.dataset.hours);
          document.querySelectorAll('#spanGroup button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
          renderRadar(state.data?.radar || {});
        });
      });

      // 手機休眠喚醒或切換回分頁時立即自動更新
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          fetchData();
        }
      });
      window.addEventListener('pageshow', () => {
        fetchData();
      });

      document.querySelectorAll('#radarTabs button, #spanGroup button').forEach(b => b.setAttribute('aria-pressed', String(b.classList.contains('active'))));
      // 初始化測站下拉選單
      initStationDropdowns();

      // 初始化載入並設定每 60 秒自動背景刷新
      fetchData();
      setInterval(() => { if (!document.hidden) fetchData(); }, 60000);
      setInterval(() => { if (!document.hidden && !state.pending) { updateFreshness(); if (state.data?.rainfall) renderRainfall(state.data.rainfall); } }, 30000);

      // 註冊 PWA Service Worker (支援手機安裝專屬 App 與高清圖示)
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('./sw.js', { updateViaCache: 'none' }).catch(err => {
          console.log('SW reg error:', err);
        });
      }
    });
  