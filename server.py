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
    def fetch_rainfall(cls):
        now = time.time()
        if cls._cache['rainfall']['data'] and (now - cls._cache['rainfall']['time'] < cls.CACHE_DURATION):
            return cls._cache['rainfall']['data']

        def parse_float(val):
            try:
                if val is None:
                    return 0.0
                v = str(val).replace(',', '').strip()
                if v in ('-', 'X', '', 'None', 'null'):
                    return 0.0
                return float(v)
            except Exception:
                return 0.0

        datatime = ""
        gentime = ""
        stations = []

        # 1. 優先嘗試爬取 CWA 網頁 HTML 表格
        url = f"https://www.cwa.gov.tw/V8/C/P/Rainfall/MOD_10M/64.html?ID={int(now * 1000)}"
        req = urllib.request.Request(url, headers=cls.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode('utf-8', errors='ignore')

            m_time = re.search(r"data-time='([^']+)'", html)
            if m_time:
                datatime = m_time.group(1)
            m_gentime = re.search(r"data-gentime='([^']+)'", html)
            if m_gentime:
                gentime = m_gentime.group(1)

            trs = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
            for tr in trs:
                name_match = re.search(r'<span[^>]*title=[\'"]([^\'"]+)[\'"]>([^<]+)<br>\(([^)]+)\)</span>', tr)
                if not name_match:
                    continue
                info = name_match.group(1).strip()
                name = name_match.group(2).strip()
                code = name_match.group(3).strip()

                region_match = re.search(r'<td headers="region"[^>]*>([^<]+)</td>', tr)
                region = region_match.group(1).strip() if region_match else ""

                def extract_val(header):
                    m = re.search(rf'<td headers="{header}"[^>]*>(?:<span[^>]*>)?([^<]+)(?:</span>)?</td>', tr)
                    return m.group(1).strip() if m else "-"

                ten_min_str = extract_val("TenMin")
                one_hr_str = extract_val("OneHr")
                three_hr_str = extract_val("ThreeHr")
                six_hr_str = extract_val("SixHr")
                twl_hr_str = extract_val("TwlHr")
                all_hr_str = extract_val("Allhr")
                today_str = extract_val("today")
                yesterday_str = extract_val("yesterday")

                stations.append({
                    "code": code,
                    "name": name,
                    "region": region,
                    "info": info,
                    "ten_min": ten_min_str,
                    "one_hr": one_hr_str,
                    "three_hr": three_hr_str,
                    "six_hr": six_hr_str,
                    "twl_hr": twl_hr_str,
                    "all_hr": all_hr_str,
                    "today": today_str,
                    "yesterday": yesterday_str,
                    "ten_min_num": parse_float(ten_min_str),
                    "one_hr_num": parse_float(one_hr_str),
                    "three_hr_num": parse_float(three_hr_str),
                    "six_hr_num": parse_float(six_hr_str),
                    "twl_hr_num": parse_float(twl_hr_str),
                    "all_hr_num": parse_float(all_hr_str),
                    "today_num": parse_float(today_str),
                    "yesterday_num": parse_float(yesterday_str),
                    "is_linyuan": ("林園" in region or "林園" in name or code in ['C0V72', 'C0V90'])
                })
        except Exception as e:
            pass

        # 2. 若 HTML 抓取無資料或失敗，自動切換官方 OpenData API 備援 (O-A0002-001)
        if not stations:
            try:
                api_key = 'CWA-8059CE68-7A75-4C3D-BDA6-CBF3BC6447EF'
                api_url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001?Authorization={api_key}&_={int(now * 1000)}"
                api_req = urllib.request.Request(api_url, headers=cls.get_headers())
                with urllib.request.urlopen(api_req, timeout=8) as resp:
                    api_data = json.loads(resp.read().decode('utf-8'))
                    all_raw_stations = api_data.get('records', {}).get('Station', [])
                    for st in all_raw_stations:
                        county = st.get('GeoInfo', {}).get('CountyName', '')
                        county_code = st.get('GeoInfo', {}).get('CountyCode', '')
                        if '高雄' in county or county_code == '64000':
                            raw_id = st.get('StationId', '')
                            town = st.get('GeoInfo', {}).get('TownName', '')
                            rf = st.get('RainfallElement', {})
                            ten_min = str(rf.get('Past10Min', {}).get('Precipitation', '-'))
                            one_hr = str(rf.get('Past1hr', {}).get('Precipitation', '-'))
                            three_hr = str(rf.get('Past3hr', {}).get('Precipitation', '-'))
                            six_hr = str(rf.get('Past6Hr', {}).get('Precipitation', '-'))
                            twl_hr = str(rf.get('Past12hr', {}).get('Precipitation', '-'))
                            all_hr = str(rf.get('Past24hr', {}).get('Precipitation', '-'))
                            today = str(rf.get('Now', {}).get('Precipitation', '-'))
                            yesterday = str(rf.get('Past2days', {}).get('Precipitation', '-'))

                            clean_code = raw_id[:-1] if (len(raw_id) == 6 and raw_id[-1] in '0123456789') else raw_id

                            stations.append({
                                "code": clean_code,
                                "fullCode": raw_id,
                                "name": st.get('StationName', ''),
                                "region": f"{town}區" if town else "高雄市",
                                "info": f"{raw_id} 高雄市{town}區 {st.get('StationName', '')} - 中央氣象署",
                                "ten_min": ten_min,
                                "one_hr": one_hr,
                                "three_hr": three_hr,
                                "six_hr": six_hr,
                                "twl_hr": twl_hr,
                                "all_hr": all_hr,
                                "today": today,
                                "yesterday": yesterday,
                                "ten_min_num": parse_float(ten_min),
                                "one_hr_num": parse_float(one_hr),
                                "three_hr_num": parse_float(three_hr),
                                "six_hr_num": parse_float(six_hr),
                                "twl_hr_num": parse_float(twl_hr),
                                "all_hr_num": parse_float(all_hr),
                                "today_num": parse_float(today),
                                "yesterday_num": parse_float(yesterday),
                                "is_linyuan": ("林園" in town or raw_id.startswith('C0V90') or raw_id.startswith('C0V72'))
                            })
                    datatime = time.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                pass

        if not stations and cls._cache['rainfall']['data']:
            return cls._cache['rainfall']['data']

        result = {
            'datatime': datatime,
            'gentime': gentime,
            'fetch_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_stations': len(stations),
            'stations': stations
        }
        if stations:
            cls._cache['rainfall'] = {'time': now, 'data': result}
        return result

    @classmethod
    def fetch_radar(cls):
        now = time.time()
        if cls._cache['radar']['data'] and (now - cls._cache['radar']['time'] < cls.CACHE_DURATION):
            return cls._cache['radar']['data']

        url = f"https://www.cwa.gov.tw/Data/js/obs_img/Observe_radar_rain.js?_={int(now * 1000)}"
        req = urllib.request.Request(url, headers=cls.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                js_content = resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            if cls._cache['radar']['data']:
                return cls._cache['radar']['data']
            return {'error': str(e), 'areas': {}}

        areas = {}
        for area_key, area_name in [('Area0', '新北樹林'), ('Area1', '臺中南屯'), ('Area2', '高雄林園')]:
            idx = js_content.find(f"'{area_key}'")
            scans_3600 = []
            scans_1000 = []
            if idx != -1:
                sub = js_content[idx:]
                next_area_idx = sub.find("'Area", 10)
                end_idx = next_area_idx if next_area_idx != -1 else len(sub)
                area_sub = sub[:end_idx]

                s0_idx = area_sub.find("'size0'")
                s1_idx = area_sub.find("'size1'")

                if s0_idx != -1:
                    s0_sub = area_sub[s0_idx:s1_idx] if s1_idx != -1 else area_sub[s0_idx:]
                    entries = re.findall(r"\{\s*\"img\":'([^']+)',\s*'text':'([^']+)'\}", s0_sub)
                    for img_rel, t_str in entries:
                        scans_3600.append({
                            'url': f"https://www.cwa.gov.tw/Data/radar_rain/{img_rel}",
                            'filename': img_rel,
                            'time': t_str
                        })

                if s1_idx != -1:
                    s1_sub = area_sub[s1_idx:]
                    entries = re.findall(r"\{\s*\"img\":'([^']+)',\s*'text':'([^']+)'\}", s1_sub)
                    for img_rel, t_str in entries:
                        scans_1000.append({
                            'url': f"https://www.cwa.gov.tw/Data/radar_rain/{img_rel}",
                            'filename': img_rel,
                            'time': t_str
                        })

            areas[area_key] = {
                'name': area_name,
                'scans_hd': scans_3600,
                'scans_sd': scans_1000,
                'latest_hd': scans_3600[0] if scans_3600 else None,
                'latest_sd': scans_1000[0] if scans_1000 else None,
            }

        # 解析全臺無地形與有地形雷達 (Observe_radar.js: CV1_3600 & CV1_TW_3600)
        no_terrain_scans = []
        with_terrain_scans = []
        try:
            rad_url = f"https://www.cwa.gov.tw/Data/js/obs_img/Observe_radar.js?_={int(now * 1000)}"
            rad_req = urllib.request.Request(rad_url, headers=cls.get_headers())
            with urllib.request.urlopen(rad_req, timeout=8) as rad_resp:
                rad_js = rad_resp.read().decode('utf-8', errors='ignore')
                no_t_entries = re.findall(r"\{\s*\"img\":'(CV1_3600_[^']+)',\s*'text':'([^']+)'\}", rad_js)
                for img_rel, t_str in no_t_entries:
                    no_terrain_scans.append({
                        'url': f"https://www.cwa.gov.tw/Data/radar/{img_rel}",
                        'filename': img_rel,
                        'time': t_str
                    })
                with_t_entries = re.findall(r"\{\s*\"img\":'(CV1_TW_3600_[^']+)',\s*'text':'([^']+)'\}", rad_js)
                for img_rel, t_str in with_t_entries:
                    with_terrain_scans.append({
                        'url': f"https://www.cwa.gov.tw/Data/radar/{img_rel}",
                        'filename': img_rel,
                        'time': t_str
                    })
        except Exception:
            pass

        # 解析全臺衛星雲圖 (臺灣彩色色調強化 LCC_IR1_CR_2750 / LCC_IR1_CR_1000)
        satellite_scans = []
        try:
            sat_url = f"https://www.cwa.gov.tw/Data/js/obs_img/Observe_sat.js?_={int(now * 1000)}"
            sat_req = urllib.request.Request(sat_url, headers=cls.get_headers())
            with urllib.request.urlopen(sat_req, timeout=8) as sat_resp:
                sat_js = sat_resp.read().decode('utf-8', errors='ignore')
                entries = re.findall(r"\{\s*\"img\":'(LCC_IR1_CR_2750/[^']+)',\s*'text':'([^']+)'\}", sat_js)
                if not entries:
                    entries = re.findall(r"\{\s*\"img\":'(LCC_IR1_CR_1000/[^']+)',\s*'text':'([^']+)'\}", sat_js)
                for img_rel, t_str in entries:
                    satellite_scans.append({
                        'url': f"https://www.cwa.gov.tw/Data/satellite/{img_rel}",
                        'filename': img_rel,
                        'time': t_str
                    })
        except Exception:
            pass

        result = {
            'fetch_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'areas': areas,
            'national_radar': {
                'no_terrain': 'https://www.cwa.gov.tw/Data/radar/CV1_3600.png',
                'with_terrain': 'https://www.cwa.gov.tw/Data/radar/CV1_TW_3600.png',
                'rain_radar': 'https://www.cwa.gov.tw/Data/radar_rain/CV1_RCSL_1000/CV1_RCSL_1000.png'
            },
            'no_terrain_scans': no_terrain_scans,
            'with_terrain_scans': with_terrain_scans,
            'satellite_scans': satellite_scans
        }
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
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            data = CWADataFetcher.fetch_rainfall()
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
            combined = {
                'rainfall': CWADataFetcher.fetch_rainfall(),
                'radar': CWADataFetcher.fetch_radar(),
                'server_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }
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
            httpd = socketserver.TCPServer(("", port), MonitorRequestHandler)
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


