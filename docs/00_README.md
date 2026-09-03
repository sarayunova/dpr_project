# Drilling DPR Monitor — Project Initiation Documents

This folder is a starting document set for building the Drilling DPR
Monitor with Claude Code. Hand Claude Code this whole folder (or paste
its contents into the conversation) when you start the project.

## What's already drafted vs. what you need to fill in

Drafted from real analysis of an actual ONGC DPR sample and a working
prototype already built and tested:

- `02_data_dictionary.md` — every field in the real DPR PDF, mapped
- `04_data_model.md` — entity/relationship design
- `05_architecture.md` — pipeline and tech stack
- `06_llm_prompts_and_eval.md` — the exact LLM prompts to use, plus a
  starter evaluation set
- `08_api_specification.md` — REST API contract
- `11_implementation_phases.md` — the build order; work through this
  one phase at a time rather than tackling everything at once
- `03_sample_documents/sample_dpr.txt` — a real (as-uploaded) DPR text
  sample used to validate the parsing logic in this doc set

Templates you need to complete with information only you have:

- `01_PRD.md` — fill in the bracketed `[ ]` sections
- `03_sample_documents/README.md` — add your actual sample PDFs here
  (proposal/AFE PDF especially — not yet analyzed)
- `07_non_functional_requirements.md` — your org's actual constraints
- `09_ui_wireframes.md` — sketch or describe your preferred screens
- `10_acceptance_criteria.md` — define your own pass/fail tests

## Suggested first prompt to Claude Code

```
I'm starting a new project. Read every file in this docs/ folder before
writing any code. Then confirm your understanding of the data model and
pipeline, and start on Phase 0 in 11_implementation_phases.md. Stop and
check in with me at each phase's exit criteria before moving to the next.
```

## Known open item

The proposal/AFE PDF has not yet been analyzed against real data — only
the DPR format has. Before Claude Code implements proposal ingestion,
give it a real (redacted if needed) sample proposal/AFE PDF so field
extraction is built against the actual layout, not a guess.
