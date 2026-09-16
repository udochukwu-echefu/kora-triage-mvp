# Main queue redesign

Research date: 8 September 2026. These are selected design references, not a claim of an objective worldwide ranking. Selection favors ticket scanning, useful density, predictable controls, and customer context.

## Reference shortlist

| Reference | Evidence reviewed | Application to Kora |
| --- | --- | --- |
| [Modern Service Desk Dashboard, Lena Aravind, Dribbble](https://dribbble.com/shots/26639254-Modern-Service-Desk-Dashboard-Streamlined-Ticket-Management) | Project description and rendered screenshot | A persistent ticket list beside the current case; clearly separated filters and contextual details. |
| [Helpdesk Ticket Dashboard Redesign, Wastian Salwa, Behance](https://www.behance.net/gallery/233862301/Helpdesk-Ticket-Dashboard-Redesign) | Project description and rendered screenshot | Counted view tabs, lighter table/list hierarchy, progressive filters, and quiet teal selection. |
| [Customer Support Platform Inbox, Pinterest](https://www.pinterest.com/pin/770326711242578290/) | Public pin preview; login overlay limits deeper inspection | Compact identity-led rows and supporting customer context. Attribution is limited to the pin; original designer was not verified. |
| [Customer Service Dashboard, Srinidhi Balaji and aspira design, Behance](https://www.behance.net/gallery/160830795/Customer-Service-Dashboard-UXUI) | Indexed project description | Clear emphasis on important operational information. Kora uses actionable view counts instead of a reporting dashboard. |
| [Inbox, Web App, Pinterest](https://au.pinterest.com/pin/66217057008547952/) | Search preview only | Supplemental inbox reference; not used to infer detailed interaction behavior. |
| [Customer Support System Dashboard, Pinterest](https://in.pinterest.com/pin/customer-support-system-dashboard-ticketing-in-2025--809240626832330777/) | Search preview only | Supplemental ticketing reference; not used to infer detailed interaction behavior. |

## Design decisions

The scene is a support agent handling a busy daytime shift on a laptop in a normally lit office. A light workspace keeps messages readable, with Kora's existing dark teal navigation and restrained gold accents.

- Replace large priority summaries with counted All conversations, Needs review, SLA risk, and Unassigned views. Counts use the same predicates as their views before additional search/filter narrowing.
- Use a 355–360px inbox on desktop, with consistent identity, subject, preview, channel, case ID, and SLA placement. The full message remains in the case panel.
- Keep search visible; expand channel, urgency, and team filters on demand. Display the number of active detailed filters.
- Add priority, oldest-first, and newest-first sorting without mutating source tickets.
- Use a pale teal selected row and a small current-case marker, replacing the accent stripe.
- Keep customer message, ownership/status context, and human response together. At 1500px and above, supporting classification and evidence occupy a right-hand column.
- Preserve existing classification, review, approval, assignment, evidence, privacy masking, and delivery actions.
- At mobile width, open one conversation at a time with a back-to-queue control and reachable response actions.

## Validation

- Production build passes.
- Browser renders without logged JavaScript errors.
- Search for Amina returns two conversations.
- Newest-first places KOR-2401 first after search is cleared.
- SLA view returns four matching seed cases.
- Email filter returns six matching seed cases.
- Mobile opening and returning to a case works; document width equals the 390px viewport with no horizontal page overflow.
- Wide layout visually inspected at 1600px.
- Local AI/backend service unavailable during validation. Live classification, approval persistence, and message delivery were not exercised.
