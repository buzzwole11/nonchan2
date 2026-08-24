# ODAI

> **Scroll less. Participate more.**
> 毎日ひとつのお題に、写真1枚で答えるだけのSNS。

Daily Prompt Social Network（日替わりお題SNS）のプロダクト企画リポジトリ。

## ドキュメント

- [仕様書 v1.2](docs/SPEC.md) — 現行版。主要な設計決定（D-01〜D-12）、安全要件、KPI、リスクを含む
- [M0 検証キット](docs/m0/README.md) — **実施しないと決定**。お題ストックとヒアリング台本として転用中

## 現在の状態

**M1（クローズドβ）の実装待ち。**

事前検証（M0）は実施しないと決定した（仕様書 §4）。したがって
**R-01「お題では毎日開く理由にならない」は未緩和のまま残る**。
M1 が事実上の最初の検証になるため、KPI 計測を後付けにせず最初から実装し、
β開始14日目の継続率を必ず算出して、M2（一般公開）に進む前に設計を見直せるようにする。

### 技術スタック（確定）

Expo（React Native）+ TypeScript / Supabase（Auth・Postgres・RLS・Storage）/ Expo Notifications。
詳細と選定理由は [仕様書 §10.3](docs/SPEC.md#103-技術スタック確定--u-05-解決済み)。
