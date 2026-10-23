# Subquestion and topic-scope validation

The automated suite covers directed/transitive requirements, invalid cycles, lossless crop coverage, stale approvals, independent-first Short variants, time budgets, persistence, explicit approval, and extracted content of generated PDFs. Topic tests cover motion/energy removal, gravity/circular-motion direction, inseparable multi-topic tasks, shared context, conditional links, all 24 content deductions and the requirement to retain an actual target task.

A browser walkthrough also checked filtered previews, opening the full original for editing, manual graph/topic approval, Short PNG rendering, paper generation, model-unavailable fallback, and desktop/mobile layout. The browser bank uses synthetic source text with known dependencies; it is not evidence of automatic semantic accuracy.

The six uploaded-paper OCR caches were checked for structural part proposals: 20 of 21 structured parent questions produced valid lossless partitions (10/10 on 2025 Paper 2, 8/9 on 2026 Paper 2 and 2/2 on 2026 Paper 1B). This measures geometric partition validation, not correct interpretation of every boundary, diagram or dependency. No proposal was automatically approved. The historical Full crop baseline remains unchanged.

Actual local Qwen2.5 1.5B Q4_K_M CPU inference was attempted after the verified model became available. The four OCR/PDF disagreements remained unresolved: three failed source-quotation checks and one abstained. Results are saved separately in `TEST SAMPLES/results/language-review-live.json`.

The model was also run on a synthetic three-part dependency example. It proposed reversed/cyclic prerequisites and unrelated topic labels; validation rejected its graph and retained the conservative original. The later trace, including synthetic inputs, raw model output and validated outcome, is saved in `TEST SAMPLES/results/dependency-review-live.json`. This is a failed inference diagnostic, not an approved dependency map. The small model has not demonstrated reliable semantic dependency classification. A well-formed proposal would still require human review of the original paper, particularly diagrams and implicit context.

The curriculum policy is a content-based deduction from the uploaded IB teacher support material, printed pp. 2–17. It does not use the example teaching route or claim an official IB prerequisite hierarchy. Its root PDF is generated from the same versioned JSON used by the filters: `python tools/build_roadmap.py`.
