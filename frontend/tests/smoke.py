"""UI acceptance smoke test against a built static site (no mocked supply/demand).

Usage: python frontend/tests/smoke.py http://127.0.0.1:4173/burdasaxla/ [artifact_dir]
Requires playwright and its Chromium browser. Basemap tiles are external and not assertions.
"""
import csv
import io
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:4173/burdasaxla/'
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('work/ui-evidence')
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1050}, device_scale_factor=1)
    page.add_init_script("localStorage.setItem('bs-lang', 'en')")
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base, wait_until='networkidle')
    page.get_by_role('textbox', name='Destination', exact=True).fill('28 May')
    page.locator('.suggest button').first.click()
    expect(page.get_by_text('No confirmed spot nearby', exact=True)).to_be_visible()
    assert page.locator('.card:not(.unverified)').count() == 0
    page.screenshot(path=str(out / 'driver.png'), full_page=True)
    page.get_by_role('button', name='AYNA Planning', exact=True).click()
    expect(page.locator('.authority-warning')).to_contain_text('Verified supply inventory incomplete — coverage cannot be established')
    expect(page.get_by_text('Read-only demonstration', exact=True)).to_be_visible()
    assert page.locator('.authority-map .leaflet-control-layers-overlays label').count() == 4
    count = page.locator('.authority-card').count()
    assert count > 0
    page.locator('.authority-card').first.click()
    expect(page.get_by_role('article', name='Candidate detail')).to_be_visible()
    assert page.get_by_role('button', name='Save review', exact=True).count() == 0
    page.screenshot(path=str(out / 'planning.png'), full_page=True)
    page.evaluate("document.body.dataset.authorityPrint = 'candidate'")
    page.pdf(path=str(out / 'sample-candidate-report.pdf'), print_background=True, prefer_css_page_size=True)
    with page.expect_download() as event:
        page.get_by_role('button', name=f'CSV ({count})', exact=True).click()
    records = list(csv.DictReader(io.StringIO(Path(event.value.path()).read_text())))
    assert len(records) == count
    assert all(r['limitations'] and r['source_snapshot'] for r in records)
    with page.expect_download() as event:
        page.get_by_role('button', name='GeoJSON', exact=True).click()
    assert len(json.loads(Path(event.value.path()).read_text())['features']) == count
    page.get_by_label('Review status filter').select_option('reject')
    expect(page.get_by_text('No tasks match this filter.', exact=True)).to_be_visible()
    with page.expect_download() as event:
        page.get_by_role('button', name='GeoJSON', exact=True).click()
    assert json.loads(Path(event.value.path()).read_text())['features'] == []
    page.get_by_role('button', name='Passenger activity', exact=True).click()
    expect(page.get_by_text('No measured passenger activity available', exact=True)).to_be_visible()
    page.screenshot(path=str(out / 'passenger-activity.png'), full_page=True)
    page.reload(wait_until='networkidle')
    expect(page.locator('.authority-card').first).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.reload(wait_until='networkidle')
    expect(page.locator('.authority-card').first).to_be_attached()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('.toolbar').evaluate('(el) => el.getBoundingClientRect().left >= 0 && el.scrollWidth <= el.clientWidth')
    page.screenshot(path=str(out / 'planning-mobile.png'), full_page=True)
    # Language toggle and return to driver journey after hard reload.
    page.get_by_role('button', name='language', exact=True).click()
    expect(page.get_by_role('button', name='Sərnişin axını', exact=True)).to_be_visible()
    page.get_by_role('button', name='← Sərnişin / Sürücü', exact=True).click()
    expect(page.locator('.authority-page')).to_have_count(0)
    assert not errors, errors
    browser.close()
print('PASS: driver search/unknown result; authority detail/read-only; filtered CSV/GeoJSON; report; activity empty state; base-path reload; mobile; AZ navigation')
