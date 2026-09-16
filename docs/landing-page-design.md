# Kora landing page, September 2026

## Direction

Warm, rounded, and clear. A support manager browsing on their phone in a bright daytime office should immediately recognise their team's conversations and see how Kora helps. Retain the app's Elms Sans and Peel Club palette; give the marketing surface more room for colour than the operational workspace.

The hero sits directly on the page without a coloured enclosing rectangle. Berry type, a pink customer message, and a blue assessment carry the colour. Action orange distinguishes links into the workspace; cream supports routing. The rounded berry call-to-action rectangle above the footer is retained at the user’s request. Accessible text derivatives replace the poster's low-contrast cream/citron lettering. Landing colours remain local so a saved dark workspace theme does not alter this art direction.

## References reviewed

- [Pinterest colourful landing-page reference](https://www.pinterest.com/pin/342766221640318998/): inspected the visible artwork and rounded Pinterest presentation; further browsing was limited by a sign-in overlay. The stock illustration was not used.
- [Slite](https://slite.com/): inspected the live site, including pill controls, generous type, and a product demonstration that makes the promise concrete.
- [Intercom](https://www.intercom.com/): reviewed the human-and-AI support positioning and product walkthrough structure.
- The user's Peel Club image and the existing app tokens are the colour source, not the reference websites.

Decorative orbit rings, rotated panels, sparkles, the floating slogan sticker, oversized shield ornament, and repetitive slogan copy have been removed. Feature sections use open layouts with colour reserved for the examples.

## Scope and behaviour

- `LandingPage.jsx` and `landing-page.css` own the new surface.
- `/` renders the landing page. `/app` and existing workspace paths retain `DashboardApp`; root `?case=` links retain their previous destination.
- All primary calls to action lead to `/app`.
- Three local example scenarios update the message, classification, team, and reply together. They are explicitly illustrative and make no API calls.
- FAQs use native disclosure controls. The mobile menu exposes its expanded state and closes after navigation.
- No testimonials, performance statistics, or customer logos were invented.

## Validation

- Production build and `git diff --check` pass. Vite reports a bundle-size advisory for the combined app entry.
- Browser verified at desktop and mobile sizes, including 1440px, 390px, and 320px; no horizontal document overflow.
- Delivery and fraud examples, FAQ expansion, mobile navigation, and primary workspace navigation verified.
- Landing browser console had no errors or warnings. Existing workspace queue renders at `/app`.
- Compared against a pre-edit copy: shared `src/index.css` is unchanged, and existing dashboard code is unchanged. `App.jsx` only adds the landing import and root-route selection.
