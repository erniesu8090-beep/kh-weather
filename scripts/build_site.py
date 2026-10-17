"""Build a credential-free static dashboard with a timestamped CWA snapshot."""
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import CWADataFetcher, now_iso

ROOT = Path(__file__).resolve().parents[1]

def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rainfall = CWADataFetcher.fetch_rainfall()
    radar = CWADataFetcher.fetch_radar()
    if not rainfall.get('stations'):
        raise RuntimeError('No rainfall observations received; keeping the last successful deployment')
    if not radar.get('areas', {}).get('Area2', {}).get('scans_hd'):
        raise RuntimeError('No Linyuan radar frames received; keeping the last successful deployment')
    for name in ['index.html', 'config.json', 'styles.css', 'stations.js', 'weather.js', 'app.js', 'sw.js', 'manifest.json', 'favicon.ico', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png', 'qrcode.png']:
        shutil.copy2(ROOT / name, destination / name)
    payload = {'rainfall': rainfall, 'radar': radar, 'generated_at': now_iso()}
    (destination / 'weather.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    (destination / '.nojekyll').touch()
    print(f"Built {destination}: {len(rainfall['stations'])} stations, generated {payload['generated_at']}")

if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'dist')
