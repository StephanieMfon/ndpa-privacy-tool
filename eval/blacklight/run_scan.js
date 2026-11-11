// Scans one site with Blacklight. usage: node run_scan.js <url> <outDir> <chromePath> <chromeMajor> <vantage>
// The collector empties outDir first, so every site gets its own folder.
(async () => {
  let collect;
  try {
    ({ collect } = require('./blacklight-collector/build'));
  } catch (e) {
    console.log('RESULT ' + JSON.stringify({ status: 'failed', page_response: 'Could not load Blacklight: ' + String((e && e.message) || e).split('\n')[0] }));
    process.exit(0);
  }
  const [url, outDir, chromePath, major, vantage] = process.argv.slice(2);
  const result = await collect(url, {
    numPages: 0,
    headless: false,
    outDir,
    puppeteerExecutablePath: chromePath,
    emulateDevice: {
      viewport: { width: 1366, height: 768 },
      userAgent: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`,
    },
    captureHar: true,
    saveScreenshots: true,
    clearCache: true,
    defaultTimeout: 30000,
    quiet: true,
    location: vantage,
  });
  console.log('RESULT ' + JSON.stringify({ status: result.status, page_response: result.page_response ? String(result.page_response) : '' }));
  process.exit(0);
})().catch((e) => {
  console.log('RESULT ' + JSON.stringify({ status: 'failed', page_response: String(e.message || e) }));
  process.exit(0);
});
