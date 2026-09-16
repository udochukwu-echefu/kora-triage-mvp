# Kora design system

## Product character

Kora is a calm, inspectable support-operations product for Nigerian fintech and e-commerce teams. It should feel precise, trustworthy, and human-owned. It must never resemble a flashy AI command centre, crypto dashboard, or generic SaaS template.

## Typography

- Primary typeface: Elms Sans Variable, self-hosted with `@fontsource-variable/elms-sans`
- Display: 600 weight maximum, tight tracking, compact line-height
- Fixed product type ramp: 12px caption, 13px footnote, 14px callout, 15px body, 17px headline, 20px title 3, 22px title 2, 26px title 1
- Body and form text: 15–16px with 1.5–1.65 line-height; use 14px only for compact controls and dense table values
- Operational labels and secondary metadata: 12–13px; never use text below 12px
- Use Regular, Medium, and Semibold weights. Avoid light weights and excessive all-caps copy

## Colour

The September 2026 exploration uses the user's Peel Club reference as a palette, with product-specific accessible text derivatives. Support agents work through long queues in a bright daytime office; white working surfaces keep dense text comfortable, and color helps locate actions and decisions.

- Keep the main canvas neutral near-white (`#FAFAF9`) and sidebar/panels paper (`#FEFDFC`). Never flood either background with brand colors.
- Action orange is a deeper accessible brand tone, paired with warm white text at WCAG AA contrast. Use it for the brand mark and primary actions; lighter orange is not used behind text.
- Pink `#F6B5B8` + berry `#980E49`: human attention and high urgency. Berry text on pink is 4.90:1; use pale pink for longer review notices.
- Sky `#CFE7F6` + berry: active navigation, current selection, AI context. Berry on sky is 6.58:1; use paler blue for large intelligence panels.
- Citron `#CDCF4C` + cream `#F6F5CD`: availability and supporting status surfaces. Use olive `#535817` for readable text (4.55:1 on citron, 6.79:1 on cream). Never reproduce the low-contrast cream/citron lettering from the poster in UI text.
- Critical urgency uses solid berry with light text and a diamond; high urgency uses pink with a dot and label. Keep textual status cues.
- Quiet borders stay neutral. Focus, active tab underlines, selected-row dots and chart confidence use berry.
- Charts pair berry confidence with olive measured accuracy and named tooltip series. Avoid low-contrast pastel chart marks on white.
- All source tokens are stored in OKLCH in `src/index.css`. Reference hex values above are their sRGB equivalents.
- Color is concentrated in navigation selection, compact counts, statuses, actions and supporting context. Raw customer messages and response fields remain neutral.
- No gradients or colored shadows. Use restrained elevation and consistent geometry.

See `docs/color-system.md` for research and contrast validation.

## Surfaces

- The public `/` URL opens the rounded, full-palette landing page. `/app` opens the existing workspace; root URLs with a `case` query retain their workspace destination. Landing-page styles are scoped in `src/components/landing-page.css` and preserve the workspace theme. See `docs/landing-page-design.md`.
- Workspace: lightly tinted operational canvas with a floating, rounded white navigation rail, approximately 244px wide on desktop
- Raw customer input stays neutral
- AI assessment uses a pale sky surface with berry headings, differentiated through labels and iconography
- Human checkpoint uses a neutral paper surface with a dark top rule
- Shadows are rare and restrained; borders and spacing establish hierarchy

## Geometry and spacing

- 4px base spacing rhythm
- Control radius: 12px
- Supporting-panel radius: 14–16px
- Major-surface radius: 18px
- Pills only for statuses, confidence, and compact metadata
- Minimum primary control height: 44px
- Dense tables retain aligned rows inside a rounded containing surface

## Interaction

- Buttons lift by 1–3px on hover and settle on press
- Do not scale controls on hover
- Navigation may shift horizontally by 2px to signal direction
- Form fields use a subtle one-pixel berry-tinted focus halo; keyboard focus on actions remains clearly visible
- Honour `prefers-reduced-motion`

## Component policy

- Use the local shadcn-style components in `src/components/ui`
- Use Radix primitives for menus and tooltips
- Use Lucide icons with text labels; do not use emoji or decorative icon tiles
- One primary action per decision area
- Empty, loading, offline, and pending states must be explicit

## Accessibility

- Maintain WCAG AA contrast for body copy and controls
- Do not communicate urgency with colour alone; include a dot or diamond and text
- All icon-only controls require accessible labels
- Desktop and mobile flows must remain keyboard reachable

## Main queue (September 2026)

- Counted priority views replace oversized summaries; the main inbox supports priority, oldest, and newest sorting.
- Desktop inbox is 355–360px wide with a continuous list surface, initial avatars, single-line previews, and aligned SLA metadata.
- Filters expand on request and display an active-filter count.
- The selected conversation uses a pale sky surface and a small dot, without an accent stripe.
- At 1500px and above, case context sits beside the response in a 260px supporting column; narrower layouts stack it below.
- Reference research and verification: `docs/queue-design-references.md`.
