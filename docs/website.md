# Project website

The landing page lives in `site/` and is published at <https://youhaveme9.github.io/dreamseed/>. It is plain HTML, CSS, and JavaScript with local assets. There is no frontend build, analytics script, font service, backend, or API key.

The public page introduces the project. It does not run seed searches. The separate `dreamseed-web` application runs on the user's computer.

## Preview and checks

```sh
python3 -m http.server 8767 --bind 127.0.0.1 --directory site
```

Open <http://127.0.0.1:8767>. Stop the preview with Ctrl+C.

```sh
python3 scripts/check_site.py
node --check site/app.js
python3 scripts/build_site_assets.py
```

The checks cover local links, fragment targets, image metadata, JSON evidence, SVG syntax, and the 2 MB total asset budget. Rendering the committed evidence data requires no Minecraft server.

Optional real browser checks use Playwright 1.61.0. Keep its dependencies outside the product environment:

```sh
npm install --prefix build/site-browser --no-save playwright@1.61.0 axe-core@4.10.3
./build/site-browser/node_modules/.bin/playwright install chromium
DREAMSEED_PLAYWRIGHT_PATH="$PWD/build/site-browser/node_modules/playwright" \
  DREAMSEED_AXE_PATH="$PWD/build/site-browser/node_modules/axe-core/axe.min.js" \
  node scripts/test_site.cjs
```

`DREAMSEED_CHROMIUM_PATH` can select an existing compatible Chromium executable. The browser test starts and stops its own local server, tests the `/dreamseed/` project path, checks six screen sizes, exercises copy buttons and keyboard controls, and saves screenshots in `build/site-qa/`.

With `DREAMSEED_AXE_PATH` set, it also runs automated WCAG A and AA checks for desktop and mobile across all four setup tabs. This is useful regression coverage, not a complete accessibility certification.

## Deployment

In the repository's **Settings → Pages**, select **GitHub Actions** as the build source. The pinned `.github/workflows/pages.yml` validates and publishes only `site/` on relevant pushes to `main`. Pull requests validate without publishing. Manual workflow dispatch is also available.

No custom domain is configured. Relative asset paths allow the page to work under the repository's `/dreamseed/` prefix. The workflow requires Pages write permission and an identity token for the deployment job only.

Before updating a release number, confirm that its downloadable assets and linked documentation exist. Do not present illustrative artwork or Cubiomes predictions as official Minecraft verification. See [asset provenance](../site/assets/README.md) for the image prompt, source data, and rendering details.
