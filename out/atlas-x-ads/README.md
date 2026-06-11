# Atlas X Ad Creatives — reusable template

Generator: `scripts/atlas_creative_template.py` (single source of truth).
Brand: AlgoAlpha (yellow #ffd400 + crimson #c9165b, dark UI, Inter).
Product: Atlas AI Backtester. Persuasion-style copy (dream outcome + proof +
low effort/risk + one bold claim + one CTA). The word "Hormozi" is never printed.

## Regenerate

```
py scripts/atlas_creative_template.py            # all 7 angles, both sizes (14 PNGs)
py scripts/atlas_creative_template.py pain proof # only these angle keys
```

## 7 angles (each rendered at 1200x628 + 1080x1080)

| key | angle | headline |
|-----|-------|----------|
| pain | pain → relief | Stop hunting for strategies. Let the AI find them. |
| proof | metrics / proof | Strategies ranked by win rate, profit and risk. |
| curiosity | curiosity hook | What if your backtesting ran itself? |
| vs | before/after | Manual backtesting vs Atlas. |
| time | hours→seconds | Find an edge in seconds, not weekends. |
| social | social proof | Signal first. Then trade. |
| risk | risk reversal | Test the AI free. |

## Sizes
- `*_1200x628.png` — 1.91:1, website-card / single-image ad
- `*_1080x1080.png` — 1:1, square feed ad

## To add/edit an angle
Edit the `CREATIVES` list in the template (one dict per angle: pill, headline,
highlight, sub, cta, foot, kind). `kind` = `hero` | `kpi` (adds metric cards) |
`vs` (adds the comparison columns). Re-run the generator.

## Paste into X Ads Manager
Pair each image with its matching copy variant from `Atlas-X-Ads-Brief.pdf`.
Landscape for the website-card / Sales objective; square for feed + retargeting.
A/B at least 2 angles per ad group.

## Saved X draft
The built campaign "Atlas AI - Sales - Jun 2026" (Sales objective, $30/day, US /
English / Financial Markets interest / trading keywords, Purchase conversion
event, pain creative + copy) is saved as a DRAFT in X Ads Manager. It needs a
valid funding source before it can publish (card on file failed). Duplicate that
draft to reuse the structure for the other angles.
