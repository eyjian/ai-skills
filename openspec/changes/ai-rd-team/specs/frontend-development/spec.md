## ADDED Requirements

### Requirement: Vue 3 Composition API enforcement
frontend-dev SHALL 使用 Vue 3 Composition API（`<script setup>` 语法）+ TypeScript 严格模式。

#### Scenario: Component implementation
- **WHEN** frontend-dev 创建 Vue 组件
- **THEN** 组件使用 `<script setup lang="ts">`，不使用 Options API

### Requirement: API integration with backend
frontend-dev SHALL 通过 Axios 对接后端 gRPC-Gateway 暴露的 HTTP API，或在后端未就绪时使用 Mock。

#### Scenario: API connection status reporting
- **WHEN** frontend-dev 完成开发
- **THEN** 完成报告中列出每个 API 的对接状态（已对接 / Mock 中）

### Requirement: Optional activation
frontend-dev SHALL 仅在画像 `has_frontend = true` 时被协调者派发。

#### Scenario: Pure API project
- **WHEN** 画像为 go-kratos-api（has_frontend: false）
- **THEN** 协调者不派发 frontend-dev Agent
