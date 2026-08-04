# ADR-0003: Frame the Competition Entry as an Internal Product Desk Copilot

**Date:** 2026-08-04

**Status:** Accepted

## Context

The competition asks for a financial-product Agent that searches, compares, calculates, and explains information from four heterogeneous product masters. The submission also receives qualitative evaluation including problem definition, workplace usefulness, answer accuracy, completeness, and risk management.

The project needs a product definition that makes these requirements feel like one valuable workflow without inventing a customer segment or expanding into personalized investment advice. The user explicitly chose competition performance as the first priority and does not want the initial scope optimized around one primary commercial persona.

## Decision

Frame the Financial Product Agent as an **internal financial-product desk Copilot**.

The Copilot converts a natural-language request into an end-to-end internal product-analysis workflow:

1. clarify material ambiguity;
2. screen candidates across the applicable product masters;
3. validate metric and population compatibility;
4. run deterministic filters, rankings, aggregates, and calculations;
5. explain product facts, risks, and limitations from available data; and
6. return sources, calculations, exclusions, missing values, and the snapshot date as a reproducible evidence packet.

Competition requirements and official guidance remain the priority. Product analysts, product desks, and sales-support staff are representative users of the workflow, but the initial design does not choose one of them as the primary paying user.

The Copilot provides objective candidate screening under stated conditions. It does not become a personalized suitability or portfolio-recommendation system merely because a user uses words such as “recommend” or “best.”

## Reasons

- The framing directly covers every required competition behavior instead of adding a parallel commercial feature set.
- It describes a complete job with an inspectable output, not only a conversational interface.
- It makes deterministic execution, comparison validity, evidence, missingness, and risk controls part of the user value.
- It supports credible workplace scenarios while remaining within the supplied data and competition rules.
- It avoids requiring customer profiles, brokerage accounts, live market feeds, or investment-advice policy that the initial scope cannot support.

## Rejected Alternatives

### Natural-language search and QA chatbot

Rejected as the product definition because it describes the interface but not the complete job. It can retrieve facts but does not necessarily validate comparisons, produce reproducible calculations, explain exclusions, or leave evidence that a financial user can defend.

### Personalized investment-recommendation Agent

Rejected for the initial competition scope because the supplied data does not contain the customer profile, suitability policy, account state, or governance needed for personalized advice. This direction would add regulatory risk without improving the core evaluated behaviors.

### Optimize first for one commercial persona

Rejected because the project is a competition submission and the user explicitly chose evaluation fit over selecting one initial paying user. A persona-first design could overfit the workflow, interface, or feature priority to one department and reduce coverage of hidden evaluation questions.

### General-purpose autonomous multi-agent platform

Rejected because architectural breadth is not a user outcome and creates additional failure modes. Multi-agent orchestration may be considered later as an implementation choice only if it measurably improves the approved behavior.

## Consequences

- Feature proposals must map to the organizer's query, comparison, calculation, grounding, clarification, or risk-control requirements.
- Demonstrations and test scenarios should show the complete flow from request to candidates, compatibility decision, answer, and evidence.
- Candidate screening, comparison validation, evidence, exclusion reasons, and missingness handling are core product behavior rather than optional compliance features.
- Personalized suitability, portfolio allocation, order execution, and persona-specific production workflows remain out of scope unless a later approved decision changes the product boundary.
- This decision does not approve the proposed SQL-first hybrid or any other implementation architecture. Architecture requires a separate ADR and explicit approval.

## Supersession

This decision does not supersede ADR-0001 or ADR-0002. It adds the approved product frame within their planning and repository constraints.
