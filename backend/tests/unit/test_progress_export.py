from app.api.endpoints.progress import _safe_csv


def test_csv_export_neutralizes_formula_leading_text_without_changing_ids():
    assert _safe_csv("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert _safe_csv(" +command") == "' +command"
    assert _safe_csv("024-XX") == "024-XX"
    assert _safe_csv(None) == ""
