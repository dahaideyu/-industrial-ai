const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://localhost:5173/login');
  await page.evaluate(() => localStorage.setItem('auth_token', 'test-token'));

  const tests = [
    ['/knowledge-management', 'BaseDashboard', ['.stats-bar', '.tree-panel', '.section-title']],
    ['/knowledge-management/kb-type/device_doc', 'WorkshopView', ['.breadcrumb', '.stats-bar']],
    ['/knowledge-management/compliance', 'ComplianceView', ['.breadcrumb', '.stats-bar']],
    ['/knowledge-management/custom', 'CustomDocs', ['.breadcrumb']],
    ['/knowledge-management/admin/categories', 'CategoryAdmin', ['.breadcrumb', '.tree-panel', '.split-layout']],
  ];

  let ok = 0, total = tests.length;
  for (const [url, name, selectors] of tests) {
    try {
      console.log('Testing:', name);
      await page.goto('http://localhost:5173' + url, { waitUntil: 'networkidle', timeout: 15000 });
      let allFound = true;
      for (const sel of selectors) {
        const found = await page.$(sel);
        if (found) {
          console.log('  OK', sel);
        } else {
          console.log('  MISSING', sel);
          allFound = false;
        }
      }
      if (allFound) ok++;
    } catch(e) {
      console.log('  ERROR:', e.message);
    }
  }

  console.log('\n=== ' + ok + '/' + total + ' pages render correctly ===');
  await browser.close();
  process.exit(ok === total ? 0 : 1);
})();
