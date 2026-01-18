# Numark MT Pro 3 for DaVinci Resolve

Detta projekt gör det möjligt att använda Numark Mixtrack Pro 3 MIDI-kontroller tillsammans med DaVinci Resolve för att styra olika funktioner via anpassade kortkommandon.

## Funktioner
- Fångar MIDI-signaler från Mixtrack Pro 3
- Mappning av MIDI till DaVinci Resolve-kortkommandon
- Enkel konfiguration via CSV-filer
- GUI för att hantera och testa mappningar

## Filer
- `capture_gui.py` – Grafiskt gränssnitt för att hantera mappningar och testa MIDI
- `capture_midi.py` – Fångar och tolkar MIDI-signaler
- `midi_to_key.py` – Översätter MIDI till tangentbordstryckningar
- `mappings.csv` – Mappning mellan MIDI och kortkommandon
- `shortcuts.csv` – Lista över DaVinci Resolve-kortkommandon
- `requirements.txt` – Nödvändiga Python-paket

## Kom igång
1. Klona detta repo:
   ```
   git clone https://github.com/zapbrox/Numark-MT-Pro-3-for-Davici-resolve.git
   ```
2. Installera beroenden:
   ```
   pip install -r requirements.txt
   ```
3. Starta GUI:t:
   ```
   python capture_gui.py
   ```

## Förutsättningar
- Python 3.8+
- Numark Mixtrack Pro 3
- DaVinci Resolve (testat med version 18+)

## Licens
MIT

## Kontakt
Skapare: zapbrox
GitHub: https://github.com/zapbrox
