import io
import json
import time
import unittest
from unittest.mock import patch
import server

class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

def response(payload):
    return Response(json.dumps(payload).encode('utf-8'))

class FetchTests(unittest.TestCase):
    def setUp(self):
        server.CWADataFetcher._cache = {key: {'time': 0, 'data': None} for key in ('rainfall', 'radar')}

    def test_api_preserves_missing_and_observation_time(self):
        payload = {'records': {'Station': [{'StationId':'C0V450','StationName':'鳳森', 'GeoInfo': {'CountyName':'高雄市', 'TownName':'小港區'}, 'ObsTime':{'DateTime':'2026-10-17T09:10:00+08:00'},'RainfallElement': {'Past10Min':{'Precipitation':'-99'}, 'Past1hr':{'Precipitation':'0'}}}]}}
        with patch('server.urllib.request.urlopen', return_value=response(payload)) as fetch:
            data = server.CWADataFetcher.fetch_rainfall()
            self.assertEqual(data['stations'][0]['ten_min_num'], None)
            self.assertEqual(data['stations'][0]['one_hr_num'], 0)
            self.assertEqual(data['stations'][0]['code'], 'C0V45')
            self.assertEqual(data['datatime'], '2026-10-17T09:10:00+08:00')
            self.assertEqual(server.CWADataFetcher.fetch_rainfall(), data)
            self.assertEqual(fetch.call_count, 1)

    def test_html_fallback_and_missing_values(self):
        html = '''<tr data-time='2026-10-17 09:10:00'><th><span title='C0V45 高雄'>鳳森<br>(C0V45)</span></th><td headers="region">小港區</td><td headers="TenMin"><span>-</span></td><td headers="OneHr"><span>1.5</span></td></tr>'''
        with patch('server.urllib.request.urlopen', side_effect=[OSError('API unavailable'), Response(html.encode())]):
            data = server.CWADataFetcher.fetch_rainfall()
            self.assertEqual(data['source'], 'CWA HTML')
            self.assertEqual(data['stations'][0]['ten_min_num'], None)
            self.assertEqual(data['stations'][0]['one_hr_num'], 1.5)
            self.assertEqual(data['stations'][0]['observed_at'], '2026-10-17 09:10:00')

    def test_failure_retains_original_timestamp_with_stale_flag(self):
        original = {'stations': [{'code': 'C0V45'}], 'datatime': '2026-10-17 08:00:00'}
        server.CWADataFetcher._cache['rainfall'] = {'time': 0, 'data': original}
        with patch('server.urllib.request.urlopen', side_effect=OSError('offline')):
            data = server.CWADataFetcher.fetch_rainfall()
        self.assertTrue(data['stale'])
        self.assertEqual(data['datatime'], original['datatime'])
        self.assertNotIn('stale', original)

    def test_local_server_is_threaded_and_loopback_only(self):
        httpd, port = server.create_server(start_port=0, max_attempts=1)
        try:
            self.assertIsInstance(httpd, server.http.server.ThreadingHTTPServer)
            self.assertEqual(httpd.server_address[0], '127.0.0.1')
        finally:
            httpd.server_close()


class BuildTests(unittest.TestCase):
    def test_static_package_versions_assets_and_preserves_public_api_config(self):
        import tempfile
        from pathlib import Path
        from scripts.build_site import build
        rain = {'stations':[{'code':'C0V45','ten_min':'0'}]}
        radar = {'areas':{'Area2':{'scans_hd':[{'url':'https://example.test/radar.png','time':'2026/10/17 09:20'}]}}}
        base = Path(__file__).resolve().parents[1] / 'test-results'
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(base.resolve()))
            with patch('server.CWADataFetcher.fetch_rainfall', return_value=rain), patch('server.CWADataFetcher.fetch_radar', return_value=radar):
                build(folder)
            html=(Path(folder)/'index.html').read_text(encoding='utf-8')
            for name in ['styles.css','stations.js','weather.js','app.js']:
                self.assertRegex(html, name.replace('.',r'\.')+r'\?v=[0-9a-f]{12}')
            self.assertEqual(json.loads((Path(folder)/'config.json').read_text())['cwaApiKey'],json.loads(Path('config.json').read_text())['cwaApiKey'])
            self.assertTrue((Path(folder)/'weather.json').exists())

if __name__ == '__main__': unittest.main()
