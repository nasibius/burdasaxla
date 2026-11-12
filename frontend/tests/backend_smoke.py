"""Local-only UI write test using a throwaway SQLite DB and SYNTHETIC activity.

Start API with a fresh BURDASAXLA_DB and test-only admin token, then Vite dev server.
SMOKE_ADMIN_TOKEN=<same-test-token> python frontend/tests/backend_smoke.py
Never run against a production backend. All writes are to localhost only.
"""
import json
import os

from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1050})
    page.add_init_script("localStorage.setItem('bs-lang', 'en')")
    page.goto('http://127.0.0.1:5173/#authority', wait_until='networkidle')
    page.locator('.authority-card').first.click()
    page.get_by_label('Admin token', exact=True).fill(os.environ['SMOKE_ADMIN_TOKEN'])
    page.get_by_label('Action', exact=True).select_option('shortlist')
    page.get_by_label('Reason (private audit note)', exact=True).fill('SYNTHETIC UI TEST: investigate only')
    page.get_by_role('button', name='Save review', exact=True).click()
    expect(page.get_by_text('Review saved.', exact=True)).to_be_visible()
    page.reload(wait_until='networkidle')
    expect(page.locator('.authority-card').first).to_contain_text('Shortlisted')
    page.get_by_role('button', name='Passenger activity', exact=True).click()
    page.get_by_text('Import aggregate observations (JSON)', exact=True).click()
    page.get_by_label('Admin token', exact=True).fill(os.environ['SMOKE_ADMIN_TOKEN'])
    record = {'location_id': 'SYNTHETIC-UI-TEST', 'name': 'SIMULATED EXAMPLE — UI TEST ONLY',
              'longitude': 49.85, 'latitude': 40.38, 'period_start': '2020-01-01T00:00:00Z',
              'period_end': '2020-01-02T00:00:00Z', 'pickups': 120, 'dropoffs': 240,
              'source_ref': 'SYNTHETIC test', 'source_url': 'https://example.org/synthetic',
              'license': 'SYNTHETIC test only', 'collection_method': 'SYNTHETIC fixture', 'publication_permitted': True}
    page.get_by_label('JSON file', exact=True).set_input_files({
        'name': 'synthetic-test.json', 'mimeType': 'application/json',
        'buffer': json.dumps({'records': [record]}).encode()})
    expect(page.get_by_text('Aggregate records imported.', exact=True)).to_be_visible()
    expect(page.get_by_role('cell', name='SIMULATED EXAMPLE — UI TEST ONLY', exact=True)).to_be_visible()
    expect(page.get_by_role('cell', name='15', exact=True)).to_be_visible()
    page.reload(wait_until='networkidle')
    page.get_by_role('button', name='Passenger activity', exact=True).click()
    expect(page.get_by_role('cell', name='SIMULATED EXAMPLE — UI TEST ONLY', exact=True)).to_be_visible()
    browser.close()
print('PASS: authenticated UI review survives reload; aggregate JSON import renders counts/rate and survives reload (throwaway DB)')
