#!/usr/bin/env python3
"""Review the speed timing preference against deterministic browser fixtures.

Run from the project root with the Playwright interpreter. Screenshots and JSON
are written to output/speed-timing-review; no service or usage DB is opened.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path.cwd()
OUT = ROOT / 'output/speed-timing-review'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    asks = []
    request_only = False

    def route(request_route):
        url = urlparse(request_route.request.url)
        if url.netloc != 'tokdash.test':
            request_route.continue_()
            return
        if url.path == '/api/output-speed':
            query = parse_qs(url.query)
            include = query.get('include_request_windows') == ['true']
            asks.append(include)
            common = dict(source='codex', model='gpt-6.1-sol', token_basis='including_reasoning',
                          speed_calls=40, eligible_calls=80, coverage=0.5,
                          days_with_measurements=1, selected_days=1,
                          speed_tokens=2000, speed_ms=40000, output_tok_per_s=50,
                          combined_tok_per_s=50, parallelism=1, peak_in_flight=1)
            rows = [] if request_only else [dict(common, measurement_kind='response_window')]
            if include:
                rows.append(dict(common, measurement_kind='request_window', speed_ms=50000,
                                 output_tok_per_s=40, combined_tok_per_s=40))
            merged = dict(common, sources=['codex'], measurement_kinds=[r['measurement_kind'] for r in rows])
            merged.pop('source')
            merged.update(speed_calls=40 * len(rows), speed_tokens=2000 * len(rows),
                          coverage=0.5 * len(rows), combined_tok_per_s=80 if include else 50)
            hidden = [dict(source='codex', model='gpt-6.1-sol', speed_calls=40)] if not include else []
            body = dict(rows=rows, models=[merged] if rows else [], source_status=[],
                        hidden_request_windows=hidden,
                        cache=dict(state='ready'), series=[], model_series=[], buckets=[],
                        range={'from': '2026-10-01', 'to': '2026-10-16'})
            request_route.fulfill(json=body)
        elif url.path == '/health':
            request_route.fulfill(json=dict(status='ok', service='tokdash', version='0.0.0'))
        elif url.path.startswith('/api/'):
            request_route.fulfill(json={})
        else:
            relative = url.path.removeprefix('/static/').lstrip('/') or 'index.html'
            path = ROOT / 'src/tokdash/static' / relative
            if path.is_file():
                request_route.fulfill(path=str(path))
            else:
                request_route.fulfill(status=404, body='')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            '--disable-gpu', '--disable-features=Vulkan,VizDisplayCompositor'], timeout=15000)
        page = browser.new_page(viewport=dict(width=1440, height=1050), reduced_motion='reduce')
        page.set_default_timeout(8000)
        page.on('pageerror', lambda error: (errors.append(str(error)), print(str(error), flush=True)))
        page.route('**/*', route)
        page.goto('http://tokdash.test/?tab=speed&range=thisMonth', wait_until='load', timeout=15000)
        page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
        page.locator('[data-speed-lens="stream"]').click()
        assert page.locator('#usageReportSpeedBody tr[data-speed-id]').count() == 1
        assert page.locator('#usageReportSpeedBody .speed-model-meta .speed-why').count() == 0
        page.evaluate('''async () => {
            await document.fonts.ready;
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }''')
        page.screenshot(path=str(OUT / 'default.png'), animations='disabled')
        page.evaluate('setSettingsPanelOpen(true)')
        assert not page.locator('#speedIncludeRequestWindows').is_checked()
        page.locator('#speedIncludeRequestWindows').check()
        page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
        page.screenshot(path=str(OUT / 'settings.png'), animations='disabled')
        page.evaluate('setSettingsPanelOpen(false)')
        assert page.locator('#usageReportSpeedBody tr[data-speed-id]').count() == 2
        assert page.locator('#usageReportSpeedBody .speed-model-meta .speed-why').count() == 2
        page.screenshot(path=str(OUT / 'both.png'), animations='disabled')
        page.reload(wait_until='load')
        page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
        assert page.evaluate('usageReportSpeedState.includeRequestWindows') is True
        page.evaluate('setSettingsPanelOpen(true)')
        page.locator('#speedIncludeRequestWindows').uncheck()
        page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
        page.evaluate('setSettingsPanelOpen(false)')
        assert page.locator('#usageReportSpeedBody tr[data-speed-id]').count() == 1
        translations = {}
        for language in ('en', 'zh', 'ja', 'ko', 'es', 'pt'):
            page.evaluate('setSettingsPanelOpen(true)')
            page.locator('#langToggle').select_option(language)
            copy = page.evaluate("""() => {
                const keys = ['usageReportSpeedIncludeRequests', 'usageReportSpeedTimingHint',
                    'speedKindShortServerDecode', 'speedKindShortPostFirstToken',
                    'speedKindShortResponseWindow', 'speedKindShortRequestWindow',
                    'speedKindServerDecode', 'speedKindPostFirstToken', 'speedKindResponseWindow',
                    'usageReportSpeedHiddenRequests', 'usageReportSpeedOpenTimingSettings',
                    'speedKindMethodServerDecode', 'speedKindMethodPostFirstToken',
                    'speedKindMethodResponseWindow', 'speedKindMethodRequestWindow'];
                return Object.fromEntries(keys.map(key => [key, I18N[currentLang][key]]));
            }""")
            assert all(isinstance(value, str) and value for value in copy.values()), language
            assert page.locator('[data-i18n="usageReportSpeedIncludeRequests"]').inner_text() == copy['usageReportSpeedIncludeRequests']
            assert page.locator('#speedTimingHint').inner_text() == copy['usageReportSpeedTimingHint']
            page.locator('#speedIncludeRequestWindows').check()
            page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
            page.screenshot(path=str(OUT / f'settings-{language}.png'), animations='disabled')
            page.evaluate('setSettingsPanelOpen(false)')
            labels = page.locator('#usageReportSpeedBody .speed-model-meta .speed-why').all_inner_texts()
            assert labels == [copy['speedKindShortResponseWindow'], copy['speedKindShortRequestWindow']], (language, labels)
            translations[language] = dict(setting=copy['usageReportSpeedIncludeRequests'], labels=labels)
            page.evaluate('setSettingsPanelOpen(true)')
            page.locator('#speedIncludeRequestWindows').uncheck()
            page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
            page.evaluate('setSettingsPanelOpen(false)')
            assert page.locator('#usageReportSpeedBody .speed-model-meta .speed-why').count() == 0
        request_only = True
        for language in ('en', 'zh', 'ja', 'ko', 'es', 'pt'):
            page.evaluate('setSettingsPanelOpen(true)')
            page.locator('#langToggle').select_option(language)
            page.evaluate('usageReportSpeedInvalidate(); usageReportLoadSpeed()')
            page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
            page.evaluate('setSettingsPanelOpen(false)')
            expected = page.evaluate('t("usageReportSpeedHiddenRequests")')
            assert page.locator('#usageReportSpeedBody').inner_text() == expected
            action = page.locator('#usageReportSpeedEmptyAction button')
            assert action.count() == 1
            assert action.inner_text() == page.evaluate('t("usageReportSpeedOpenTimingSettings")')
            assert page.locator('[data-speed-tool="codex"]').count() == 1
            action.click()
            assert page.locator('#settingsPanel').is_visible()
            page.locator('#speedIncludeRequestWindows').check()
            page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
            page.evaluate('setSettingsPanelOpen(false)')
            assert page.locator('#usageReportSpeedBody tr[data-speed-id]').count() == 1
            page.evaluate('setSettingsPanelOpen(true)')
            page.locator('#speedIncludeRequestWindows').uncheck()
            page.wait_for_function('usageReportSpeedState.loadedKey && !usageReportSpeedState.loading')
            page.evaluate('setSettingsPanelOpen(false)')
        assert False in asks and True in asks
        assert not errors, errors
        browser.close()
    result = dict(passed=True, request_scopes=asks, page_errors=errors, translations=translations)
    (OUT / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
