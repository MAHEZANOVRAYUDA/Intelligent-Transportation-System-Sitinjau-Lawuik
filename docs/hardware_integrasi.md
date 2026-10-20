# Integrasi hardware lapangan — Sitinjau Laut

**Status:** rencana pengadaan Fase 3–4 (software FastAPI sudah ada; firmware ESP32 belum).  
**Cakupan:** dua gerbang identik (A Padang, B Solok), jarak 16,5 km.  
**Harga:** perkiraan pasar Indonesia 2026, belum PPN/instalasi tiang.

Raspberry Pi **tidak** dibagi dua gerbang. Occupancy koridor butuh jaringan (4G/VPN) antar situs.

---

## 1. Arsitektur per gerbang

```
Kamera IP PoE (RTSP)
        │
        ▼
Raspberry Pi 5 8GB + Hailo-8L + SSD USB3
        │  FastAPI :8000, YOLO, tracker, occupancy
        │  UART 3,3 V 115200 JSON
        ▼
ESP32-WROOM-32
        ├── I2C → LCD monokrom 20×4  (kepadatan: U%, lancar/padat/macet)
        └── GPIO → MOSFET → fan 12 V (ON dari telemetry perangkat, bukan dari kepadatan jalan)
```

LCD **hanya menampilkan** hasil occupancy yang sudah dihitung Pi. ESP32 **tidak** menjalankan YOLO.

Fan **menyala** ketika Pi mengirim update keadaan perangkat (`cpu_c`, `throttled`, `fan:1`), dengan histeresis 65 °C / 55 °C. Jika UART putus &gt;15 detik, fan ON (fail-safe panas).

---

## 2. Bill of materials

Jumlah default = 2 gerbang. Cadangan ditandai terpisah.

### 2.1 Komputasi

| Item | Spesifikasi | Qty | Est. satuan (IDR) |
|---|---|---:|---:|
| Raspberry Pi 5 | 8 GB, Active Cooler resmi | 2 | 1,7 jt |
| PSU 5 V / 5 A | USB-C PD 27 W atau buck dari 12 V | 2 | 0,25 jt |
| microSD A2 64 GB | boot OS saja | 2 | 0,15 jt |
| SSD NVMe 256 GB + enclosure USB 3 | data, model, SQLite | 2 | 0,65 jt |
| Hailo-8L AI Kit | HAT PCIe Pi 5 | 2 | 2,2 jt |
| Coral USB Accelerator | **opsional**, risiko driver Pi 5 | 0–2 | 1,5 jt |
| RTC DS3231 | jam saat 4G putus | 2 | 0,04 jt |
| Watchdog hardware/USB | restart jika hang | 2 | 0,12 jt |

### 2.2 Kamera

| Item | Spesifikasi | Qty | Est. satuan |
|---|---|---:|---|
| Kamera IP outdoor | 4 MP, RTSP, PoE, IR, IP66 | 2 | 2,5 jt |
| Injector/switch PoE | industri, surge | 2 | 0,45 jt |
| SFTP Cat6 | ±30 m/gerbang | 60 m | 12 rb/m |
| Tiang/arm + grounding + SPD | galvanis | 2 set | 1,2 jt + 0,35 jt |

### 2.3 ESP32, LCD, fan

| Item | Spesifikasi | Qty |
|---|---|---:|
| ESP32-WROOM-32 DevKit | UART + I2C 3,3 V | 3 (2+1) |
| LCD 20×4 HD44780 + I2C | monokrom backlight | 3 (2+1) |
| OLED 128×64 (opsional) | dalam kabinet | 2 |
| MOSFET N logic-level | IRLZ44N / IRLML2502 | 4 |
| Dioda flyback 1N5819 | paralel fan | 4 |
| Fan 12 V 80 mm | 2 per kabinet | 4 |
| DHT22/SHT30 | suhu kabinet | 2 |

**Jangan** menyambung fan ke pin ESP32 atau GPIO Pi. MOSFET + fuse 1 A + PSU 12 V.

### 2.4 Daya dan kabinet

| Item | Qty |
|---|---:|
| PSU 12 V 10 A industri | 2 |
| UPS 1000 VA AVR | 2 |
| MCB + SPD AC | 2 set |
| Kabinet outdoor IP65 + din-rail | 2 |

Beban tipikal per gerbang ≈ **40–55 W** (IR malam lebih tinggi). UPS ≈ 15–25 menit, bukan genset.

### 2.5 Jaringan

| Item | Qty |
|---|---:|
| Router 4G industri + VPN | 2 |
| Antena 4G outdoor + surge | 2 |
| SIM data 20–50 GB/bulan | 2 |
| Switch Gigabit industri | 2 |

### 2.6 Cadangan disarankan

1× Pi 5, 1× ESP32, 1× LCD, 1× SSD, 1× PSU 12 V.

Perkiraan hardware dua gerbang (tanpa jasa tiang): **sekitar 42–58 juta IDR**.

---

## 3. Protokol UART (rancangan)

115200 8N1, TX/RX silang, GND bersama, **3,3 V saja**.

```json
{"gate":"A","u":42.1,"status":"padat","on":{"motor":12,"mobil":4,"bus":0,"truck":1},"cpu_c":71.2,"throttled":false,"fan":1}
```

Contoh LCD 20×4:

```
SITINJAU A  14:22
U=42%  PADAT
M12 C4 B0 T1
FAN ON  CPU 71C
```

Firmware ESP32 dan jembatan UART di worker **belum ada di repositori** — langkah coding berikutnya setelah barang tiba.

---

## 4. Analisis kompatibilitas (ringkas)

| Pasangan | Hasil |
|---|---|
| YOLOv8n di CPU Pi 5, imgsz 960 | Tidak cukup untuk produksi |
| YOLOv8n + Hailo-8L | Cocok; export HEF Ultralytics; uji fps di lapangan |
| Coral USB + Pi 5 Bookworm | Berisiko; jangan SKU utama |
| Hailo HAT + NVMe HAT | Konflik satu PCIe → SSD lewat USB 3 |
| Kamera USB 5 V jarak 20 m | Tidak cocok; wajib IP/PoE |
| UART Pi 5 ↔ ESP32 3,3 V | Cocok |
| GPIO langsung ke fan 12 V | Tidak aman |
| LCD I2C 5 V ↔ ESP32 | Perlu modul 3,3 V atau shifter |
| OLED di bawah matahari | Lemah; utamakan 20×4 backlight |
| SQLite di microSD 24 jam | Jangan; pakai SSD |
| Dua `run.py` tanpa API pusat | Occupancy dual-gate tidak akurat |

Software FastAPI **memadai** sebagai otak gerbang. Yang masih gap: firmware ESP32, sinkronisasi dua situs 16,5 km, fine-tune dataset, kalibrasi garis di kamera produksi.

Dokumen proyek: `docs/PROJECT.md`. Rumus occupancy: `docs/algorithm.md`.
