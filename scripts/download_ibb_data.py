"""Download the three IBB Open Data sources used by AfetRota.

Run::

    python scripts/download_ibb_data.py

This fetches:
  1. Kentsel Açık ve Yeşil Alan Koordinatları   (~52 MB GeoJSON, 1,371 polygons)
  2. Muhtarlık Adres Bilgileri                  (~400 KB GeoJSON, 963 points)
  3. Deprem Senaryosu Analiz Sonuçları          (~56 KB CSV, 959 mahalle)

After downloading, run ``scripts/build_real_data.py`` to derive the slim
shelter and risk-zone GeoJSON files that the agent uses at runtime.
"""

from __future__ import annotations

import ssl
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

DOWNLOADS = [
    (
        "raw_ibb_green_areas.geojson",
        "https://data.ibb.gov.tr/dataset/82e809cf-9465-407a-91cd-ac745d6fbc95/"
        "resource/41ddb7a6-6931-4176-9614-2c2892da5307/download/yaysis_mahal_geo_data.geojson",
        "Kentsel Açık ve Yeşil Alan Koordinatları",
    ),
    (
        "raw_ibb_muhtarlik.geojson",
        "https://data.ibb.gov.tr/dataset/c310cde9-92b1-4c51-9575-d71b1dc7ac43/"
        "resource/71f75529-7fae-4a85-b05f-664c62eda422/download/muhtarlik_lokasyon.geojson",
        "Muhtarlık Adres Bilgileri",
    ),
    (
        "raw_ibb_deprem_senaryosu.csv",
        "https://data.ibb.gov.tr/dataset/c13514d9-86b1-4b83-a9b9-1a15cb5f254c/"
        "resource/9c3ac492-de4b-4245-b418-7ad3df67a193/download/deprem-senaryosu-analiz-sonuclar.csv",
        "Deprem Senaryosu Analiz Sonuçları",
    ),
]


def main() -> None:
    DATA.mkdir(exist_ok=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for fname, url, label in DOWNLOADS:
        out = DATA / fname
        if out.exists():
            print(f"[skip]   {fname}  ({label})  — already present")
            continue
        print(f"[fetch]  {fname}  ({label}) …")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=180) as r:
            data = r.read()
        out.write_bytes(data)
        print(f"[ok]     {fname}  ({len(data):,} bytes)")
    print("\nNext: python scripts/build_real_data.py")


if __name__ == "__main__":
    main()
