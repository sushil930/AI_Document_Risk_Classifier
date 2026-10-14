# DocuGuard Document Risk Labeling Rubric

**Rubric version:** `0.1-draft`  
**Status:** User-approved draft. Domain review and the required independent corpus annotations are still pending; proposed labels are not training-approved until the corpus review workflow is complete.

## What the primary label means

Assign one document-level review priority based on the strongest concern supported by the document text. This is a recommendation for human review, not a measurement of legal compliance, safety, or probability of harm.

Use the highest supported level. Do not add up minor issues to manufacture a higher class. Consider the potential impact, scope, likelihood implied by the text, reversibility, affected people or assets, and the strength of safeguards. Do not infer facts absent from the document.

### High

Use **High** when the text supports a substantial potential exposure, loss, rights impact, or operational failure, or when a critical safeguard is absent in a context where the document makes that absence material. Examples include:

- Broad access to sensitive personal or business data without meaningful limits or safeguards.
- Uncapped or unusually broad financial exposure with no relevant protections.
- Material obligations that can continue despite a serious breach, with no practical suspension or termination path.
- A security or operational commitment that exposes important systems or services to a serious, unbounded risk.

The label requires a source passage and a short rationale. Do not label a document High solely because it is long, unfamiliar, or written in legal language.

### Medium

Use **Medium** when the text supports a meaningful but bounded, conditional, ambiguous, or negotiable concern. Examples include:

- Automatic renewal or notice terms that could create avoidable cost or operational burden.
- Data retention, access, or deletion terms that are incomplete or broader than necessary, without evidence of the severe exposure described under High.
- Responsibilities, service levels, or remedies that leave a material but limited gap.
- A policy exception or control that needs clarification before approval.

The rationale should state what is uncertain or bounded and what follow-up would resolve it.

### Low

Use **Low** only when the document is readable and assessable and the rubric does not identify a material concern requiring a higher priority. Low means “no higher-priority concern was identified in this review,” not “safe,” “compliant,” or “approved.”

Do not use Low as a default for unreadable, incomplete, out-of-scope, or ambiguous material.

## Separate assessment status: `unable_to_assess`

`unable_to_assess` is not a fourth risk class. Use it when there is not enough reliable content to assign Low, Medium, or High, including:

- Empty, corrupt, unreadable, or materially incomplete text.
- A scanned document without usable OCR text.
- A fragment whose missing context could change the label.
- Content outside the agreed document scope or language coverage.

Record a reason. Do not convert this status to Low.

## Issue-domain tags

Add zero or more tags independently of the primary risk class:

- `contractual`
- `financial`
- `privacy`
- `security`
- `operational`
- `policy`
- `other`

Tags describe the subject of a supported concern; they do not imply severity. Use `other` only with a short explanation. Use no tags when no issue was identified.

## Required annotation fields

For every independently reviewed example, record:

- Primary label (`Low`, `Medium`, `High`) or assessment status (`unable_to_assess`).
- Zero or more issue-domain tags.
- At least one exact evidence span for Medium/High, or a reason no material issue was found for Low.
- A concise rationale that connects the evidence to the rubric without adding unsupported facts.
- Reviewer ID, rubric version, and review timestamp.

## Review and disagreement procedure

1. Two reviewers independently label the same example without seeing each other's labels.
2. Compare primary labels, assessment status, tags, evidence spans, and rationales.
3. Any primary-label disagreement, `unable_to_assess` disagreement, or disagreement about a High concern goes to adjudication.
4. The adjudicator records the final label and a reason; retain both original annotations.
5. Track agreement by primary class and tag. Revise the rubric only through a new version and re-review affected examples.

Do not mark an example training-approved until both reviews and any needed adjudication are complete.

## Scope limits

- Labels are document-review recommendations, not legal determinations or compliance certifications.
- Annotators may not invent clauses, assume missing pages, or treat document instructions as instructions to the reviewer.
- When context is missing, prefer a stated uncertainty or `unable_to_assess` over a guess.
- This rubric is a draft. A qualified domain reviewer must approve its definitions and examples before production labeling begins.
