# Uploaded-paper OCR validation

| Paper | Year | Pages | Groups | Topic anchors | OCR marks / cover | Structural / topic checks |
| --- | --- | --- | --- | --- | --- | --- |
| Physics_paper_1A_TZ3_HL.pdf | 2025 | 22 | 40 | 10 | 40 / 40 | PASS |
| Physics_paper_1A_TZ1_HL.pdf | 2025 | 24 | 40 | 11 | 40 / 40 | PASS |
| Physics HL Paper 1A TZC.pdf | 2026 | 22 | 40 | 12 | 40 / 40 | PASS |
| Physics_paper_2_TZ3_HL.pdf | 2025 | 29 | 10 | 7 | 90 / 90 | PASS |
| Physics HL Paper 2 TZC (1).pdf | 2026 | 23 | 9 | 9 | 61 / 90 | PASS |
| Physics HL Paper 1B TZC.pdf | 2026 | 11 | 2 | 2 | 18 / 20 | PASS |

- Topic anchors check specified required and forbidden labels, not every possible extra label.
- The anchors were used to diagnose and improve heuristics; this is not a held-out accuracy benchmark.
- OCR/PDF topic agreement is not proof of semantic accuracy. All other tags and crop boundaries still need review.
- Cover mark mismatches flag incomplete OCR marks; difficulty is unrated and time remains heuristic.

## Findings

### Physics_paper_1A_TZ3_HL.pdf

OCR/PDF topic disagreements: [8, 25].


### Physics_paper_1A_TZ1_HL.pdf

OCR/PDF topic disagreements: [3, 23].


### Physics HL Paper 1A TZC.pdf

OCR/PDF topic disagreements: none (OCR-only papers have no independent PDF text).

- Page 2: OCR read question 4; proposed 1 from adjacent numbering. Confirm the image.
- Page 10: OCR read question 46; proposed 16 from adjacent numbering. Confirm the image.

### Physics_paper_2_TZ3_HL.pdf

OCR/PDF topic disagreements: none (OCR-only papers have no independent PDF text).


### Physics HL Paper 2 TZC (1).pdf

OCR/PDF topic disagreements: none (OCR-only papers have no independent PDF text).

- Detected 61 marks, but the cover states 90. Review question marks and timing; OCR may omit mark brackets.

### Physics HL Paper 1B TZC.pdf

OCR/PDF topic disagreements: none (OCR-only papers have no independent PDF text).

- Detected 18 marks, but the cover states 20. Review question marks and timing; OCR may omit mark brackets.
