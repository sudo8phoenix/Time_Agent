# Synthetic development intake fixtures

Developer-authored on 10 October 2026. Not owner data, real site records, benchmark labels or independently reviewed gold. F-01/F-02 are fictional fixture locations. Keep all alternate formats/corrections for these scenarios in development.

- `civil-diary.xlsx`: header row 3, Work day → report_date, Operation → work_description, Start clock → actual_start; optional file discipline civil.
- `civil-diary-next.xlsx`: same sheet/header signature, next day's fixture; reuse confirmed mapping.
- `electrical-diary.xlsx`: Electrical log, header row 1, Field narrative → work_description, Shift day → report_date, Started at → actual_start; optional file discipline electrical.
- `text-diary.txt`: quantity-free daily diary.
- `scan-diary.png`: raster diary source; `scan-diary-rgb.zlib` is its compressed RGB data (1000×260). Tests embed this immutable raster in an image-only PDF. Suggested transcription: “Started excavation at F-01 on 2026-10-09 at 08:30.”

`backend/tests/integration/test_flexible_intake.py` creates text/image PDFs in memory and verifies proposals through authorized acceptance on isolated PostgreSQL, using explicit fixture extraction/matching outputs. No live-model accuracy is claimed.
