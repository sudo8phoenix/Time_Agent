"""F01/F02: real intake/pipeline/acceptance, isolated PostgreSQL, fixture model."""
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import NameObject, DecodedStreamObject, DictionaryObject
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.report_intake import SaveMapping, Transcription, save_mapping, transcribe
from app.api.endpoints.review import approve, ApprovalRequest, get_proposal
from app.db.models import (Activity, ActivityState, Fragment, Job, Observation, Project, Proposal,
                           ProjectMembership, ScheduleVersion, User)
from app.db.session import engine
from app.ingest import reports
from app.ingest.report_mapping import MappingSpec, mapped_rows
from app.jobs.pipeline import process_job
from app.jobs.service import enqueue_job
from app.schemas.observation import Observation as Extracted
from backend.tests.unit.test_report_mapping import xlsx

FIXTURES = Path(__file__).parents[3] / 'data/synthetic/v2/intake'


def diary_pdf(*, scan=False):
    writer = PdfWriter(); page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    text = 'SYNTHETIC DAILY DIARY - Started excavation at F-01 on 2026-10-09 at 08:30.'
    if scan:
        # A raster page has no extractable text, equivalent to an unreadable scan.
        image = DecodedStreamObject(); image.set_data(__import__('zlib').decompress((FIXTURES / 'scan-diary-rgb.zlib').read_bytes()))
        image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): __import__('pypdf').generic.NumberObject(1000), NameObject('/Height'): __import__('pypdf').generic.NumberObject(260),
                      NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): __import__('pypdf').generic.NumberObject(8)})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im1'): writer._add_object(image)})})
        stream.set_data(b'q 500 0 0 130 50 550 cm /Im1 Do Q')
    else:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream.set_data(f'BT /F1 10 Tf 30 700 Td ({text}) Tj ET'.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output); return output.getvalue()


@pytest.fixture
def intake(tmp_path, monkeypatch):
    connection = engine.connect(); transaction = connection.begin()
    db = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint')()
    monkeypatch.setattr(reports, 'get_settings', lambda: type('Settings', (), {'upload_dir': str(tmp_path)})())
    user = User(username=f'intake-{uuid4().hex}', password_hash='unused', role='reviewer')
    project = Project(name=f'F01/F02 synthetic {uuid4().hex}', timezone='UTC')
    version = ScheduleVersion(project=project, version_number=1, content_sha256=uuid4().hex, state='active')
    db.add_all([user, project, version]); db.flush(); project.active_schedule_version_id = version.id
    db.add(ProjectMembership(project_id=project.id, user_id=user.id))
    activity = Activity(schedule_version=version, external_id='EX-F-01', name='Excavation F-01', wbs='1',
                        discipline='civil', work_type='excavation', area='F-01', asset_tags='F-01',
                        is_leaf=True, measurement_basis='unsupported')
    db.add(activity); db.flush(); db.add(ActivityState(activity_id=activity.id, revision=0, completed_quantity=0)); db.flush()
    try: yield db, project, user, activity
    finally: db.close(); transaction.rollback(); connection.close()


def accepted_start(db, project, user, activity, report):
    job, _ = enqueue_job(db, project, report)
    fragment = db.scalar(select(Fragment).where(Fragment.report_id == report.id))
    quote = fragment.original_text
    discipline, work_type = activity.discipline, activity.work_type
    def extract(_):
        return [Extracted.model_validate({'discipline': discipline, 'work_type': work_type,
            'event_type': 'actual_start', 'observed_status': 'in_progress', 'area': 'F-01',
            'asset_tags': ['F-01'], 'explicit_activity_id': None, 'work_date': '2026-10-09',
            'date_basis': 'explicit', 'quantity': None, 'quantity_kind': 'none', 'unit': None,
            'raw_unit': None, 'reported_percent': None, 'actual_start': None, 'actual_finish': None,
            'blocker': None, 'summary': quote[:2000], 'warnings': [],
            'evidence': [{'fields': ['event_type'], 'fragment_id': str(fragment.id), 'quote': quote}],
            'lifecycle_effects': [{'kind': 'actual_start', 'scope': 'whole_activity',
                'endpoint': {'local_date': '2026-10-09', 'local_time': '08:30:00', 'precision': 'minute',
                             'basis': 'explicit', 'raw_expression': '2026-10-09 08:30'},
                'evidence': [{'fields': ['endpoint'], 'fragment_id': str(fragment.id), 'quote': quote}]}]})]
    def select_activity(*_):
        return {'candidate_id': str(activity.id), 'mapping_state': 'suggested', 'match_strength': 'review',
                'explanation': 'Fixture evidence', 'candidates': [], 'missing_information': []}
    result = process_job(db, job, extraction_call=extract, selection_call=select_activity,
                         retrieve_call=lambda *_: [activity])
    assert result['proposal_count'] == 1
    proposal = db.scalar(select(Proposal).join(Observation).where(Observation.job_id == job.id))
    assert db.get(ActivityState, activity.id).actual_start is None
    approve(proposal.id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
            idempotency_key=f'intake-{report.id}'), user, db)
    state = db.get(ActivityState, activity.id)
    assert state.actual_start == date(2026, 10, 9) and state.actual_start_time.hour == 8
    payload = get_proposal(proposal.id, user, db)
    assert payload['evidence'][0]['locator'] == fragment.locator
    return payload


@pytest.mark.parametrize('discipline', ['civil', 'electrical'])
def test_two_report_workbooks_and_mapping_reuse(intake, discipline):
    db, project, user, activity = intake
    if discipline == 'civil':
        raw = xlsx(['Date of work', 'Operation', 'Clock'], [[date(2026, 10, 9), 'Started excavation F-01', '08:30']], header_row=3)
        spec = MappingSpec(sheet='Civil diary', header_row=3, columns={'report_date': 1, 'work_description': 2, 'actual_start': 3}, context={'discipline': discipline})
    else:
        activity.discipline = 'electrical'; activity.work_type = 'cable_laying'; activity.name = 'Cable laying F-01'
        raw = xlsx(['Field narrative', 'Shift day', 'Started at'], [['Started cable laying F-01', date(2026, 10, 9), '08:30']], title='Electrical log')
        spec = MappingSpec(sheet='Electrical log', header_row=1, columns={'work_description': 1, 'report_date': 2, 'actual_start': 3}, context={'discipline': discipline})
    _, errors, metadata = mapped_rows(raw, spec); assert not errors
    saved = save_mapping(SaveMapping(template=discipline, header_signature=metadata['header_signature'], spec=spec), project, db, user)
    report, _ = reports.ingest_report(db, project, raw, filename=f'{discipline}.xlsx', mapping=spec,
        uploader_id=user.id, ingestion_metadata={'mapping_id': saved['id'], 'mapping_revision': saved['revision']})
    payload = accepted_start(db, project, user, activity, report)
    assert payload['provenance']['intake']['mapping_id'] == saved['id']
    assert payload['provenance']['intake']['rows'][0]['cells'][0]['cell']
    second = xlsx(['Date of work', 'Operation', 'Clock'], [[date(2026, 10, 10), 'Started excavation F-01', '09:30']], header_row=3) if discipline == 'civil' else xlsx(['Field narrative', 'Shift day', 'Started at'], [['Started cable laying F-01', date(2026, 10, 10), '09:30']], title='Electrical log')
    assert mapped_rows(second, spec)[2]['header_signature'] == metadata['header_signature']
    reused, duplicate = reports.ingest_report(db, project, second, filename=f'{discipline}-next.xlsx', mapping=spec,
        ingestion_metadata={'mapping_id': saved['id'], 'mapping_revision': saved['revision']})
    assert not duplicate and reused.id != report.id
    assert reused.ingestion_metadata['mapping_revision'] == 1


@pytest.mark.parametrize('scan', [False, True])
def test_pdf_and_scan_transcription_through_acceptance(intake, scan):
    db, project, user, activity = intake
    raw = diary_pdf(scan=scan)
    report, _ = reports.ingest_report(db, project, raw, filename='scan.pdf' if scan else 'diary.pdf', uploader_id=user.id)
    if scan:
        job, _ = enqueue_job(db, project, report)
        assert process_job(db, job)['state'] == 'needs_transcription'
        body = Transcription(pages={1: 'Started excavation at F-01 on 2026-10-09 at 08:30.'})
        result = transcribe(report.id, body, project, db, user)
        retry = transcribe(report.id, body, project, db, user)
        assert retry['existing'] and retry['job_id'] == result['job_id']
        from app.db.models import Report
        report = db.get(Report, result['report_id'])
        assert report.ingestion_metadata['transcriber_id'] == str(user.id)
        assert report.ingestion_metadata['transcribed_at']
    payload = accepted_start(db, project, user, activity, report)
    assert payload['evidence'][0]['locator'] == 'page:1'
    if scan:
        assert payload['provenance']['intake']['quality'] == 'human_transcribed'
        assert payload['provenance']['source']['original_url'].endswith('/original')


def test_invalid_page_and_row_never_silently_accepted(intake):
    db, project, user, _ = intake
    report, _ = reports.ingest_report(db, project, diary_pdf(scan=True), filename='scan.pdf')
    with pytest.raises(HTTPException):
        transcribe(report.id, Transcription(pages={2: 'Wrong page'}), project, db, user)
    raw = xlsx(['Work', 'Date'], [['Started', '10/09/2026']])
    spec = MappingSpec(sheet='Civil diary', header_row=1, columns={'work_description': 1, 'report_date': 2})
    with pytest.raises(ValueError, match='XLSX_ROW_ERRORS'):
        reports.ingest_report(db, project, raw, filename='bad.xlsx', mapping=spec)


def test_http_preview_mapping_reuse_and_project_csrf_safety(intake):
    from datetime import datetime, timedelta, timezone
    import hashlib
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_session
    from app.db.models import Session as LoginSession
    db, project, user, _ = intake
    db.add(LoginSession(token_hash=hashlib.sha256(b'fixture-session').hexdigest(), user_id=user.id,
                        csrf_hash=hashlib.sha256(b'fixture-csrf').hexdigest(),
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1))); db.flush()
    app.dependency_overrides[get_session] = lambda: db
    raw = xlsx(['Work', 'Day'], [['Started excavation F-01', date(2026, 10, 9)]])
    spec = {'sheet': 'Civil diary', 'header_row': 1, 'columns': {'work_description': 1, 'report_date': 2}}
    base = f'/api/v1/projects/{project.id}/reports'
    try:
        with TestClient(app) as client:
            client.cookies.set('progress_session', 'fixture-session')
            assert client.post(base + '/preview', files={'file': ('civil.xlsx', raw)}).status_code == 403
            headers = {'X-CSRF-Token': 'fixture-csrf'}
            response = client.post(base + '/preview', files={'file': ('civil.xlsx', raw)},
                                   data={'mapping': __import__('json').dumps(spec)}, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()['valid_rows'] == 1
            saved = client.post(base + '/mappings', json={'template': 'Civil', 'spec': spec,
                'header_signature': response.json()['header_signature']}, headers=headers)
            assert saved.status_code == 201, saved.text
            mapping_id = saved.json()['id']
            uploaded = client.post(base, files={'file': ('civil.xlsx', raw)}, data={'mapping_id': mapping_id}, headers=headers)
            assert uploaded.status_code == 202, uploaded.text
            report_id = uploaded.json()['report_id']
            retrieved = client.get(base + '/' + report_id)
            assert retrieved.json()['ingestion_metadata']['mapping_id'] == mapping_id
            assert client.get(f'/api/v1/projects/{uuid4()}/reports/{report_id}').status_code == 403
            changed = xlsx(['Changed work header', 'Day'], [['Started excavation', date(2026, 10, 9)]])
            assert client.post(base, files={'file': ('next.xlsx', changed)}, data={'mapping_id': mapping_id}, headers=headers).status_code == 422
            next_raw = xlsx(['Work', 'Day'], [['Started excavation F-01', date(2026, 10, 10)]])
            next_file = client.post(base, files={'file': ('next.xlsx', next_raw)}, data={'mapping_id': mapping_id}, headers=headers)
            assert next_file.status_code == 202 and next_file.json()['report_id'] != report_id
            scan = client.post(base, files={'file': ('scan.pdf', diary_pdf(scan=True), 'application/pdf')}, headers=headers)
            assert scan.status_code == 202 and scan.json()['state'] == 'needs_transcription'
            scan_id = scan.json()['report_id']
            assert client.post(base + f'/{scan_id}/transcriptions', json={'pages': {'1': 'Started excavation F-01 on 2026-10-09 at 08:30.'}}, headers=headers).status_code == 202
    finally:
        app.dependency_overrides.clear()
