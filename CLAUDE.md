# AI Assistant Instructions

This is an AI-powered job application pipeline. See README.md for architecture
and SETUP.md for onboarding a new user.

## Candidate memory (always-on behavior)

`config/candidate_notes.md` (gitignored) is the candidate's living memory. The
resume/cover-letter generator reads it on every run.

**Whenever the candidate reveals something new about themselves in conversation
— a tool they've used, an experience or story, a personal angle, a preference
or constraint, a writing-style correction — append it to the matching section
of `config/candidate_notes.md` in the same turn.** If you're unsure it's true
or resume-grade, confirm with them first. Never record anything they haven't
actually said about themselves.

Examples of capture-worthy moments:
- "I actually used Hex a bit at my last job" → Tools & skills
- "fraud was always front of mind at my fintech job" → Experiences & stories
- "my wife is a therapist" (offered for a mental-health company) → Personal angles
- "that closer is lame, cut it" → Writing style notes

## Material quality rules

- Verify any factual claim about a company before it ships; delete what can't
  be verified.
- Resume dates and titles must exactly match the candidate's LinkedIn.
- Never claim skills or experience the candidate hasn't confirmed.
- No em dashes in generated materials. No generic closers.
- Always have the candidate review PDFs before submission (see README
  "Before you send anything").
