# Plan in plain words

Write this together, in plain language. Then the plan owner runs `/lanes-plan` in Claude Code.
It proposes how to split the work in `.lanes/plan.proposed.yaml`, and nothing changes until the
plan owner reviews it (`$lanes plan diff`) and accepts it (`$lanes plan accept`).
To re-plan mid-project, edit this file and run `/lanes-plan` again.

## Goal
<!-- One or two sentences: what will be true when this feature is done? -->
Example: Users can export their order history as CSV from the account page.

## What needs building
<!-- The pieces of work, as a bullet list. Name files or folders when you know them. -->
- Example: a CSV export endpoint in `src/api/export/`
- Example: an "Export" button on the account page (`src/pages/account/`)
- Example: tests for both

## Team
<!-- One line per person: their member id, what they want to (or must) work on, anything they can't do.
     Assignments written here always win over what the planner would pick. -->
- $member: example: the API and anything touching the database
- teammate: example: the UI; new to the codebase, so keep their task self-contained

## Rules
<!-- Constraints the plan must respect. -->
- Example: `src/db/schema.py` must not change without the whole team agreeing.
- Example: keep the export format stable; mobile clients read it.
