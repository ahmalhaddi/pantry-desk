# Questions for a pantry coordinator

Pantry Desk is a first version built around a guess: a coordinator could replenish sites more carefully if stewards reported what they can take, and the coordinator reserved food against that report.

This is not a pilot. Nobody at a food rescue organization has used it. The Detroit sites in the demo are fictional.

## What the app assumes

- One network is enough for the first release.
- Stewards can name a quantity in crates, cases, or pounds, and those units are not converted.
- A capacity report is usable for 48 hours. That number is configurable.
- A receiving window fits a batch when it is still open and starts before the distribution deadline.
- Storage has to match exactly: refrigerated food does not go to an ambient-only site.
- A reservation holds stock until someone confirms receipt or a coordinator cancels it.
- Confirming receipt does not put the food back. Canceling a reservation does, and only once.
- A newer capacity report does not erase a reservation already made. If the new report is smaller than what is already reserved, further reservations wait.
- Suggestions rank sites by reported quantity minus what that site was reserved or delivered in the last 14 days. The sentence on screen is the explanation. The rank is not an optimal plan, and it does not identify a "hungriest" neighborhood.
- Residents do not need accounts, and the app does not collect household information.

## What I would ask before changing it

- Do stewards actually know a quantity, in a stable unit, on the morning of a delivery?
- Is 48 hours too long, or too short, for a report to stay trustworthy?
- Should a coordinator be able to reserve food for a site with a stale report in an emergency, with that override written down?
- What should happen when a site accepts only part of a delivery? This version treats receipt as all or nothing.
- Are produce, dairy, bakery, shelf-stable food, and frozen food the categories coordinators use?
- Who is allowed to cancel after a truck has left?
- Do several stewards share one site, or is one steward enough?
- Is the network the right boundary, or do coordinators think in routes and buildings?

## What the demo counts

The app can show quantity reserved and quantity delivered. It does not show food waste prevented, meals served, or pounds rescued. Those would need a definition and a measurement this project does not have.
