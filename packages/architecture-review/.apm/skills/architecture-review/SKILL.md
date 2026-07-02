---
name: architecture-review
description: PR や差分を、契約面・責務/lifecycle・変換/依存・実行時進化性の観点に分割してアーキテクチャレビューし、根拠付き finding と具体的な修正戦略に統合する必要があるときに使用する。特定言語やフレームワークに依存しない汎用レビューに対応。
---

# Architecture Review

PR や差分を、実装詳細の前に「どの設計原則が守られているか」と「公開・観測可能な契約として維持する価値があるか」からレビューする。
具体 PR から得た知識は、そのまま規則にせず、再利用できるソフトウェア設計原則へ抽象化して扱う。

この skill は単独 reviewer ではなく、Principle ごとの reviewer を束ねる Review Lead として動く。Review Lead は独自の設計 finding を足さず、証拠パケットの作成、subagent の進行管理、重複統合、severity 調整、最終文面化だけを担当する。

## Evidence Discipline

レビューでは、次を分けて扱う。

- **Direct fact**: PR 本文、diff、関連 issue、既存コード、docs、tests、一次情報から直接言えること。
- **Design inference**: direct fact から導ける責務境界、契約、進化性、保守性への影響。
- **Open question**: 現状の diff だけでは判断できない前提、隠れた lifecycle、互換性、運用要件。

外部 API、protocol、runtime option、言語/runtime version に依存する判断は、推測ではなく一次情報や現行 repo 設定を確認してから扱う。

既存の PR review、review comment、approval、changes requested、discussion thread など、人間レビュー由来の情報は取得・閲覧・要約・照合しない。finding の根拠にも、Repair Strategy phase の入力にも使わない。レビューは PR 本文、diff、関連 issue 本文、既存コード、docs、tests、外部一次情報から独立に構成する。

## Repair Strategy Separation

Principle reviewer は抽象的なソフトウェア設計原則による評価を保つ。問題を見つけた段階で、個別実装方針まで背負わない。

具体的な修正方針は、Principle review とは別の **Repair Strategy phase** で作る。これにより、reviewer は担当 Principle の検査に集中し、Review Lead は複数 finding と repair constraints を統合して、実装者が次に動ける戦略へ落とせる。

Principle reviewer が出すのは次までである。

- **Finding candidate**: direct fact、principle、design inference、user impact。
- **Repair constraints**: 修正方針が満たすべき制約。例: `実行 lifecycle の owner に生成 policy を混ぜない`, `default/custom/compatibility 経路は同じ抽象境界を通る`, `request 正規化 owner を分裂させない`。
- **Open question**: 修正戦略を決める前に必要な未確認前提。

Repair Strategy phase では、統合済み finding と repair constraints を入力に、次を必ず具体化する。

- **Target owner map**: 修正後に各 phase や contract をどの型・層・設定境界が所有するか。
- **Code movement**: どの class/function/module/constructor 引数/docs/test を追加・削除・移動・縮小するか。
- **Contract update**: public API、設定、docs、CHANGELOG、tests のどこを変更して契約を固定するか。
- **Tradeoff**: その方針でどの Principle 上の複雑さが減り、何を意図的に残すか。

## Review Team

各 reviewer は自分の Principle cluster だけを主担当にする。横断的な兆候を見つけた場合は、該当 reviewer へ渡す候補として記録し、全観点を自分で抱え込まない。

| Role                              | Principle ownership                                                                                             | Role prompt                                   |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Contract Surface Reviewer         | Semantic boundary, Invariant ownership, Cognitive load, API reversibility, Documentation as contract            | `agents/contract-surface-reviewer.md`         |
| Responsibility Lifecycle Reviewer | Responsibility cohesion, Lifecycle ownership, Extension mechanism, State and side effects                       | `agents/responsibility-lifecycle-reviewer.md` |
| Translation Dependency Reviewer   | Translation boundary, Dependency direction, Information hiding, Passthrough envelope                            | `agents/translation-dependency-reviewer.md`   |
| Runtime Evolution Reviewer        | Substitutability, Compatibility and migration, Security boundary, Error contract, Testability and observability | `agents/runtime-evolution-reviewer.md`        |
| Repair Strategy Synthesizer       | Finding integration から具体修正戦略への変換、owner map、code movement、contract/test/docs plan                 | `agents/repair-strategy-synthesizer.md`       |
| Review Lead                       | Evidence quality, Finding integration, reviewer conflict resolution, severity calibration                       | this `SKILL.md`                               |

Subagent を起動できる環境では、上記 role prompt と共通の evidence packet を渡して並列にレビューさせる。利用できない場合は同じ role 分担を逐次実行し、fallback したことを短く明記する。

逐次 fallback の粒度は role 単位にする。4 つの Principle reviewer prompt を順に適用し、finding 候補と repair constraints だけを内部メモとして残してから、Repair Strategy Synthesizer へ渡す。

Principle reviewer の role prompt として読むのは4つの Markdown file だけである。Repair Strategy phase では `agents/repair-strategy-synthesizer.md` を読む。呼び出し側が `agents/*.md` とまとめて指示していても、この phase 別の読み分けを固定ルールとして優先する。

## Workflow

1. **証拠パケットを作る**
   - PR 本文、diff、関連 issue、既存コード、ユーザー向け docs、テストを読む。
   - 外部 API 境界がある場合は一次情報を確認する。ライブラリ、プロトコル、runtime option の仕様を推測で扱わない。
   - 既存の PR review、review comment、approval、changes requested、discussion thread は読まない。`gh pr view` や `gh api` を使う場合も、comments/reviews/reviewThreads を取得しない。
   - 特定 commit や過去 revision をレビューする場合、現在の PR 本文や docs が対象 revision とずれることがある。PR 本文は意図の補助証拠として扱い、最終判断は対象 revision の diff、該当時点の変更ファイル、一次情報に寄せる。
   - 追加・変更された public class/function/module、constructor 引数、method、返り値、docs 記載、observable runtime boundary を列挙する。
   - 変更された既存型や層について、PR 前後で増えた責務を短い表にする。lifecycle を持つ処理は phase ごとに owner を書く。
   - default/custom/compatibility など複数経路が同じ対象を扱う場合は、各経路の owner と call graph を並べる。
   - ある層が抽象 interface を呼んでいるだけでも、呼び出しタイミング、fallback 選択、無効状態の判定、生成結果の検証を決めているなら、その lifecycle phase の owner 候補として扱う。
   - direct fact と design inference を混ぜない形で、各 reviewer へ渡せる短い context にまとめる。

2. **Principle reviewer を並列または逐次に起動する**
   - 各 role prompt を読み、同じ evidence packet と PR 対象を渡す。
   - 各 reviewer には「担当 Principle だけを深掘りする」「finding 候補は direct fact、principle、impact、repair constraints を分けて書く」「具体修正戦略は書かない」「確認不能な前提は open question にする」と明示する。

3. **結果を統合する**
   - 同じ根本原因から出ている複数候補は、個別 class や小症状へ分解しすぎず、1 つの設計 finding として統合する。
   - reviewer 間で前提や severity が割れた場合、親が解釈で上書きせず、該当 reviewer へ差し戻して再確認させる。
   - 親が新しい finding を思いついた場合も、その Principle を担当する reviewer へ差し戻し、reviewer の回答を根拠に統合する。
   - direct fact が不足する候補は finding にせず、open question または検証メモとして残す。
   - 統合 finding ごとに repair constraints をまとめる。ここではまだ具体修正戦略へ展開しない。

4. **Repair Strategy を作る**
   - 統合 finding、repair constraints、既存コードの owner map、docs/tests を `Repair Strategy Synthesizer` へ渡す。
   - Synthesizer には「新しい finding を追加しない」「既存 finding を実装可能な方針へ変換する」「target owner map、code movement、contract update、tradeoff を必ず出す」と明示する。
   - Review Lead は repair strategy が `専用境界へ寄せる`、`owner を明確にする`、`docs に書く` だけで止まっていないか確認する。抽象的な場合は Synthesizer へ差し戻す。

5. **レビューを書く**
   - Findings-first で、重要度順に具体的なファイル・行を示す。
   - 「これはバグ」「これは設計リスク」「これは確認質問」を混ぜずに書く。
   - 方針変更要求は、confirmed runtime breakage や security regression でない限り `Medium change request` 相当にする。
   - 各 finding に **Recommended repair strategy** を付ける。これは Repair Strategy Synthesizer の出力を要約し、target owner map、code movement、contract update、どの Principle 上の複雑さが減るかを明示する。
   - 最終レビューは、ジュニアエンジニアにも伝わる密度まで畳む。subagent の表や全論点を貼らず、1 finding につき `結論`、`根拠となる事実`、`設計上の問題`、`修正方針` の4点へ圧縮する。
   - 専門用語は消さない。`lifecycle owner`、`factory boundary`、`config boundary`、`public contract`、`extension mechanism` など、覚えてほしい語は残し、その直後に今回の PR で何を意味するかを1文で説明する。
   - finding ごとの Recommended repair strategy は1つに絞る。複数案を並べる場合は「採用候補」ではなく、採用しない理由を添えた補足に留める。
   - findings がない場合は、残る test gap や未確認の外部仕様だけを短く示す。

## Final Review Style

最終出力は「深い分析の要約」であって「分析ログ」ではない。読者がジュニアエンジニアでも次の修正に進めるように、次の形を基本にする。

- **結論**: 何を変えてほしいかを最初に書く。例: `生成判断は dedicated factory へ寄せ、実行 handler から外してください。`
- **根拠となる事実**: diff、既存コード、docs、tests、一次情報から直接言える事実だけを書く。
- **設計上の問題**: 覚えてほしい専門用語を残して説明する。例: `lifecycle owner が混ざっています。Handler は実行 lifecycle の owner で、生成 policy の owner ではありません。`
- **修正方針**: owner map と code movement を短く書く。例: `default 実装も custom 実装も同じ factory interface を通し、アプリ全体の差し替えは既存 config boundary に置きます。`

レビュー本文では、同じ根本原因を複数の小さな指摘に割りすぎない。たとえば「拡張点を追加した結果、生成、変換、実行の責務が複数層へ散っている」場合は、責務分散を1つの主 finding にまとめ、その中で各 class/module の移動先を示す。

## Reviewer Handoff Contract

各 reviewer の出力は次の形に揃える。

- **Direct facts used**: ファイル、行、PR 本文、docs、一次情報など。
- **Principle assessment**: 担当 Principle ごとの評価。問題なしの Principle も短く理由を書く。
- **Finding candidates**: severity、principle、direct fact、design inference、user impact、repair constraints。
- **Open questions**: finding 化しない未確認前提。
- **Cross-role handoff**: 他 reviewer に渡すべき兆候。

Review Lead はこの形式以外の自由文をそのまま最終レビューへ貼らない。必ず証拠、Principle、影響、提案へ正規化する。

## Repair Strategy Handoff Contract

Repair Strategy Synthesizer の出力は次の形に揃える。

- **Inputs used**: 統合 finding、repair constraints、既存コード/docs/tests の参照。
- **Target owner map**: lifecycle phase、translation boundary、public/config/docs/test contract ごとの修正後 owner。
- **Concrete change set**: 削るもの、移すもの、追加するものを class/function/module/docs/test 単位で列挙する。
- **Contract and verification plan**: どの公開契約をどう固定し、どの test/doc/changelog を更新するか。
- **Tradeoffs and remaining questions**: 意図的に残す互換性や、判断に必要な未確認前提。

Synthesizer は新しい設計 finding を追加しない。新しい問題に気づいた場合は、Review Lead へ差し戻し対象として記録する。

## Principle Boundaries

- **Semantic boundary**: 新しい型や層が、利用者の作業単位、外部仕様の単位、ドメイン概念のどれを表すか。
- **Invariant ownership**: 無効な組み合わせ、秘密情報、互換条件、fallback 条件をどの型や層が保証するか。
- **Responsibility cohesion**: 1 つの型や層が持つ変更理由はまとまっているか。新しい責務が既存責務の自然な延長か、実装都合で同居していないか。
- **Lifecycle ownership**: 入力解決、対象選択、生成、変換、初期化、実行、post-processing、cleanup の各 phase をどの型や層が所有するか。
- **Translation boundary**: 内部表現を外部 API、プロトコル、runtime 引数、wire format へ変換する責務がどこにあるか。
- **Dependency direction**: 高水準 policy が低水準 detail へ過剰に依存していないか。adapter、factory、config、runtime 呼び出しの向きが安定した抽象へ向いているか。
- **Information hiding**: caller や factory が下位表現、内部配列、秘密値、初期化順序を知りすぎていないか。
- **Substitutability**: interface、base class、adapter、compatibility layer の実装差し替えで、既存の観測可能な契約が保たれるか。
- **Extension mechanism**: 拡張点が明示的で、default/custom/compatibility 経路が同じ抽象境界を通るか。
- **Compatibility and migration**: 既存契約を壊さずに移行できるか。deprecated alias、互換レイヤ、段階移行、fallback が利用者に予測可能か。
- **Security boundary**: 秘密情報、権限、外部入力、unsafe option がどの層で閉じているか。ログ、例外 context、public return 値へ漏れないか。
- **State and side effects**: lazy initialization、global state、singleton、cache、transaction、cleanup などの副作用がどこで発生し、重複・迂回・後上書きされないか。
- **Error contract**: 異常系の検出タイミング、例外種別、context、fallback が利用者にとって一貫しているか。
- **Passthrough envelope**: 外部 API が受け取った option や payload を下位 runtime や別プロトコルへそのまま渡す場合、その外側形状を誰が所有するか。
- **Cognitive load**: 利用者が新しく覚える概念数が、誤用防止や変更局所化によって回収されているか。
- **API reversibility**: 一度公開した名前、constructor 形状、返り値、docs サンプルを後から畳めるか。
- **Testability and observability**: tests が中間実装ではなく利用者に約束する境界を固定しているか。失敗時の診断情報が契約理解を助けるか。
- **Documentation as contract**: user docs、design docs、CHANGELOG、サンプルコードが実装と同じ API shape を固定しているか。

## Generic Heuristics

- runtime breakage を critical にするのは、現在の対象 revision で外部 API 境界に渡る実引数や observable behavior が一次情報と矛盾していると確認できる場合だけにする。未確認や設計上の弱さは medium 以下の design risk として扱う。
- `assert()`、debug-only guard、type assertion を契約表現に使っている場合は、本番契約か開発時ガードかを見る。新規 public API の「禁止」「同時指定不可」「検出できる」は本番契約に見えやすい。
- 秘密情報や権限情報をラップする変更では、生値化の場所だけでなく、public method、log、exception、return value に秘密情報が含まれるかも確認する。
- docs のサンプルは API shape の事実上の固定点になる。サンプルが複雑なら、その複雑さ自体をレビュー対象にする。
- 「責務分離が明確」は、それぞれの責務が外部仕様・不変条件・利用者作業単位・lifecycle phase のどれかに対応している場合だけ採用する。
- 単一 Value Object や named constructor を提案する前に、分離された各型が独自の lifecycle、security boundary、安定度、複数 target 変換、互換レイヤ隔離を持っていないか確認する。これらを持つ場合は分離維持が正当化されうる。
- 生成、変換、実行を含む PR では、責務マップを作り、default/custom/compatibility 経路が同じ抽象境界を通るかを見る。
- 既存基底型や互換レイヤに default constructor、lazy initialization、global state 参照などの初期化副作用がある場合は、外部注入や遅延生成がその副作用を迂回・重複・後上書きしていないかを見る。これは初期化責務と変換責務の owner が一致しているかの確認として扱う。
- 実行 lifecycle を管理する層に、生成・変換・生成結果検証など別 phase の判断を足さない。既存コードコメントや class/module 名が Handler、Invoker、Facade、Runner、Command、Job など実行や orchestration を示す場合、その層は原則として実行 lifecycle の owner として扱い、生成 policy の owner 候補から外して考える。
- Factory/creation extension を追加する PR では、default 経路だけ直接生成し、custom 経路だけ Factory へ逃がす分岐を疑う。default 実装も Factory として表現し、default/custom/compatibility が同じ factory boundary を通る形を優先する。
- Router、Dispatcher、Controller、Command handler などの orchestration 層は、対象選択や実行順序の owner であって、具体 object 生成 policy や fallback の owner とは限らない。抽象を導入したなら、生成判断、生成結果検証、fallback は dedicated boundary へ寄せられないか確認する。
- Repair Strategy phase では、拡張点がシステム全体に効く設定で、request ごとの runtime 判断ではない場合は、constructor DI だけでなく既存の config、module registration、DI container、provider registry、environment settings の導線に置く方が利用者作業単位に合うかを見る。
- Repair Strategy phase では、「X に責務を持たせない」と判断した場合は、必ず「代わりに Y へ寄せる」「X から削る変更」「Y に追加する変更」をセットで書く。否定だけのレビューにしない。

## References

必要なら [references/review-rubric.md](references/review-rubric.md) を読む。
Principle reviewer へ渡す role prompt は `agents/*.md` を使う。
