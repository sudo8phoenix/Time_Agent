from datetime import date, time
from io import BytesIO
from openpyxl import Workbook
import pytest
from app.ingest.report_mapping import MappingSpec, mapped_rows, preview


def xlsx(headers, rows, *, title='Civil diary', header_row=1):
    wb = Workbook(); ws = wb.active; ws.title = title
    for _ in range(header_row - 1): ws.append(['Synthetic development report'])
    ws.append(headers)
    for row in rows: ws.append(row)
    output = BytesIO(); wb.save(output); return output.getvalue()


def test_native_excel_date_time_and_quantity_free_lifecycle():
    raw = xlsx(['Day', 'Work', 'Clock'], [[date(2026, 10, 9), 'Started excavation F-01', time(8, 30)]], header_row=3)
    assert preview(raw)[0]['rows'][2][1]['value'] == 'Work'
    spec = MappingSpec(sheet='Civil diary', header_row=3, columns={'report_date': 1, 'work_description': 2, 'actual_start': 3}, context={'discipline': 'civil'})
    parts, errors, metadata = mapped_rows(raw, spec)
    assert not errors and len(parts) == 1
    assert 'report_date: 2026-10-09' in parts[0][1] and '08:30:00' in parts[0][1]
    assert parts[0][0] == 'sheet:Civil diary/row:4'
    assert metadata['rows'][0]['cells'][1]['cell'] == 'B4'
    assert metadata['rows'][0]['cells'][1]['header'] == 'Work'
    assert 'quantity' not in spec.columns


def test_ambiguous_date_and_formula_are_visible_errors():
    raw = xlsx(['Day', 'Work'], [['09/10/2026', 'Finished excavation'], [date(2026, 10, 9), '=1+1']])
    spec = MappingSpec(sheet='Civil diary', header_row=1, columns={'report_date': 1, 'work_description': 2})
    parts, errors, metadata = mapped_rows(raw, spec)
    assert not parts and len(errors) == len(metadata['rows']) == 2
    spec.date_format = '%d/%m/%Y'
    parts, errors, _ = mapped_rows(raw, spec)
    assert len(parts) == 1 and len(errors) == 1
    assert '2026-10-09' in parts[0][1]


def test_signature_changes_with_headers_and_duplicate_mapping_rejected():
    spec = MappingSpec(sheet='Civil diary', header_row=1, columns={'work_description': 1})
    _, _, first = mapped_rows(xlsx(['Work'], [['Started']]), spec)
    _, _, second = mapped_rows(xlsx(['Task'], [['Started']]), spec)
    assert first['header_signature'] != second['header_signature']
    with pytest.raises(ValueError):
        MappingSpec(sheet='Civil diary', header_row=1, columns={'work_description': 1, 'area': 1})


def test_date_only_excel_endpoint_keeps_unknown_clock_and_invalid_time_is_error():
    raw = xlsx(['Work', 'Finish'], [['Finished excavation', date(2026, 10, 9)]])
    spec = MappingSpec(sheet='Civil diary', header_row=1, columns={'work_description': 1, 'actual_finish': 2})
    parts, errors, metadata = mapped_rows(raw, spec)
    assert not errors and 'actual_finish: 2026-10-09' in parts[0][1]
    assert '00:00' not in parts[0][1]
    assert metadata['rows'][0]['cells'][1]['number_format']
    _, errors, _ = mapped_rows(xlsx(['Work', 'Finish'], [['Finished', '99:99']]), spec)
    assert errors
