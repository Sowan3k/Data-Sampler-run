"""Browser checks for the real interface (headless Chrome, desktop 1366 px and mobile 390 px).

Not part of the pytest suite. Uses fixture data only; never run against a real research database.

    pip install playwright            # and have Google Chrome installed
    mkdir /tmp/ui_data
    python tests/browser/seed_fixture.py . /tmp/ui_data
    RESEARCH_DATA=/tmp/ui_data python run.py          # in a second terminal, note the port
    python tests/browser/browser_checks.py http://127.0.0.1:8765 "$(cat /tmp/ui_data/admin.token)" /tmp/ui_shots

Adjust executable_path below if Chrome is installed elsewhere. Results go to /tmp/ui_shots/results.json.
"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
base, admin_token, out = sys.argv[1], sys.argv[2], Path(sys.argv[3]); out.mkdir(exist_ok=True)
results = []
def ok(name, cond, detail=''):
    results.append((name, bool(cond), detail)); print(('PASS ' if cond else 'FAIL ') + name + (f' ({detail})' if detail else ''))

ADMIN_PAGES = ['Overview', 'Research setup', 'API connections', 'Data discovery', 'Video library', 'AI screening', 'Jobs', 'Coding & reliability', 'Analysis & reports', 'Data compliance', 'Activity log', 'Help']
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    for label, vp in [('desktop', {'width': 1366, 'height': 900}), ('mobile', {'width': 390, 'height': 844})]:
        ctx = browser.new_context(viewport=vp, accept_downloads=True); page = ctx.new_page()
        errors = []; page.on('pageerror', lambda e: errors.append(str(e))); page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.goto(f'{base}/#token={admin_token}'); page.wait_for_selector('h1')
        for name in ADMIN_PAGES:
            if label == 'mobile': page.click('#menu')
            page.click(f'.nav button:text-is("{name}")'); page.wait_for_function('document.querySelector("#content p.muted")?.textContent !== "Loading…"')
            page.wait_for_timeout(250)
            body = page.inner_text('#content')
            overflow = page.evaluate('document.scrollingElement.scrollWidth - window.innerWidth')
            ok(f'{label}: {name} loads with guidance', 'Unable to load' not in body and 'what this page is for' in body.lower(), body[:80].replace('\n', ' ') if 'Unable to load' in body else '')
            ok(f'{label}: {name} has no horizontal page overflow', overflow <= 1, f'{overflow}px')
            page.screenshot(path=str(out / f'{label}-{name.replace(" & ", "-").replace(" ", "-").lower()}.png'), full_page=False)
        ok(f'{label}: no browser errors on admin pages', not errors, '; '.join(errors[:3]))
        ctx.close()

    # Library "Load more" and filters (desktop)
    ctx = browser.new_context(viewport={'width': 1366, 'height': 900}, accept_downloads=True); page = ctx.new_page()
    page.on('dialog', lambda d: d.accept())
    page.goto(f'{base}/#token={admin_token}'); page.wait_for_selector('h1')
    page.click('.nav button:text-is("Video library")'); page.wait_for_selector('#librarytable p')
    first = page.inner_text('#librarytable p'); rows = page.locator('#librarytable tbody tr').count()
    ok('library shows totals and 100 rows first', 'Showing 100 of' in first and rows == 100, first)
    page.click('button[data-action="load-more"]'); page.wait_for_timeout(200)
    total = int(first.split(' of ')[1].split(' ')[0])
    ok('Load more reveals the rest', page.locator('#librarytable tbody tr').count() == min(200, total), page.inner_text('#librarytable p'))
    page.select_option('#statusfilter', 'eligible'); page.wait_for_timeout(200)
    ok('filter by screening decision', page.locator('#librarytable tbody tr').count() == 2, page.inner_text('#librarytable p'))

    # Admin video review: screening rules, navigation
    page.select_option('#statusfilter', 'all'); page.fill('#filter', 'AAAAAAAAAA'); page.wait_for_timeout(200)
    page.locator('button[data-video="AAAAAAAAAA2"]').click(); page.wait_for_selector('.videonav')
    ok('video page shows navigation and position', page.locator('.videonav').inner_text().startswith(('1 of', '2 of', '3 of', '4 of')), page.locator('.videonav').inner_text())
    page.select_option('#screening', 'excluded'); page.click('button[data-action="observe"]'); page.wait_for_timeout(300)
    ok('excluding without a reason is refused', 'exclusion reason' in page.inner_text('#notice').lower(), page.inner_text('#notice'))
    page.select_option('#screenreason', 'not_election_related'); page.click('button[data-action="observe"]'); page.wait_for_timeout(400)
    ok('excluding with a reason saves', page.inner_text('#notice').startswith('Saved'), page.inner_text('#notice'))
    page.click('button[data-action="nav-todo"]'); page.wait_for_selector('.videonav'); page.wait_for_timeout(200)
    ok('Next unscreened moves to another video', 'AAAAAAAAAA2' not in page.inner_text('h1'), page.inner_text('.lead'))
    page.screenshot(path=str(out / 'desktop-video-review-admin.png'), full_page=True)
    # adjudication is blocked for a video in the open round
    page.goto(f'{base}/#token={admin_token}'); page.wait_for_selector('h1')
    page.click('.nav button:text-is("Coding & reliability")'); page.wait_for_selector('button[data-video]')
    page.locator('button[data-video]').first.click(); page.wait_for_selector('.annot')
    ok('admin sees adjudication blocked during open round', 'Adjudication blocked' in page.inner_text('.annot'))
    # exports
    page.click('.nav button:text-is("Data compliance")'); page.wait_for_selector('button[data-action="export-package"]')
    with page.expect_download() as d: page.click('button[data-action="export-package"]')
    ok('reproducibility package downloads', d.value.suggested_filename == 'reproducibility_package.zip')
    with page.expect_download() as d: page.click('button[data-action="export-searchlog"]')
    ok('search log downloads', d.value.suggested_filename == 'search_log.csv')
    ctx.close()

    # Coder session on mobile: drafts, unsaved warning, submit, next uncoded
    for label, vp in [('mobile coder', {'width': 390, 'height': 844}), ('desktop coder', {'width': 1366, 'height': 900})]:
        ctx = browser.new_context(viewport=vp); page = ctx.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        dialogs = []; unload = []
        page.on('dialog', lambda dlg: (unload.append(1), dlg.accept()) if dlg.type == 'beforeunload' else (dialogs.append(dlg.message), dlg.dismiss()))
        coder = 'coderA' if label.startswith('mobile') else 'coderB'
        page.goto(f'{base}/#token=token-{coder}'); page.wait_for_selector('h1')
        ok(f'{label}: lands on My assignments with guidance', 'My assignments' in page.inner_text('h1') and 'what this page is for' in page.inner_text('#content').lower())
        page.locator('button[data-video]').first.click(); page.wait_for_selector('.annot')
        vid = page.inner_text('.lead').split('Video ID ')[1].split(' ')[0]
        ok(f'{label}: blind mode hides AI drafts and evidence', 'Blind coding' in page.inner_text('#content') and 'Origin evidence' not in page.inner_text('#content'))
        page.click('button[data-action="add-persona"]'); page.select_option('#p0_gender', 'male'); page.select_option('#p0_age', 'elderly'); page.select_option('#p0_endorses_party', 'bnp')
        page.select_option('#eligibility', 'eligible'); page.wait_for_timeout(700)
        saved = page.evaluate('Object.keys(localStorage).filter(k=>k.startsWith("sc-draft"))')
        ok(f'{label}: draft saved locally while typing', len(saved) == 1, str(saved))
        page.click('button[data-action="back"]'); page.wait_for_timeout(200)
        ok(f'{label}: leaving with unsaved changes asks first', dialogs and 'unsaved' in dialogs[-1].lower(), str(dialogs[-1:]))
        page.reload(); page.wait_for_selector('h1')
        ok(f'{label}: reloading with unsaved changes triggers the browser warning', unload)
        page.locator(f'button[data-video="{vid}"]').click(); page.wait_for_selector('.annot')
        ok(f'{label}: draft offered after reload', page.locator('.draftbar').count() == 1)
        page.click('button[data-action="restore-draft"]'); page.wait_for_selector('#p0_gender')
        ok(f'{label}: draft restores the codes', page.eval_on_selector('#p0_age', 'e=>e.value') == 'elderly')
        page.click('button[data-action="save-annotation"]'); page.wait_for_timeout(400)
        ok(f'{label}: submission accepted', page.inner_text('#notice').startswith('Submitted'), page.inner_text('#notice'))
        ok(f'{label}: draft cleared after submit', page.evaluate('Object.keys(localStorage).filter(k=>k.startsWith("sc-draft")).length') == 0)
        page.click('button[data-action="nav-todo"]'); page.wait_for_timeout(400)
        ok(f'{label}: Next uncoded goes to the remaining video', vid not in page.inner_text('.lead'), page.inner_text('.lead')[:60])
        overflow = page.evaluate('document.scrollingElement.scrollWidth - window.innerWidth')
        ok(f'{label}: video page has no horizontal overflow', overflow <= 1, f'{overflow}px')
        page.screenshot(path=str(out / f'{label.replace(" ", "-")}-video-review.png'), full_page=True)
        ok(f'{label}: no browser errors', not errors, '; '.join(errors[:3]))
        ctx.close()
    browser.close()
json.dump([{'test': n, 'passed': ok_, 'detail': d} for n, ok_, d in results], open(out / 'results.json', 'w'), indent=2)
print(f"\n{sum(r[1] for r in results)} of {len(results)} browser checks passed")
