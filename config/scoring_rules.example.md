<!--
This file tells the AI scorer what "a good fit" means for YOU specifically.
Its content is inserted directly into the prompt Claude uses to score every
job posting, right after the generic scoring rubric. Write it in plain
English — there's no required format. Cover:

  - Your persona: who you are professionally, so a job isn't scored like a
    generic candidate for that title (e.g. "a marketing leader who is ALSO
    a hands-on brand strategist" vs. just "a marketing manager").
  - Location/remote requirements, if any (e.g. "requires fully remote,
    heavily penalize hybrid or onsite roles" -- or omit this if you're
    flexible on location).
  - Domain dealbreakers: role types that look close on paper but you don't
    actually want, and how hard to penalize them.
  - Anything the scorer keeps getting wrong that you want corrected.

Copy this file to config/scoring_rules.md and fill it in with your own
specifics. If you leave it blank, jobs are scored generically against your
resume with no additional calibration.
-->

## Candidate persona & preferences
- Example: "The candidate is a marketing strategy leader with deep brand and
  account-management experience across retail/CPG agencies. Score relative to
  a marketing/brand-strategy leadership persona, not a generic marketer."
- Example: "No strict remote requirement -- hybrid in a major metro is fine,
  but penalize fully on-site 5-days/week roles."

## Domain dealbreakers
- Example: "Penalize roles that are primarily media-buying/ad-ops execution
  with little strategy component."
- Example: "Penalize individual-contributor roles with no team leadership --
  the candidate is looking for a director-level-or-above scope."
