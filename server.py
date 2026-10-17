#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高雄氣象雷達回波與即時雨量監控伺服器
提供本地 Web 服務與中央氣象署 (CWA) 資料代理轉發 (無須任何第三方套件，純 Python 標準函式庫)
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import json
import re
import os
import sys
import webbrowser
import time
import logging
import math
import threading
from datetime import datetime, timezone, timedelta
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

TAIPEI = timezone(timedelta(hours=8))

def now_iso():
    return datetime.now(TAIPEI).isoformat(timespec="seconds")

def serialized(lock):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with lock:
                return fn(*args, **kwargs)
        return wrapped
    return decorate

_rain_lock = threading.RLock()
_radar_lock = threading.RLock()
from threading import Timer

# 強制設定標準輸出與錯誤輸出為 UTF-8 編碼，避免 Windows 控制台出現亂碼
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 設定 Windows 終端機視窗標題
if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("高雄氣象雷達回波 與 雨量即時監控系統")
    except Exception:
        pass

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
# Optional ignored local configuration; existing environment takes precedence.
_env_path = os.path.join(DIRECTORY, '.env')
if os.path.isfile(_env_path):
    with open(_env_path, encoding='utf-8-sig') as _env_file:
        for _line in _env_file:
            if _line.startswith('CWA_API_KEY='):
                os.environ.setdefault('CWA_API_KEY', _line.partition('=')[2].strip())



class CWADataFetcher:
    _cache = {
        'rainfall': {'time': 0, 'data': None},
        'radar': {'time': 0, 'data': None}
    }
    CACHE_DURATION = 20  # 快取 20 秒，避免對氣象署頻繁請求

    @classmethod
    def get_headers(cls):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.cwa.gov.tw/',
            'Accept': '*/*'
        }

    @classmethod
    @serialized(_rain_lock)
    def fetch_rainfall(cls):
        now = time.time()
        cached = cls._cache['rainfall']
        if cached['data'] and now - cached['time'] < cls.CACHE_DURATION:
            return cached['data']

        def number(value):
            try:
                n = float(str(value).replace(',', '').strip())
                return n if math.isfinite(n) and n >= 0 else None
            except (ValueError, TypeError):
                return None

        stations = []
        datatime = gentime = ''
        source = 'OpenData API'
        try:
            with open(os.path.join(DIRECTORY, 'config.json'), encoding='utf-8') as config_file:
                public_key = json.load(config_file).get('cwaApiKey', '')
            api_key = os.environ.get('CWA_API_KEY') or public_key
            if not api_key:
                raise RuntimeError('No CWA key configured')
            url = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001?Authorization=' + api_key
            with urllib.request.urlopen(urllib.request.Request(url, headers=cls.get_headers()), timeout=12) as response:
                payload = json.load(response)
            fields = {'ten_min': 'Past10Min', 'one_hr': 'Past1hr', 'three_hr': 'Past3hr', 'six_hr': 'Past6Hr', 'twl_hr': 'Past12hr', 'all_hr': 'Past24hr', 'today': 'Now'}
            for raw in payload.get('records', {}).get('Station', []):
                geo = raw.get('GeoInfo', {})
                if '高雄' not in geo.get('CountyName', '') and str(geo.get('CountyCode', '')) != '64000':
                    continue
                raw_id = str(raw.get('StationId', ''))
                code = raw_id[:-1] if len(raw_id) == 6 and raw_id[-1].isdigit() else raw_id
                station = {'code': code, 'fullCode': raw_id, 'name': raw.get('StationName', ''), 'region': geo.get('TownName', ''), 'observed_at': raw.get('ObsTime', {}).get('DateTime', '')}
                for field, api_field in fields.items():
                    value = number(raw.get('RainfallElement', {}).get(api_field, {}).get('Precipitation'))
                    station[field] = '-' if value is None else str(value)
                    station[field + '_num'] = value
                stations.append(station)
            datatime = min((s['observed_at'] for s in stations if s['observed_at']), default='')
        except Exception as error:
            logging.warning('CWA OpenData fetch failed: %s', type(error).__name__)

        if not stations:
            source = 'CWA HTML'
            try:
                url = f'https://www.cwa.gov.tw/V8/C/P/Rainfall/MOD_10M/64.html?ID={int(now * 1000)}'
                with urllib.request.urlopen(urllib.request.Request(url, headers=cls.get_headers()), timeout=12) as response:
                    html = response.read().decode('utf-8', errors='replace')
                match = re.search(r"data-time=['\"]([^'\"]+)", html)
                datatime = match.group(1) if match else ''
                for row in re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL):
                    name = re.search(r"<span[^>]*title=['\"]([^'\"]+)['\"]>([^<]+)<br>\(([^)]+)\)</span>", row)
                    if not name:
                        continue
                    region = re.search(r'<td headers="region"[^>]*>([^<]+)</td>', row)
                    station = {'code': name.group(3), 'name': name.group(2), 'region': region.group(1) if region else '', 'observed_at': datatime}
                    for field, header in {'ten_min': 'TenMin', 'one_hr': 'OneHr', 'three_hr': 'ThreeHr', 'six_hr': 'SixHr', 'twl_hr': 'TwlHr', 'all_hr': 'Allhr', 'today': 'today'}.items():
                        cell = re.search(rf'<td headers="{header}"[^>]*>(.*?)</td>', row, re.DOTALL)
                        text = re.sub('<[^>]+>', '', cell.group(1)).strip() if cell else '-'
                        station[field] = text
                        station[field + '_num'] = number(text)
                    stations.append(station)
            except Exception as error:
                logging.warning('CWA HTML fetch failed: %s', type(error).__name__)
        if not stations and cached['data']:
            return {**cached['data'], 'stale': True, 'error': '上游來源無法更新'}
        result = {'datatime': datatime, 'gentime': gentime, 'fetch_time': now_iso(), 'source': source, 'stale': not bool(stations), 'stations': stations, 'total_stations': len(stations)}
        if stations:
            cls._cache['rainfall'] = {'time': now, 'data': result}
        return result

    @classmethod
    @serialized(_radar_lock)
    def fetch_radar(cls):
        now = time.time()
        cached = cls._cache['radar']
        if cached['data'] and now - cached['time'] < cls.CACHE_DURATION:
            return cached['data']

        def get_script(name):
            try:
                url = f'https://www.cwa.gov.tw/Data/js/obs_img/{name}?_={int(now * 1000)}'
                with urllib.request.urlopen(urllib.request.Request(url, headers=cls.get_headers()), timeout=10) as response:
                    return response.read().decode('utf-8', errors='replace')
            except Exception as error:
                logging.warning('CWA image metadata failed (%s): %s', name, type(error).__name__)
                return ''

        with ThreadPoolExecutor(max_workers=3) as pool:
            rain_js, radar_js, sat_js = list(pool.map(get_script, ['Observe_radar_rain.js', 'Observe_radar.js', 'Observe_sat.js']))

        def scans(content, folder, prefix=''):
            entries = re.findall(r"\{\s*\"img\":'([^']+)',\s*'text':'([^']+)'\}", content)
            return [{'url': f'https://www.cwa.gov.tw/Data/{folder}/{path}', 'filename': path, 'time': observed} for path, observed in entries if path.startswith(prefix)]

        areas = {}
        for key, name in [('Area0', '新北樹林'), ('Area1', '臺中南屯'), ('Area2', '高雄林園')]:
            start = rain_js.find(f"'{key}'")
            block = rain_js[start:] if start >= 0 else ''
            end = block.find("'Area", 10)
            if end >= 0: block = block[:end]
            sd_start = block.find("'size1'")
            hd = scans(block[:sd_start] if sd_start >= 0 else block, 'radar_rain')
            sd = scans(block[sd_start:] if sd_start >= 0 else '', 'radar_rain')
            # Keep the last good product if just one upstream feed fails.
            prior = cached['data'].get('areas', {}).get(key, {}) if cached['data'] else {}
            areas[key] = {'name': name, 'scans_hd': hd or prior.get('scans_hd', []), 'scans_sd': sd or prior.get('scans_sd', [])}
        result = {
            'fetch_time': now_iso(), 'areas': areas,
            'no_terrain_scans': scans(radar_js, 'radar', 'CV1_3600_'),
            'with_terrain_scans': scans(radar_js, 'radar', 'CV1_TW_3600_'),
            'satellite_scans': scans(sat_js, 'satellite', 'LCC_IR1_CR_2750/') or scans(sat_js, 'satellite', 'LCC_IR1_CR_1000/')
        }
        for field in ['no_terrain_scans', 'with_terrain_scans', 'satellite_scans']:
            if not result[field] and cached['data']:
                result[field] = cached['data'].get(field, [])
        result['stale'] = not all([rain_js, radar_js, sat_js])
        cls._cache['radar'] = {'time': now, 'data': result}
        return result


class MonitorRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        if self.path.startswith('/api/rainfall'):
            data = CWADataFetcher.fetch_rainfall()
            self.send_response(200 if data.get('stations') else 503)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        elif self.path.startswith('/api/radar'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            data = CWADataFetcher.fetch_radar()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        elif self.path.startswith('/api/all'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            with ThreadPoolExecutor(max_workers=2) as pool:
                rain_future = pool.submit(CWADataFetcher.fetch_rainfall)
                radar_future = pool.submit(CWADataFetcher.fetch_radar)
                combined = {'rainfall': rain_future.result(), 'radar': radar_future.result(), 'generated_at': now_iso()}
            self.wfile.write(json.dumps(combined, ensure_ascii=False).encode('utf-8'))
            return

        if self.path == '/' or self.path == '':
            self.path = '/index.html'

        return super().do_GET()

def open_browser(port):
    url = f'http://localhost:{port}'
    opened = False
    if sys.platform == 'win32':
        import subprocess
        edge_paths = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            "msedge"
        ]
        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            "chrome"
        ]
        
        for browser_exe in edge_paths + chrome_paths:
            try:
                subprocess.Popen([browser_exe, f"--app={url}", "--window-size=540,960"])
                opened = True
                break
            except Exception:
                continue

    if not opened:
        webbrowser.open(url)


def start_native_window(url):
    """啟動真正的 Windows 原生桌面應用視窗 (基於 WebView2)"""
    try:
        import webview
        # 建立原生獨立桌面視窗 (寬 540 x 高 950)
        window = webview.create_window(
            title='高雄氣象即時監控 · 降雨雷達與雨量',
            url=url,
            width=540,
            height=950,
            resizable=True,
            easy_drag=True
        )
        webview.start()
        return True
    except Exception as e:
        print(f"⚠️ 原生視窗模式啟動略過 ({e})，切換為瀏覽器模式...")
        return False


def create_server(start_port=8888, max_attempts=50):
    for port in range(start_port, start_port + max_attempts):
        try:
            socketserver.TCPServer.allow_reuse_address = False
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), MonitorRequestHandler)
            return httpd, port
        except OSError as e:
            if getattr(e, 'winerror', None) == 10048 or e.errno in (48, 98, 10048):
                print(f"⚠️  Port {port} 已被佔用，自動切換至 Port {port + 1}...")
                continue
            else:
                raise e
    raise RuntimeError(f"無法在範圍 {start_port} ~ {start_port + max_attempts} 找到可用 Port。")


def main():
    start_port = 8888
    if len(sys.argv) > 1:
        try:
            start_port = int(sys.argv[1])
        except ValueError:
            pass

    try:
        httpd, active_port = create_server(start_port=start_port)
        url = f"http://localhost:{active_port}"
        print("=" * 64)
        print("  高雄氣象雷達回波 與 雨量即時監控系統 (原生桌面版)")
        print(f"  伺服器已成功啟動: {url}")
        if active_port != start_port:
            print(f"  (原預設 Port {start_port} 被佔用，已自動切換至 Port {active_port})")
        print("  正在啟動獨立原生桌面視窗...")
        print("=" * 64)

        # 在背景 Daemon 線程啟動 HTTP 伺服器
        import threading
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        # 主線程啟動原生桌面視窗
        native_success = start_native_window(url)
        if not native_success:
            Timer(1.0, open_browser, args=[active_port]).start()
            # 保持伺服器運行
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n伺服器已安全停止。")
    except Exception as e:
        print(f"啟動錯誤: {e}")

if __name__ == '__main__':
    main()


