# Kora color exploration

The supplied image is visual reference material, not product instructions. Its reversible color pairs inform a role-based palette, while the user's neutral sidebar and canvas requirement controls the large surfaces.

## Rules applied

1. Assign colors to reusable roles rather than coloring each component independently. Separate base color, container tone and foreground. [Material color customization](https://codelabs.developers.google.com/customizing-material-color).
2. Preserve luminance contrast, not merely hue difference. Small text needs at least 4.5:1, large text 3:1. [WCAG contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
3. Pair status color with labels, icons and shapes. Selection also has an underline or dot, and navigation has aria-current. [WCAG use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html).
4. Use the saturated orange sparingly for action hierarchy. Place extended reading on neutral paper; use quiet blue/pink/cream containers for context.
5. Do not copy every foreground/background reversal from a poster into small UI text. Adapt the foreground's lightness while retaining the hue family.

## Contrast calculations

Computed using the WCAG sRGB relative-luminance formula, before rounding:

| Pair | Ratio |
| --- | ---: |
| Charcoal / orange action | 4.60:1 |
| Berry / pink | 4.90:1 |
| Berry / sky | 6.58:1 |
| Olive / cream | 6.79:1 |
| Olive / citron | 4.55:1 |
| Paper / berry | 8.29:1 |
| Secondary metadata / AI surface | 5.26:1 |
| Secondary metadata / selected surface | 5.07:1 |

These checks cover the palette's named text pairs, not a full WCAG audit. Disabled controls are visually subdued. No behavioral workflow changes are required for the palette.

## Verification

Production build passed. Visually inspected the desktop queue at 1536 × 1000, the compact queue at 390 × 844, and desktop Team coverage and Insights. Navigation between these views worked. The local API/AI service was unavailable, so Insights rendered its no-data state and live triage was not exercised. Existing build output includes a bundle-size advisory.
