# Architecture Review Rubric

## Conceptual Fit

Flag a design when decomposition mirrors implementation nouns but not a clear concept boundary.

Good signs:

- The object prevents invalid combinations that callers would otherwise create.
- The object maps to a stable upstream or domain concept.
- The object hides a shape conversion that callers should not learn.
- The object makes future extension local without adding speculative layers.
- The object has a crisp name for the invariant it owns.

Bad signs:

- The object is just a named subset of an option array or payload.
- The object exposes a generic conversion method such as `getContext()` but the returned data is incomplete until another layer mutates it.
- The object forces users to understand both the upstream option tree and the project-specific taxonomy.
- The object cannot represent valid upstream states.
- The object exists because the implementation had several groups of parameters, not because callers have several concepts.

Keep separation when the split owns at least one real boundary:

- Different lifecycle or stability.
- Different authority or security exposure.
- Different secret exposure boundary.
- Different target adapters or wire formats.
- Compatibility layer isolation.
- Independently testable invariant that callers would otherwise violate.

## Finding Granularity

Prefer one integrated architecture finding when several local issues share the same root cause.

Use an integrated finding when:

- Several new classes split one upstream option/payload/protocol boundary.
- A factory/adapter must reassemble fragments from those classes to produce the final target shape.
- The user still needs to understand the upstream structure plus the project-specific split.

Default to drafting the integrated finding first when public fragments are merged into one final external shape. Split into separate findings only after proving that each fragment owns a different lifecycle, security boundary, compatibility boundary, or invariant.

Use separate findings when:

- Each class owns a different invariant or lifecycle.
- Each issue has a distinct fix.
- One issue is a confirmed runtime bug and another is only a design risk.

The finding subject should be the abstraction split, not only the first suspicious method.

## External API Boundary

For adapters around libraries, protocols, runtimes, or wire formats:

- Confirm the expected argument shape from upstream documentation or source.
- Identify whether the project object is a domain model, a configuration model, or an adapter output. Do not let one object pretend to be all three.
- If the external API passes an option envelope or payload through to a lower runtime/protocol, consider that envelope a candidate abstraction boundary. If the project object cannot produce the final target shape and a factory/caller must wrap or mutate it, review that as translation boundary leakage.
- Split payload ownership from envelope/orchestration. A factory may choose the target API and apply a shallow connection envelope, but it should not need to know how to assemble the upstream option payload, inject secrets, or merge fragments from public value objects.
- Name conversion functions by target boundary, for example `for<ExternalTarget>()`, rather than a generic `getContext()` when shapes differ.
- Test each target boundary shape directly. Avoid relying only on reflection over private helpers.
- Keep secrets out of broad public context arrays unless the method name makes the exposure explicit.

## Public API Cost

Public classes and constructor parameters should pass at least one of these tests:

- They encode a real invariant.
- They reduce the number of concepts a user must know.
- They create a stable compatibility boundary for an existing migration.
- They isolate a volatile external API behind a deliberate adapter.

If none pass, prefer a smaller API: named constructors, one value object with explicit methods, or a private adapter.

When removing public fragment classes is plausible, prefer this alternative order:

1. A single public value object with named constructors that encode the meaningful setup modes.
2. Target-specific conversion methods on that value object when the output shape is part of the public contract.
3. A private/internal adapter only when the target shape is not a user-facing concept.

Do not use an internal adapter proposal to preserve unnecessary public fragment classes.

## Change Request Threshold

Write a Medium change request, not only an open question, when Direct fact or primary-source-backed Contract inference shows all of these:

- A new public abstraction does not map to the upstream boundary, user task, or owned invariant.
- It leaves final translation responsibility to a factory, adapter, or caller.
- It increases public API surface or cognitive load without a compensating boundary.

End as an open question only when the missing information is product intent, roadmap intent, or an unverified external API fact.

## Cognitive Load Test

Ask what the user must learn after the PR:

- New class names.
- New constructor combinations.
- New precedence or compatibility rules.
- New docs examples.
- Upstream concepts that still leak through.

Then ask what they no longer need to know. If the second list is not clearly shorter or safer, the abstraction is suspect.

## Evidence Ladder

Use these labels internally while reviewing:

- **Direct fact**: visible in diff, tests, docs, runtime logs, or primary source.
- **Contract inference**: implied by public names, docs, tests, or changelog.
- **Design risk**: likely future maintenance/user cost, not a current runtime failure.
- **Open question**: cannot be decided without product/roadmap intent.

Only direct facts should support runtime-bug findings. Contract inference and design risk are still valid architecture review findings, but label them accurately.

## Severity Calibration

- Critical: confirmed runtime breakage, security regression, or public API behavior that cannot work as documented.
- Medium: design risk, public API cost, missing invariant, misleading contract, or missing boundary test.
- Low: clarity or naming issue with limited misuse risk.

Do not label an external API concern critical/blocking unless the exact outgoing argument shape in current HEAD is verified against primary source and the code cannot work, or it creates a security regression. Architecture-level redesign requests are usually Medium change requests.

## Review Wording

Use this shape for architecture findings:

```text
[severity] <file:line> <short title>

The current abstraction splits <X> into <Y>, but that split does not own a clear <semantic boundary/invariant/translation boundary>. As a result, <concrete complexity or maintenance cost>. Prefer <smaller alternative> because it makes <boundary/invariant/user operation> explicit.
```

For change requests about leaked translation boundaries:

```text
[medium] <file:line> <abstraction> が <external boundary> を所有していません

Direct fact: <diff/primary sourceから言えること>.
Design risk: 現状の分離では <factory/adapter/caller> が最終的な <external option/payload shape> を知る必要があり、利用者/API保守の複雑さを増やしています。
Request: <single value object / named constructor / target-specific conversion method / private adapter> に寄せ、<external boundary> へ渡す形をその責務の型が生成する設計に変更してください。
Open question: もしこの分離が別の互換要件や境界を所有しているなら、その要件を public contract として示してください。
```

For integrated findings about an abstraction split:

```text
[medium] <file:line> <abstraction split> が <target concept> の単位を表していません

Direct fact: <new classes/methods> split <configuration/payload/protocol> into <parts>, while primary source shows <target concept/envelope/condition>.
Design risk: 現状の分離は <user/factory/adapter> に <upstream shape and project taxonomy> の両方を理解させ、抽象化が複雑さを下げていません。
Request: 公開面は <single value object with named constructors> に寄せ、<target concept or upstream option payload> をその型が所有する設計へ変更してください。Factory は必要なら接続先 API ごとの外側 envelope 選択だけを担います。target-specific adapter を使う場合も、公開 fragment class を正当化するためではなく、外部 API 変換を閉じるために使います。
Open question: この分離が別の lifecycle/security/compatibility boundary を所有しているなら、その境界を public contract として示してください。
```

Do not overstate. If the code works today but creates future API cost, call it a design risk, not a runtime bug.
