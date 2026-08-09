# Kora design system

## Product character

Kora is a calm, inspectable support-operations product for Nigerian fintech and e-commerce teams. It should feel precise, trustworthy, and human-owned. It must never resemble a flashy AI command centre, crypto dashboard, or generic SaaS template.

## Typography

- Primary typeface: Elms Sans Variable, self-hosted with `@fontsource-variable/elms-sans`
- Display: 600 weight maximum, tight tracking, compact line-height
- Body: 400–550 weight, comfortable line-height
- Operational labels: 9–10px, uppercase only for short metadata and section labels
- Avoid long all-caps sentences and tiny body copy

## Colour

- Core Color Hunt palette: `#E5CB90`, `#FFF3C8`, `#34A99D`, `#458393`
- Canvas and paper: clean blue-tinted whites; cream `#FFF3C8` is reserved for warm supporting surfaces
- Shell and primary ink: an accessibility-safe deep shade derived from blue `#458393`
- Accent: muted gold `#E5CB90`
- Strong interactive state: teal `#34A99D`; focus treatment uses blue `#458393`
- The accent is reserved for active navigation, confidence, machine assessment, selected state, and urgent attention
- No gradients, glass effects, purple, magenta, or unrelated decorative colour

## Surfaces

- The public URL opens directly into the workspace; there is no separate marketing surface
- Workspace: light operational register with a dark navigation rail
- Raw customer input stays neutral
- AI assessment uses a pale teal-tinted surface
- Human checkpoint uses a neutral paper surface with a dark top rule
- Shadows are rare and restrained; borders and spacing establish hierarchy

## Geometry and spacing

- 4px base spacing rhythm
- Control radius: 7px
- Card radius: 8–10px
- Pills only for statuses, confidence, and compact metadata
- Minimum primary control height: 44px
- Dense tables remain square-edged inside their containing card

## Interaction

- Buttons lift by 1–3px on hover and settle on press
- Do not scale controls on hover
- Navigation may shift horizontally by 2px to signal direction
- Focus rings use the strong teal and remain visible
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
