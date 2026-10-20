"""Skrip Simulasi Data Uji Lalu Lintas Sitinjau Lauik (Macet / Padat / Lancar / Reset)."""

import argparse
import json
import urllib.request
import urllib.error
import sys

BASE_URL = "http://localhost:8000"

def simulate(status: str, fill_diurnal: bool = True, server_url: str = BASE_URL):
    url = f"{server_url}/api/dev/simulate-traffic"
    payload = json.dumps({"status": status, "fill_diurnal": fill_diurnal}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("=" * 60)
            print(" SIMULASI DATA LALU LINTAS BERHASIL DISUNTIKKAN")
            print("=" * 60)
            print(f"Status Target    : {data['simulated_counts']['target'].upper()}")
            print(f"Profil Diurnal   : {'Aktif (Pola Alami 24 Jam)' if fill_diurnal else 'Non-aktif'}")
            print(f"Kendaraan Masuk  : {data['simulated_counts']['truck']} Truk, {data['simulated_counts']['bus']} Bus, {data['simulated_counts']['mobil']} Mobil, {data['simulated_counts']['motor']} Motor")
            snap = data['snapshot']
            print(f"Arus (Q)         : {snap['volume_q_smp_jam']} smp/jam")
            print(f"Kapasitas (C)    : {snap['capacity_c_smp_jam']} smp/jam")
            print(f"Derajat Kejenuhan: {snap['degree_of_saturation']} (Kepadatan: {round(snap['degree_of_saturation']*100, 1)}%)")
            print(f"Tingkat Layanan  : LoS {snap['los']}")
            print(f"Status Sistem    : {snap['status'].upper()}")
            print(f"Pesan HUD        : \"{snap['human_message']}\"")
            print("=" * 60)
            print("Buka browser di http://localhost:8000/ untuk melihat tampilan Macet secara langsung!")
    except urllib.error.URLError as exc:
        print(f"Error menghubungkan ke server {server_url}: {exc}")
        print("Pastikan server Sitinjau Laut sedang berjalan di port 8000.")
        sys.exit(1)

def reset_data(server_url: str = BASE_URL):
    url = f"{server_url}/api/monitoring/reset"
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("=" * 60)
            print(" DATA MONITORING BERHASIL DIRESET")
            print("=" * 60)
            print(f"Data Dihapus     : {data.get('deleted', {})}")
            snap = data.get('snapshot', {})
            print(f"Status Kembali   : {snap.get('status', 'lancar').upper()} (LoS {snap.get('los', 'A')})")
            print("Dashboard kembali bersih seperti semula.")
    except urllib.error.URLError as exc:
        print(f"Error menghubungkan ke server {server_url}: {exc}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Simulasi Data Uji Lalu Lintas Sitinjau Lauik")
    parser.add_argument("--status", choices=["macet", "padat", "lancar"], default="macet", help="Target status lalu lintas (default: macet)")
    parser.add_argument("--no-diurnal", action="store_true", help="Jangan isi kurva harian jam-jam sebelumnya")
    parser.add_argument("--reset", action="store_true", help="Hapus seluruh data dummy / reset database dan memori")
    parser.add_argument("--url", default=BASE_URL, help="URL server (default: http://localhost:8000)")
    args = parser.parse_args()

    if args.reset:
        reset_data(args.url)
    else:
        simulate(args.status, not args.no_diurnal, args.url)

if __name__ == "__main__":
    main()
